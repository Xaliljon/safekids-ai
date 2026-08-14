import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:guardian_core/guardian_core.dart';

import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'evidence_section.dart';
import 'format.dart';
import 'widgets.dart';

/// Incident review: everything the AI concluded, and the human's decision.
/// Details come live from the box when the incident is still open; the
/// cached notification carries the essentials otherwise. Evidence is
/// metadata only — no images, no video, no identities (docs/04).
class IncidentDetailsScreen extends ConsumerStatefulWidget {
  const IncidentDetailsScreen({required this.notificationId, super.key});

  final String notificationId;

  @override
  ConsumerState<IncidentDetailsScreen> createState() =>
      _IncidentDetailsScreenState();
}

class _IncidentDetailsScreenState extends ConsumerState<IncidentDetailsScreen> {
  IncidentDetails? _details;
  bool _loading = true;
  String? _actionError;
  bool _acting = false;
  final _note = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final message = ref
        .read(notificationRepositoryProvider)
        .byNotificationId(widget.notificationId);
    if (message != null) {
      final details = await ref
          .read(connectionControllerProvider)
          .fetchIncident(message.incidentId);
      if (mounted) {
        setState(() {
          _details = details;
          _loading = false;
        });
      }
    } else if (mounted) {
      setState(() => _loading = false);
    }
  }

  Future<void> _resolve({required bool confirm}) async {
    final l10n = AppLocalizations.of(context);
    final message = ref
        .read(notificationRepositoryProvider)
        .byNotificationId(widget.notificationId);
    if (message == null) {
      return;
    }
    final question = confirm ? l10n.confirmQuestion : l10n.dismissQuestion;
    final sure = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(question),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.cancel),
          ),
          FilledButton(
            key: const Key('confirm-dialog-yes'),
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(confirm ? l10n.confirmAction : l10n.dismissAction),
          ),
        ],
      ),
    );
    if (sure != true || !mounted) {
      return;
    }
    setState(() {
      _acting = true;
      _actionError = null;
    });
    final error = await ref
        .read(connectionControllerProvider)
        .resolve(message.incidentId, confirm: confirm, note: _note.text);
    if (!mounted) {
      return;
    }
    setState(() {
      _acting = false;
      _actionError = error == null ? null : l10n.decisionFailed;
    });
    if (error == null) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(l10n.decisionRecorded)));
      context.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final repository = ref.watch(notificationRepositoryProvider);
    final message = repository.byNotificationId(widget.notificationId);
    if (message == null) {
      return Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(l10n.alertsEmpty)),
      );
    }
    final related = repository.byIncidentId(message.incidentId);
    final pending = message.incidentStatus == IncidentStatus.pendingReview;
    final color = severityColor(context, message.severity);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.incidentTitle)),
      body: ListView(
        key: const Key('incident-list'),
        children: [
          // ---------------------------------------------------- header
          Card(
            margin: const EdgeInsets.all(16),
            color: color.withValues(alpha: 0.12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${incidentTypeLabel(l10n, message.incidentType)} — '
                    '${severityLabel(l10n, message.severity).toUpperCase()}',
                    style: Theme.of(context)
                        .textTheme
                        .titleLarge
                        ?.copyWith(color: color, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 8),
                  Text(message.summary, key: const Key('summary')),
                ],
              ),
            ),
          ),
          // ------------------------------------------ video (evidence)
          SectionHeader(l10n.evidenceVideoSection),
          EvidenceSection(incidentId: message.incidentId),
          // ------------------------------------------------ AI signals
          if (_details != null && _aggregateSignals(_details!).isNotEmpty) ...[
            SectionHeader(l10n.aiSignalsSection),
            PanelCard(
              child: Column(
                key: const Key('ai-signals'),
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final signal in _aggregateSignals(_details!))
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 4),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(signal.$1),
                              Text('${(signal.$2 * 100).round()}%',
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w600)),
                            ],
                          ),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(3),
                            child: LinearProgressIndicator(
                              value: signal.$2.clamp(0.0, 1.0),
                              minHeight: 5,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ],
          // -------------------------------------------- details (facts)
          SectionHeader(l10n.incidentEvidence),
          PanelCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _field(l10n.cameraLabel, message.cameraId),
                _field(
                    l10n.trackNumber(message.trackDisplayId), message.trackId),
                _field(l10n.confidenceLabel,
                    '${(message.confidence * 100).round()}%'),
                if (_details != null) ...[
                  _field(l10n.riskConfidenceLabel,
                      '${(_details!.riskConfidence * 100).round()}%'),
                  _field(l10n.openedAtLabel,
                      '${formatDate(_details!.openedAt)} ${formatTime(_details!.openedAt)}'),
                  _field(l10n.lastEventLabel,
                      '${formatDate(_details!.lastEventAt)} ${formatTime(_details!.lastEventAt)}'),
                ],
                _field(l10n.eventsCount(message.eventCount), ''),
                const SizedBox(height: 8),
                Text(
                  l10n.evidenceMetadataOnly,
                  key: const Key('evidence-note'),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: Theme.of(context).colorScheme.outline),
                ),
              ],
            ),
          ),
          // -------------------------------------------------- timeline
          SectionHeader(l10n.incidentTimeline),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_details == null)
            PanelCard(
              child: Text(
                l10n.incidentUnavailableOffline,
                key: const Key('timeline-unavailable'),
              ),
            )
          else
            PanelCard(
              child: Column(
                children: [
                  for (var i = 0; i < _details!.events.length; i++)
                    _TimelineEvent(
                      event: _details!.events[i],
                      isFirst: i == 0,
                      isLast: i == _details!.events.length - 1,
                    ),
                ],
              ),
            ),
          // -------------------------------------- review + decision
          SectionHeader(l10n.incidentReviewStatus),
          PanelCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Chip(
                      key: const Key('review-status-chip'),
                      label: Text(
                        incidentStatusLabel(l10n, message.incidentStatus),
                      ),
                      backgroundColor: pending
                          ? Colors.orange.withValues(alpha: 0.2)
                          : message.incidentStatus == IncidentStatus.confirmed
                              ? Colors.red.withValues(alpha: 0.15)
                              : Colors.blueGrey.withValues(alpha: 0.15),
                    ),
                    const Spacer(),
                    if (_details?.reviewer != null)
                      Text('${l10n.reviewerLabel}: ${_details!.reviewer}'),
                  ],
                ),
                if (pending) ...[
                  const SizedBox(height: 12),
                  TextField(
                    key: const Key('review-note'),
                    controller: _note,
                    decoration: InputDecoration(
                      labelText: l10n.reviewNoteHint,
                      border: const OutlineInputBorder(),
                      isDense: true,
                    ),
                  ),
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.icon(
                          key: const Key('confirm-button'),
                          onPressed:
                              _acting ? null : () => _resolve(confirm: true),
                          icon: const Icon(Icons.check),
                          label: Text(l10n.confirmAction),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: OutlinedButton.icon(
                          key: const Key('dismiss-button'),
                          onPressed:
                              _acting ? null : () => _resolve(confirm: false),
                          icon: const Icon(Icons.close),
                          label: Text(l10n.dismissAction),
                        ),
                      ),
                    ],
                  ),
                ],
                if (_actionError != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      _actionError!,
                      key: const Key('action-error'),
                      style:
                          TextStyle(color: Theme.of(context).colorScheme.error),
                    ),
                  ),
              ],
            ),
          ),
          // ---------------------------------------------- track history
          SectionHeader(l10n.incidentTrackHistory),
          PanelCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.trackNumber(message.trackDisplayId),
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Text(
                  l10n.notificationsOfIncident,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                for (final notification in related)
                  ListTile(
                    key: Key('history-${notification.notificationId}'),
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: StatusDot(
                      color: severityColor(context, notification.severity),
                    ),
                    title: Text(
                      '${formatTime(notification.timestamp)} — '
                      '${severityLabel(l10n, notification.severity)} '
                      '${(notification.confidence * 100).round()}%',
                    ),
                    subtitle: Text(
                        incidentStatusLabel(l10n, notification.incidentStatus)),
                  ),
              ],
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  /// Strongest score per signal name across the whole timeline — "why the
  /// AI raised this", at a glance (EVIDENCE_UX.md).
  static List<(String, double)> _aggregateSignals(IncidentDetails details) {
    final best = <String, double>{};
    for (final event in details.events) {
      for (final signal in event.signals) {
        final current = best[signal.name] ?? 0;
        if (signal.score > current) {
          best[signal.name] = signal.score;
        }
      }
    }
    final entries = best.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    return [for (final entry in entries) (entry.key, entry.value)];
  }

  Widget _field(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              flex: 2,
              child: Text(label, style: const TextStyle(color: Colors.grey)),
            ),
            Expanded(flex: 3, child: Text(value)),
          ],
        ),
      );
}

/// One timeline entry with a connector line and per-signal score bars.
class _TimelineEvent extends StatelessWidget {
  const _TimelineEvent({
    required this.event,
    required this.isFirst,
    required this.isLast,
  });

  final IncidentEvent event;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 24,
            child: Column(
              children: [
                Expanded(
                  child: Container(
                    width: 2,
                    color: isFirst ? Colors.transparent : scheme.outlineVariant,
                  ),
                ),
                Icon(Icons.circle, size: 10, color: scheme.primary),
                Expanded(
                  child: Container(
                    width: 2,
                    color: isLast ? Colors.transparent : scheme.outlineVariant,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '${formatTime(event.observedAt)} · '
                    '${(event.confidence * 100).round()}%',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  for (final signal in event.signals)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Text(signal.name,
                                  style: Theme.of(context).textTheme.bodySmall),
                              Text(
                                signal.detail,
                                style: Theme.of(context)
                                    .textTheme
                                    .bodySmall
                                    ?.copyWith(color: scheme.outline),
                              ),
                            ],
                          ),
                          ClipRRect(
                            borderRadius: BorderRadius.circular(2),
                            child: LinearProgressIndicator(
                              value: signal.score.clamp(0.0, 1.0),
                              minHeight: 4,
                              backgroundColor: scheme.surfaceContainerHighest,
                            ),
                          ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
