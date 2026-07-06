"""Official YOLOX integration (Sprint 19.1): variants, targets, wrapper,
checkpoints, and the OfficialYoloxTrainer DetectorFamily — no real network
calls (checkpoint download is monkeypatched to a local fake file)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import torch

from guardian_ai.export.onnx_export import export_onnx
from guardian_ai.training.detectors.yolox import checkpoints
from guardian_ai.training.detectors.yolox.family import OfficialYoloxTrainer
from guardian_ai.training.detectors.yolox.targets import to_yolox_labels
from guardian_ai.training.detectors.yolox.variants import base_in_channels, get_variant, strides
from guardian_ai.training.detectors.yolox.wrapper import OfficialYoloxWrapper
from guardian_ai.training.errors import TrainingConfigurationError
from guardian_ai.training.families import get_family, reserved_families


class TestVariants:
    def test_known_variants_have_expected_depth_width(self) -> None:
        assert get_variant("tiny").depth == pytest.approx(0.33)
        assert get_variant("tiny").width == pytest.approx(0.375)
        assert get_variant("nano").depthwise is True
        assert get_variant("l").depth == pytest.approx(1.0)

    def test_unknown_variant_is_rejected(self) -> None:
        with pytest.raises(TrainingConfigurationError, match="unknown yolox variant"):
            get_variant("xl")

    def test_base_channels_and_strides_are_the_official_constants(self) -> None:
        assert base_in_channels() == (256, 512, 1024)
        assert strides() == (8, 16, 32)


class TestTargets:
    def test_padding_and_pixel_scaling(self) -> None:
        targets = [
            (torch.tensor([[0.5, 0.5, 0.2, 0.3]]), torch.tensor([2])),
            (
                torch.tensor(
                    [[0.1, 0.1, 0.05, 0.05]],
                ),
                torch.tensor([0]),
            ),
        ]
        padded = to_yolox_labels(targets, input_size=640)
        assert padded.shape == (2, 1, 5)
        assert padded[0, 0].tolist() == pytest.approx([2.0, 320.0, 320.0, 128.0, 192.0])
        assert padded[1, 0, 0].item() == 0.0

    def test_uneven_box_counts_are_zero_padded(self) -> None:
        targets = [
            (torch.tensor([[0.5, 0.5, 0.1, 0.1], [0.2, 0.2, 0.1, 0.1]]), torch.tensor([1, 2])),
            (torch.tensor([[0.3, 0.3, 0.1, 0.1]]), torch.tensor([0])),
        ]
        padded = to_yolox_labels(targets, input_size=100)
        assert padded.shape == (2, 2, 5)
        assert torch.all(padded[1, 1] == 0.0)  # padding row is all zeros

    def test_all_empty_batch_keeps_a_real_dimension(self) -> None:
        targets = [
            (torch.zeros((0, 4)), torch.zeros((0,), dtype=torch.long)),
            (torch.zeros((0, 4)), torch.zeros((0,), dtype=torch.long)),
        ]
        padded = to_yolox_labels(targets, input_size=640)
        assert padded.shape == (2, 1, 5)
        assert torch.all(padded == 0.0)


class TestWrapper:
    def _tiny_model(self) -> torch.nn.Module:
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        backbone = YOLOPAFPN(0.33, 0.25, in_channels=[256, 512, 1024])
        head = YOLOXHead(4, 0.25, in_channels=[256, 512, 1024])
        return YOLOX(backbone, head)

    def test_train_mode_returns_eval_style_tensor_and_caches_input(self) -> None:
        wrapper = OfficialYoloxWrapper(self._tiny_model())
        wrapper.train()
        images = torch.rand(1, 3, 64, 64)
        out = wrapper(images)
        assert out.shape[0] == 1
        assert out.shape[-1] == 9  # 4 box + 1 obj + 4 classes
        assert wrapper._cached_images is images
        assert wrapper.yolox_model.training is True  # restored after the throwaway pass

    def test_eval_mode_passes_through_directly(self) -> None:
        wrapper = OfficialYoloxWrapper(self._tiny_model())
        wrapper.eval()
        with torch.no_grad():
            out = wrapper(torch.rand(1, 3, 64, 64))
        assert out.shape[-1] == 9

    def test_compute_loss_without_forward_first_is_refused(self) -> None:
        wrapper = OfficialYoloxWrapper(self._tiny_model())
        with pytest.raises(RuntimeError, match="forward\\(\\) must run before"):
            wrapper.compute_loss(torch.zeros(1, 1, 5))

    def test_compute_loss_uses_cached_images_and_is_differentiable(self) -> None:
        wrapper = OfficialYoloxWrapper(self._tiny_model())
        wrapper.train()
        images = torch.rand(1, 3, 64, 64)
        wrapper(images)
        labels = torch.tensor([[[2.0, 32.0, 32.0, 10.0, 10.0]]])
        loss = wrapper.compute_loss(labels)
        assert loss.requires_grad
        loss.backward()
        assert any(p.grad is not None for p in wrapper.parameters())


class TestCheckpoints:
    def _fake_state_dict_path(self, tmp_path: Path, num_classes: int = 80) -> Path:
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        backbone = YOLOPAFPN(0.33, 0.25, in_channels=[256, 512, 1024])
        head = YOLOXHead(num_classes, 0.25, in_channels=[256, 512, 1024])
        model = YOLOX(backbone, head)
        path = tmp_path / "fake.pth"
        torch.save({"model": model.state_dict()}, path)
        return path

    def test_load_into_matching_classes_loads_everything(self, tmp_path: Path) -> None:
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        checkpoint_path = self._fake_state_dict_path(tmp_path, num_classes=80)
        backbone = YOLOPAFPN(0.33, 0.25, in_channels=[256, 512, 1024])
        head = YOLOXHead(80, 0.25, in_channels=[256, 512, 1024])
        model = YOLOX(backbone, head)
        skipped = checkpoints.load_into(model, checkpoint_path, num_classes=80)
        assert skipped == []

    def test_load_into_different_classes_skips_head_only(self, tmp_path: Path) -> None:
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        checkpoint_path = self._fake_state_dict_path(tmp_path, num_classes=80)
        backbone = YOLOPAFPN(0.33, 0.25, in_channels=[256, 512, 1024])
        head = YOLOXHead(4, 0.25, in_channels=[256, 512, 1024])
        model = YOLOX(backbone, head)
        backbone_before = next(model.backbone.parameters()).clone()
        skipped = checkpoints.load_into(model, checkpoint_path, num_classes=4)
        assert skipped == ["head"]
        # the backbone actually changed (loaded from the checkpoint)
        assert not torch.equal(backbone_before, next(model.backbone.parameters()))

    def test_load_into_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(TrainingConfigurationError, match="not found"):
            checkpoints.load_into(self._fake_state_dict_path(tmp_path), tmp_path / "nope.pth", 80)

    def test_download_pretrained_pins_checksum_on_first_use(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_source = self._fake_state_dict_path(tmp_path, num_classes=80)
        monkeypatch.setattr(checkpoints, "cache_dir", lambda: tmp_path / "cache")

        def fake_download(url: str, destination: str) -> None:
            Path(destination).write_bytes(fake_source.read_bytes())

        monkeypatch.setattr(torch.hub, "download_url_to_file", fake_download)

        variant = get_variant("nano")
        path = checkpoints.download_pretrained(variant)
        assert path.is_file()
        manifest = json.loads((tmp_path / "cache" / checkpoints.MANIFEST_FILE).read_text())
        assert variant.name in manifest

        # second call reuses the cache and re-verifies the same checksum
        path_again = checkpoints.download_pretrained(variant)
        assert path_again == path

    def test_tampered_cache_is_rejected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_source = self._fake_state_dict_path(tmp_path, num_classes=80)
        monkeypatch.setattr(checkpoints, "cache_dir", lambda: tmp_path / "cache")
        monkeypatch.setattr(
            torch.hub,
            "download_url_to_file",
            lambda url, destination: Path(destination).write_bytes(fake_source.read_bytes()),
        )
        variant = get_variant("nano")
        path = checkpoints.download_pretrained(variant)
        path.write_bytes(path.read_bytes() + b"tampered")
        with pytest.raises(TrainingConfigurationError, match="does not match its pinned"):
            checkpoints.download_pretrained(variant)


class TestOfficialYoloxTrainer:
    @pytest.mark.parametrize("variant", ["nano", "tiny", "s"])
    def test_build_forward_loss_backward_decode(self, variant: str) -> None:
        family = OfficialYoloxTrainer(variant)
        model = family.build(num_classes=4, input_size=64, pretrained=False)
        model.train()
        images = torch.rand(2, 3, 64, 64)
        out = model(images)
        targets = [
            (torch.tensor([[0.5, 0.5, 0.2, 0.3]]), torch.tensor([2])),
            (torch.tensor([[0.3, 0.6, 0.15, 0.4]]), torch.tensor([0])),
        ]
        loss = family.loss(out, targets)
        assert torch.isfinite(loss)
        loss.backward()

        model.eval()
        with torch.no_grad():
            out_eval = model(images)
        predictions = family.decode(out_eval)
        assert len(predictions) == 2
        for prediction in predictions:
            assert prediction.boxes.shape[1] == 4 if prediction.boxes.size else True

    def test_loss_before_build_is_refused(self) -> None:
        family = OfficialYoloxTrainer("tiny")
        with pytest.raises(TrainingConfigurationError, match="build"):
            family.loss(torch.zeros(1, 1, 9), [(torch.zeros(0, 4), torch.zeros(0).long())])

    def test_decode_accepts_numpy_and_empty_predictions(self) -> None:
        family = OfficialYoloxTrainer("tiny")
        family.build(num_classes=4, input_size=64, pretrained=False)
        raw = torch.zeros(1, 10, 9).numpy()
        predictions = family.decode(raw)
        assert len(predictions) == 1
        assert predictions[0].boxes.shape == (0, 4)

    def test_input_output_names(self) -> None:
        family = OfficialYoloxTrainer("tiny")
        assert family.input_name() == "images"
        assert family.output_name() == "output"

    def test_custom_checkpoint_overrides_pretrained(self, tmp_path: Path) -> None:
        from yolox.models import YOLOPAFPN, YOLOX, YOLOXHead

        source = YOLOX(
            YOLOPAFPN(0.33, 0.375, in_channels=[256, 512, 1024]),
            YOLOXHead(4, 0.375, in_channels=[256, 512, 1024]),
        )
        checkpoint_path = tmp_path / "custom.pth"
        torch.save({"model": source.state_dict()}, checkpoint_path)

        family = OfficialYoloxTrainer("tiny")
        model = family.build(
            num_classes=4, input_size=64, pretrained=True, checkpoint=checkpoint_path
        )
        assert model is not None  # loaded without hitting the network

    def test_exports_and_validates_onnx(self, tmp_path: Path) -> None:
        family = OfficialYoloxTrainer("nano")
        model = family.build(num_classes=4, input_size=64, pretrained=False)
        destination = tmp_path / "model.onnx"
        sha256 = export_onnx(model, family, 64, destination)
        assert len(sha256) == 64
        assert destination.is_file()


def test_all_five_variants_registered_and_none_reserved() -> None:
    for variant in ("nano", "tiny", "s", "m", "l"):
        name = f"yolox-{variant}"
        assert name not in reserved_families()
        assert get_family(name).license == "Apache-2.0"
