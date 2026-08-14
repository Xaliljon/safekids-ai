import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:guardian_core/guardian_core.dart';

import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';
import 'widgets.dart';

/// Per-camera status from the box's health surface: state, FPS, pipeline
/// counters, and a capability-gated restart action. On boxes without
/// remote restart the action explains that auto-recovery already handles
/// crashed cameras (honest UI beats a dead button).
class CamerasScreen extends ConsumerWidget {
  const CamerasScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final status = ref.watch(statusControllerProvider);
    final health = status.health;
    final cameras = health?.cameras ?? const <CameraHealth>[];
    final metrics = status.metrics;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.camerasTitle)),
      body: RefreshIndicator(
        onRefresh: () => ref.read(statusControllerProvider).refresh(),
        child: cameras.isEmpty
            ? ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  if (!status.live && health != null)
                    OfflineBanner(text: l10n.boxUnreachable),
                  Padding(
                    padding: const EdgeInsets.all(32),
                    child: Center(
                      child: Text(
                        health == null ? l10n.noHealthYet : l10n.camerasEmpty,
                        key: const Key('cameras-empty'),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ],
              )
            : ListView(
                key: const Key('cameras-list'),
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  if (!status.live) OfflineBanner(text: l10n.boxUnreachable),
                  for (final camera in cameras)
                    _CameraCard(
                      camera: camera,
                      trackingLatencyMs: metrics?.trackingLatencyMs,
                    ),
                  const SizedBox(height: 24),
                ],
              ),
      ),
    );
  }
}

class _CameraCard extends ConsumerWidget {
  const _CameraCard({required this.camera, required this.trackingLatencyMs});

  final CameraHealth camera;
  final double? trackingLatencyMs;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final color = cameraStatusColor(context, camera.status);
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: ExpansionTile(
        key: Key('camera-${camera.cameraId}'),
        leading: StatusDot(color: color, size: 14),
        title: Text(
          camera.cameraId,
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        subtitle: Text(
          '${cameraStatusLabel(l10n, camera.status)}'
          '${camera.fps != null ? ' · ${camera.fps!.toStringAsFixed(1)} ${l10n.fpsLabel}' : ''}',
          style: TextStyle(color: color),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        children: [
          _row(l10n.fpsLabel,
              camera.fps == null ? '—' : camera.fps!.toStringAsFixed(1)),
          _row(
            l10n.latencyLabel,
            trackingLatencyMs == null
                ? '—'
                : '${trackingLatencyMs!.toStringAsFixed(1)} ms',
          ),
          _row(l10n.framesProcessed, '${camera.framesProcessed ?? '—'}'),
          _row(l10n.framesDropped, '${camera.framesDropped ?? '—'}'),
          _row(l10n.detectorErrors, '${camera.detectorErrors ?? '—'}'),
          _row(l10n.trackerErrors, '${camera.trackerErrors ?? '—'}'),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              key: Key('restart-${camera.cameraId}'),
              icon: const Icon(Icons.restart_alt),
              label: Text(l10n.restartCamera),
              onPressed: () => _restart(context, ref, l10n),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _restart(
      BuildContext context, WidgetRef ref, AppLocalizations l10n) async {
    final box = ref.read(connectionControllerProvider).box;
    if (box == null) {
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    final result = await ref
        .read(statusControllerProvider)
        .restartCamera(box, camera.cameraId);
    final text = switch (result) {
      null => l10n.restartRequested,
      'unsupported' => l10n.restartUnsupported,
      _ => l10n.restartFailed,
    };
    messenger.showSnackBar(SnackBar(
      key: const Key('restart-result'),
      content: Text(text),
      duration: const Duration(seconds: 5),
    ));
  }

  Widget _row(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: const TextStyle(color: Colors.grey)),
            Text(value, style: const TextStyle(fontWeight: FontWeight.w500)),
          ],
        ),
      );
}
