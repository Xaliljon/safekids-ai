"""YOLOX-Tiny: the first production DetectorFamily (Sprint 19, ADR-0003).

A from-scratch, anchor-free, multi-scale detector — CSPDarknet-tiny-style
backbone, a PAFPN-lite neck, and a decoupled head over strides
(8, 16, 32) — reimplemented independently in PyTorch (Apache-2.0 in
spirit and in fact: no Ultralytics/AGPL code anywhere, ADR-0003). It
speaks the same single-tensor DetectorFamily contract as ``tiny-ssd``:
one forward pass returns ``(batch, total_anchors, 5 + num_classes)`` —
box regression (4, raw grid-relative offsets), objectness, class scores.

**What is simplified, and why** (so nobody mistakes this for the
published YOLOX paper's exact recipe):

- No "Focus" stem or SPP block — a plain strided conv stem and no extra
  receptive-field bottleneck. Fewer parameters, faster to reason about;
  revisit if the real dataset's recall plateaus on partially-occluded
  people.
- Target assignment is **not** the paper's Sinkhorn/optimal-transport
  SimOTA. It uses a center-region candidate set (anchor points whose
  center falls inside the GT box, or — for objects smaller than every
  grid cell — the single nearest anchor point) and keeps the ``k``
  candidates closest to the GT center, ``k = min(10, candidates)``. This
  is a distance-prior simplification of "dynamic-k top-IoU" assignment,
  not the exact paper algorithm. It is cheap (no extra forward pass to
  cost-match) and directionally correct (candidates near an object's
  center become positive); documented here as the known simplification
  to revisit if precision plateaus.
- Box regression loss is IoU-based (not the paper's IoU + L1 combo).

Train-mode forward returns raw obj/cls logits (for
``binary_cross_entropy_with_logits``); eval-mode forward applies sigmoid
before returning, so the exported ONNX graph and ``decode()`` never
need to guess which mode produced a tensor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from guardian_ai.training.errors import TrainingConfigurationError

if TYPE_CHECKING:
    import torch

_STRIDES: tuple[int, ...] = (8, 16, 32)
_BOX_FIELDS = 5  # cx, cy, w, h, objectness
_MAX_CANDIDATES_PER_GT = 10
_SCORE_FLOOR = 0.05
_NMS_IOU_THRESHOLD = 0.45
_MAX_DETECTIONS = 100
_BOX_LOSS_WEIGHT = 5.0
_CLS_LOSS_WEIGHT = 1.0


def _make_conv_bn_act(in_channels: int, out_channels: int, kernel_size: int, stride: int) -> Any:
    from torch import nn

    padding = kernel_size // 2
    return nn.Sequential(
        nn.Conv2d(in_channels, out_channels, kernel_size, stride, padding, bias=False),
        nn.BatchNorm2d(out_channels),
        nn.SiLU(inplace=True),
    )


def _make_bottleneck(channels: int) -> Any:
    from torch import nn

    class Bottleneck(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.conv1 = _make_conv_bn_act(channels, channels, 1, 1)
            self.conv2 = _make_conv_bn_act(channels, channels, 3, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return x + self.conv2(self.conv1(x))  # type: ignore[no-any-return]

    return Bottleneck()


def _make_csp_layer(in_channels: int, out_channels: int, depth: int) -> Any:
    """A CSP block: split, N residual bottlenecks on one branch, fuse."""
    from torch import nn

    hidden = out_channels // 2

    class CspLayer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.reduce = _make_conv_bn_act(in_channels, hidden, 1, 1)
            self.shortcut = _make_conv_bn_act(in_channels, hidden, 1, 1)
            self.blocks = nn.Sequential(*[_make_bottleneck(hidden) for _ in range(depth)])
            self.fuse = _make_conv_bn_act(hidden * 2, out_channels, 1, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            import torch

            main = self.blocks(self.reduce(x))
            side = self.shortcut(x)
            return self.fuse(torch.cat([main, side], dim=1))  # type: ignore[no-any-return]

    return CspLayer()


def _build_backbone_and_neck(width: int) -> Any:
    """CSPDarknet-tiny-style backbone + PAFPN-lite neck.

    ``width`` is the base channel count (24 for yolox-tiny's 0.375 width
    multiplier on the paper's 64-channel stem). Returns a module whose
    forward(x) yields the three fused feature maps (P3/P4/P5, strides
    8/16/32) the head consumes.
    """
    from torch import nn

    c1, c2, c3, c4 = width * 2, width * 4, width * 8, width * 16  # 48,96,192,384

    class BackboneNeck(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.stem = _make_conv_bn_act(3, width, 3, 2)
            self.stage1 = nn.Sequential(
                _make_conv_bn_act(width, c1, 3, 2), _make_csp_layer(c1, c1, 1)
            )
            self.stage2 = nn.Sequential(_make_conv_bn_act(c1, c2, 3, 2), _make_csp_layer(c2, c2, 3))
            self.stage3 = nn.Sequential(_make_conv_bn_act(c2, c3, 3, 2), _make_csp_layer(c3, c3, 3))
            self.stage4 = nn.Sequential(_make_conv_bn_act(c3, c4, 3, 2), _make_csp_layer(c4, c4, 1))
            # top-down (FPN)
            self.reduce_c5 = _make_conv_bn_act(c4, c3, 1, 1)
            self.fuse_p4 = _make_csp_layer(c3 * 2, c3, 1)
            self.reduce_p4 = _make_conv_bn_act(c3, c2, 1, 1)
            self.fuse_p3 = _make_csp_layer(c2 * 2, c2, 1)
            # bottom-up (PAN): down_p3(c2)+reduced_p4(c2) -> c2*2 in;
            # down_n4(c3)+reduced_c5(c3) -> c3*2 in
            self.down_p3 = _make_conv_bn_act(c2, c2, 3, 2)
            self.fuse_n4 = _make_csp_layer(c2 * 2, c3, 1)
            self.down_n4 = _make_conv_bn_act(c3, c3, 3, 2)
            self.fuse_n5 = _make_csp_layer(c3 * 2, c4, 1)
            self.upsample = nn.Upsample(scale_factor=2, mode="nearest")

        def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
            import torch

            x = self.stem(x)
            x = self.stage1(x)
            c3 = self.stage2(x)  # stride 8,  c2 channels
            c4 = self.stage3(c3)  # stride 16, c3 channels
            c5 = self.stage4(c4)  # stride 32, c4 channels

            reduced_c5 = self.reduce_c5(c5)  # c3 channels
            p4 = self.fuse_p4(torch.cat([self.upsample(reduced_c5), c4], dim=1))  # c3 ch
            reduced_p4 = self.reduce_p4(p4)  # c2 channels
            p3 = self.fuse_p3(torch.cat([self.upsample(reduced_p4), c3], dim=1))  # c2 ch

            n3 = p3
            n4 = self.fuse_n4(torch.cat([self.down_p3(n3), reduced_p4], dim=1))  # c3 ch
            n5 = self.fuse_n5(torch.cat([self.down_n4(n4), reduced_c5], dim=1))  # c4 ch
            return n3, n4, n5  # strides 8, 16, 32

    return BackboneNeck()


def _build_head(channels: tuple[int, int, int], num_classes: int, head_width: int) -> Any:
    from torch import nn

    class ScaleHead(nn.Module):
        def __init__(self, in_channels: int) -> None:
            super().__init__()
            self.stem = _make_conv_bn_act(in_channels, head_width, 1, 1)
            self.cls_convs = nn.Sequential(
                _make_conv_bn_act(head_width, head_width, 3, 1),
                _make_conv_bn_act(head_width, head_width, 3, 1),
            )
            self.reg_convs = nn.Sequential(
                _make_conv_bn_act(head_width, head_width, 3, 1),
                _make_conv_bn_act(head_width, head_width, 3, 1),
            )
            self.cls_pred = nn.Conv2d(head_width, num_classes, 1)
            self.reg_pred = nn.Conv2d(head_width, 4, 1)
            self.obj_pred = nn.Conv2d(head_width, 1, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            import torch

            feature = self.stem(x)
            reg_feature = self.reg_convs(feature)
            cls_feature = self.cls_convs(feature)
            return torch.cat(
                [
                    self.reg_pred(reg_feature),
                    self.obj_pred(reg_feature),
                    self.cls_pred(cls_feature),
                ],
                dim=1,
            )

    return nn.ModuleList([ScaleHead(channel) for channel in channels])


def build_network(num_classes: int, width: int = 24, head_width: int = 96) -> Any:
    """The full YOLOX-Tiny module: backbone+neck -> 3 scale heads -> one tensor."""
    from torch import nn

    channels = (width * 4, width * 8, width * 16)  # c2, c3, c4

    class YoloxTiny(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.backbone_neck = _build_backbone_and_neck(width)
            self.heads = _build_head(channels, num_classes, head_width)
            self.num_classes = num_classes

        def forward(self, images: torch.Tensor) -> torch.Tensor:
            import torch

            features = self.backbone_neck(images)
            per_scale = []
            for feature, head in zip(features, self.heads, strict=True):
                raw = head(feature)  # (B, 5+nc, H, W)
                batch, channels_, height, width_ = raw.shape
                flat = raw.permute(0, 2, 3, 1).reshape(batch, height * width_, channels_)
                per_scale.append(flat)
            output = torch.cat(per_scale, dim=1)  # (B, total_anchors, 5+nc)
            if self.training:
                return output
            box = output[..., :4]
            obj_cls = torch.sigmoid(output[..., 4:])
            return torch.cat([box, obj_cls], dim=-1)

    return YoloxTiny()


def build_anchor_grid(input_size: int, strides: tuple[int, ...] = _STRIDES) -> np.ndarray:
    """(total_anchors, 3) rows of (grid_x, grid_y, stride), scale-major order —
    matching the concatenation order ``build_network``'s forward() emits."""
    rows = []
    for stride in strides:
        size = input_size // stride
        ys, xs = np.meshgrid(np.arange(size), np.arange(size), indexing="ij")
        grid = np.stack([xs.ravel(), ys.ravel()], axis=1)
        strides_col = np.full((grid.shape[0], 1), stride)
        rows.append(np.concatenate([grid, strides_col], axis=1))
    return np.concatenate(rows, axis=0).astype(np.float32)


def _pairwise_iou(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """IoU matrix between two sets of (cx, cy, w, h) boxes: (A, B)."""

    def corners(boxes: np.ndarray) -> np.ndarray:
        return np.stack(
            [
                boxes[:, 0] - boxes[:, 2] / 2,
                boxes[:, 1] - boxes[:, 3] / 2,
                boxes[:, 0] + boxes[:, 2] / 2,
                boxes[:, 1] + boxes[:, 3] / 2,
            ],
            axis=1,
        )

    a, b = corners(boxes_a), corners(boxes_b)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    intersection = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - intersection
    return np.where(union > 0, intersection / np.maximum(union, 1e-9), 0.0)


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy score-ordered NMS on (cx, cy, w, h) boxes. Returns kept indices."""
    order = np.argsort(-scores)
    keep: list[int] = []
    while order.size and len(keep) < _MAX_DETECTIONS:
        current = order[0]
        keep.append(int(current))
        if order.size == 1:
            break
        rest = order[1:]
        ious = _pairwise_iou(boxes[current : current + 1], boxes[rest])[0]
        order = rest[ious <= iou_threshold]
    return keep


class YoloxTinyFamily:
    """The production detector family: build, loss, decode, tensor names."""

    name = "yolox-tiny"
    license = "Proprietary-GuardianAI"

    def __init__(self) -> None:
        self._input_size = 640
        self._num_classes = 1
        self._anchor_grid: np.ndarray | None = None

    def build(self, num_classes: int, input_size: int) -> Any:
        self._num_classes = num_classes
        self._input_size = input_size
        self._anchor_grid = build_anchor_grid(input_size)
        return build_network(num_classes)

    # ------------------------------------------------------------- target assignment

    def _assign(self, boxes_px: np.ndarray, anchor_centers: np.ndarray) -> list[np.ndarray]:
        """Per-GT positive anchor indices (center-region + top-k-by-distance)."""
        num_gt = boxes_px.shape[0]
        assignments: list[np.ndarray] = []
        claimed: dict[int, tuple[int, float]] = {}  # anchor idx -> (gt idx, gt area)
        order_by_area = np.argsort(boxes_px[:, 2] * boxes_px[:, 3])  # smallest first, wins ties
        candidate_sets: list[np.ndarray] = [np.array([], dtype=int) for _ in range(num_gt)]

        for gt_index in range(num_gt):
            cx, cy, w, h = boxes_px[gt_index]
            inside = (
                (anchor_centers[:, 0] >= cx - w / 2)
                & (anchor_centers[:, 0] <= cx + w / 2)
                & (anchor_centers[:, 1] >= cy - h / 2)
                & (anchor_centers[:, 1] <= cy + h / 2)
            )
            candidates = np.nonzero(inside)[0]
            if candidates.size == 0:
                distances = np.hypot(anchor_centers[:, 0] - cx, anchor_centers[:, 1] - cy)
                candidates = np.array([int(np.argmin(distances))])
            else:
                distances = np.hypot(
                    anchor_centers[candidates, 0] - cx, anchor_centers[candidates, 1] - cy
                )
                keep = np.argsort(distances)[:_MAX_CANDIDATES_PER_GT]
                candidates = candidates[keep]
            candidate_sets[gt_index] = candidates

        for gt_index in order_by_area:
            area = float(boxes_px[gt_index, 2] * boxes_px[gt_index, 3])
            for anchor_index in candidate_sets[gt_index]:
                previous = claimed.get(int(anchor_index))
                if previous is None or area < previous[1]:
                    claimed[int(anchor_index)] = (int(gt_index), area)

        for gt_index in range(num_gt):
            assignments.append(
                np.array(
                    [anchor for anchor, (owner, _) in claimed.items() if owner == gt_index],
                    dtype=int,
                )
            )
        return assignments

    def loss(self, outputs: Any, targets: list[tuple[Any, Any]]) -> Any:
        import torch
        from torch.nn import functional

        if self._anchor_grid is None:
            raise TrainingConfigurationError("YoloxTinyFamily.build() must run before loss()")
        device = outputs.device
        input_size = self._input_size
        grid_xy = torch.from_numpy(self._anchor_grid[:, :2]).to(device)
        stride = torch.from_numpy(self._anchor_grid[:, 2]).to(device)
        anchor_centers_px = (grid_xy + 0.5) * stride[:, None]

        obj_logits = outputs[..., 4]
        reg_raw = outputs[..., :4]
        cls_logits = outputs[..., 5:]

        obj_targets = torch.zeros_like(obj_logits)
        box_losses = []
        cls_losses = []

        for image_index, (boxes_norm, labels) in enumerate(targets):
            if boxes_norm.shape[0] == 0:
                continue
            boxes_px = (boxes_norm * input_size).detach().cpu().numpy()
            anchor_centers_np = anchor_centers_px.detach().cpu().numpy()
            assignments = self._assign(boxes_px, anchor_centers_np)

            for gt_index, anchor_indices in enumerate(assignments):
                if anchor_indices.size == 0:
                    continue
                anchor_idx_t = torch.from_numpy(anchor_indices).to(device)
                obj_targets[image_index, anchor_idx_t] = 1.0

                gt_box = boxes_norm[gt_index] * input_size
                gx = grid_xy[anchor_idx_t, 0]
                gy = grid_xy[anchor_idx_t, 1]
                s = stride[anchor_idx_t]
                dx, dy, dw, dh = (
                    reg_raw[image_index, anchor_idx_t, 0],
                    reg_raw[image_index, anchor_idx_t, 1],
                    reg_raw[image_index, anchor_idx_t, 2],
                    reg_raw[image_index, anchor_idx_t, 3],
                )
                pred_cx = (gx + dx) * s
                pred_cy = (gy + dy) * s
                pred_w = torch.exp(dw.clamp(max=6.0)) * s
                pred_h = torch.exp(dh.clamp(max=6.0)) * s
                iou = _iou_torch(
                    pred_cx,
                    pred_cy,
                    pred_w,
                    pred_h,
                    gt_box[0],
                    gt_box[1],
                    gt_box[2],
                    gt_box[3],
                )
                box_losses.append(1.0 - iou)

                one_hot = torch.zeros((anchor_idx_t.numel(), self._num_classes), device=device)
                one_hot[:, int(labels[gt_index])] = 1.0
                cls_losses.append(
                    functional.binary_cross_entropy_with_logits(
                        cls_logits[image_index, anchor_idx_t], one_hot, reduction="none"
                    ).mean(dim=1)
                )

        obj_loss = functional.binary_cross_entropy_with_logits(obj_logits, obj_targets)
        if box_losses:
            box_loss = torch.cat(box_losses).mean()
            cls_loss = torch.cat(cls_losses).mean()
        else:
            box_loss = torch.zeros((), device=device)
            cls_loss = torch.zeros((), device=device)
        return obj_loss + _BOX_LOSS_WEIGHT * box_loss + _CLS_LOSS_WEIGHT * cls_loss

    # -------------------------------------------------------------------- decode

    def decode(self, outputs: Any) -> list[Any]:
        """Accepts a torch tensor (training/eval loop) or a numpy array
        (ONNX Runtime output — same decode math, used by the benchmark and
        COCO-baseline comparison paths)."""
        from guardian_ai.training.families import Prediction

        if self._anchor_grid is None:
            raise TrainingConfigurationError("YoloxTinyFamily.build() must run before decode()")
        input_size = self._input_size
        grid_xy = self._anchor_grid[:, :2]
        stride = self._anchor_grid[:, 2]

        raw = outputs.detach().cpu().numpy() if hasattr(outputs, "detach") else np.asarray(outputs)
        predictions = []
        for image in raw:
            centers = (image[:, :2] + grid_xy) * stride[:, None]
            sizes = np.exp(np.clip(image[:, 2:4], None, 6.0)) * stride[:, None]
            objectness = image[:, 4]
            class_scores = image[:, 5:]
            labels = class_scores.argmax(axis=1)
            scores = objectness * class_scores.max(axis=1)
            keep = scores >= _SCORE_FLOOR
            boxes_px = np.concatenate([centers[keep], sizes[keep]], axis=1)
            scores_kept = scores[keep]
            labels_kept = labels[keep]

            kept_indices: list[int] = []
            for label in np.unique(labels_kept):
                mask = labels_kept == label
                if not mask.any():
                    continue
                local = _nms(boxes_px[mask], scores_kept[mask], _NMS_IOU_THRESHOLD)
                kept_indices.extend(np.nonzero(mask)[0][local].tolist())

            if kept_indices:
                boxes_norm = boxes_px[kept_indices] / input_size
                predictions.append(
                    Prediction(
                        boxes=boxes_norm.astype(np.float32),
                        scores=scores_kept[kept_indices].astype(np.float32),
                        labels=labels_kept[kept_indices].astype(np.int64),
                    )
                )
            else:
                predictions.append(
                    Prediction(
                        boxes=np.zeros((0, 4), dtype=np.float32),
                        scores=np.zeros((0,), dtype=np.float32),
                        labels=np.zeros((0,), dtype=np.int64),
                    )
                )
        return predictions

    def input_name(self) -> str:
        return "images"

    def output_name(self) -> str:
        return "output"


def _iou_torch(
    cx1: Any, cy1: Any, w1: Any, h1: Any, cx2: float, cy2: float, w2: float, h2: float
) -> Any:
    """Differentiable IoU between predicted boxes (tensors) and one GT box (scalars)."""
    x1a, y1a = cx1 - w1 / 2, cy1 - h1 / 2
    x2a, y2a = cx1 + w1 / 2, cy1 + h1 / 2
    x1b, y1b = cx2 - w2 / 2, cy2 - h2 / 2
    x2b, y2b = cx2 + w2 / 2, cy2 + h2 / 2
    inter_w = (x2a.clamp(max=x2b) - x1a.clamp(min=x1b)).clamp(min=0)
    inter_h = (y2a.clamp(max=y2b) - y1a.clamp(min=y1b)).clamp(min=0)
    intersection = inter_w * inter_h
    area_a = (w1 * h1).clamp(min=1e-9)
    area_b = w2 * h2
    union = (area_a + area_b - intersection).clamp(min=1e-9)
    return intersection / union
