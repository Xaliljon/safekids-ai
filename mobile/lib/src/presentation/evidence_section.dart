import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/generated/app_localizations.dart';
import '../application/evidence_controller.dart';
import '../providers.dart';
import 'evidence_player.dart';
import 'format.dart';
import 'widgets.dart';

/// The video block of the incident review (EVIDENCE_UX.md): thumbnail,
/// download with progress, playback, and the Original / AI-analysis switch.
class EvidenceSection extends ConsumerWidget {
  const EvidenceSection({super.key, required this.incidentId});

  final String incidentId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final controller = ref.watch(evidenceControllerProvider(incidentId));
    final playerBuilder = ref.watch(evidencePlayerBuilderProvider);
    final record = controller.record;

    return PanelCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          switch (controller.state) {
            EvidencePlaybackState.loading => const Padding(
                key: Key('evidence-loading'),
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
            EvidencePlaybackState.none => Text(
                l10n.evidenceNone,
                key: const Key('evidence-none'),
              ),
            EvidencePlaybackState.preparing => Row(
                key: const Key('evidence-preparing'),
                children: [
                  const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  const SizedBox(width: 12),
                  Expanded(child: Text(l10n.evidencePreparing)),
                ],
              ),
            EvidencePlaybackState.failed => Text(
                l10n.evidenceFailed,
                key: const Key('evidence-failed'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            EvidencePlaybackState.available => _Poster(
                key: const Key('evidence-available'),
                controller: controller,
                child: FilledButton.icon(
                  key: const Key('evidence-download'),
                  onPressed: () => ref
                      .read(evidenceControllerProvider(incidentId))
                      .download(),
                  icon: const Icon(Icons.download),
                  label: Text(l10n.evidenceDownload),
                ),
              ),
            EvidencePlaybackState.downloading => _Poster(
                key: const Key('evidence-downloading'),
                controller: controller,
                child: Column(
                  children: [
                    LinearProgressIndicator(
                      key: const Key('evidence-progress'),
                      value:
                          controller.progress > 0 ? controller.progress : null,
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '${l10n.evidenceDownloading} '
                      '${(controller.progress * 100).round()}%',
                    ),
                  ],
                ),
              ),
            EvidencePlaybackState.cached => Column(
                key: const Key('evidence-player'),
                children: [
                  playerBuilder(
                    controller.videoPath!,
                    Key('evidence-video-${controller.variant}'),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    l10n.evidenceOfflineNote,
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: Theme.of(context).colorScheme.outline),
                  ),
                ],
              ),
          },
          if (controller.canSwitchVariant) ...[
            const SizedBox(height: 12),
            SegmentedButton<String>(
              key: const Key('evidence-variant'),
              segments: [
                ButtonSegment(
                  value: 'original',
                  icon: const Icon(Icons.videocam_outlined, size: 18),
                  label: Text(l10n.evidenceOriginal),
                ),
                ButtonSegment(
                  value: 'overlay',
                  icon: const Icon(Icons.auto_awesome, size: 18),
                  label: Text(l10n.evidenceAiView),
                ),
              ],
              selected: {controller.variant},
              onSelectionChanged: (selection) => ref
                  .read(evidenceControllerProvider(incidentId))
                  .switchVariant(selection.first),
            ),
          ],
          if (record != null && record.durationSeconds != null) ...[
            const SizedBox(height: 8),
            Text(
              '${record.durationSeconds!.toStringAsFixed(0)} s · '
              '${formatDate(record.createdAt)} ${formatTime(record.createdAt)}'
              '${record.sizeBytes != null ? ' · ${(record.sizeBytes! / (1024 * 1024)).toStringAsFixed(1)} MB' : ''}',
              key: const Key('evidence-facts'),
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ],
        ],
      ),
    );
  }
}

class _Poster extends StatelessWidget {
  const _Poster({super.key, required this.controller, required this.child});

  final EvidenceController controller;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (controller.thumbnail != null)
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: Image.memory(
              controller.thumbnail!,
              key: const Key('evidence-thumbnail'),
              fit: BoxFit.cover,
              width: double.infinity,
            ),
          ),
        const SizedBox(height: 12),
        child,
      ],
    );
  }
}
