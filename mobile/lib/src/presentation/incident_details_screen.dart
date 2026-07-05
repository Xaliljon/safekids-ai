import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:guardian_core/guardian_core.dart';

import '../app.dart';
import '../providers.dart';

/// Incident review: everything the AI concluded, and the human's decision.
/// Details come live from the box when the incident is still open; the
/// cached notification carries the essentials otherwise. No images.
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

  @override
  void initState() {
    super.initState();
    _load();
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
    final message = ref
        .read(notificationRepositoryProvider)
        .byNotificationId(widget.notificationId);
    if (message == null) {
      return;
    }
    setState(() {
      _acting = true;
      _actionError = null;
    });
    final error = await ref
        .read(connectionControllerProvider)
        .resolve(message.incidentId, confirm: confirm);
    if (!mounted) {
      return;
    }
    setState(() {
      _acting = false;
      _actionError = error;
    });
    if (error == null) {
      context.go('/');
    }
  }

  @override
  Widget build(BuildContext context) {
    final message = ref
        .watch(notificationRepositoryProvider)
        .byNotificationId(widget.notificationId);
    if (message == null) {
      return const Scaffold(
          body: Center(child: Text('Notification not found')));
    }
    final pending = message.incidentStatus == IncidentStatus.pendingReview;
    final color = severityColor(message.severity.wire);
    return Scaffold(
      appBar: AppBar(title: const Text('Incident review')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            color: color.withValues(alpha: 0.12),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'POTENTIAL FALL — ${message.severity.wire.toUpperCase()}',
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
          const SizedBox(height: 12),
          _field('Incident ID', message.incidentId),
          _field('Severity', message.severity.wire.toUpperCase()),
          _field('Time', message.timestamp.toLocal().toString()),
          _field('Confidence', '${(message.confidence * 100).round()}%'),
          _field('Camera', message.cameraId),
          _field('Track', '#${message.trackDisplayId} (${message.trackId})'),
          _field('Status', message.incidentStatus.wire),
          const SizedBox(height: 16),
          Text('Timeline', style: Theme.of(context).textTheme.titleMedium),
          if (_loading)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_details == null)
            const Padding(
              key: Key('timeline-unavailable'),
              padding: EdgeInsets.symmetric(vertical: 8),
              child: Text(
                  'Timeline unavailable (incident no longer open on the box).'),
            )
          else
            for (final event in _details!.events)
              ListTile(
                key: Key('timeline-${event.observedAt.toIso8601String()}'),
                dense: true,
                leading: const Icon(Icons.timeline),
                title: Text(
                  '${event.observedAt.toLocal()} — candidate '
                  '${(event.confidence * 100).round()}%',
                ),
                subtitle: Text(
                  event.signals
                      .map((signal) => '${signal.name}: ${signal.detail}')
                      .join('\n'),
                ),
              ),
          const SizedBox(height: 24),
          if (pending)
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    key: const Key('confirm-button'),
                    onPressed: _acting ? null : () => _resolve(confirm: true),
                    icon: const Icon(Icons.check),
                    label: const Text('Confirm incident'),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: OutlinedButton.icon(
                    key: const Key('dismiss-button'),
                    onPressed: _acting ? null : () => _resolve(confirm: false),
                    icon: const Icon(Icons.close),
                    label: const Text('Dismiss'),
                  ),
                ),
              ],
            )
          else
            Text(
              'Reviewed — ${message.incidentStatus.wire}',
              key: const Key('reviewed-label'),
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium,
            ),
          if (_actionError != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                _actionError!,
                key: const Key('action-error'),
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
        ],
      ),
    );
  }

  Widget _field(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
                width: 110,
                child: Text(label, style: const TextStyle(color: Colors.grey))),
            Expanded(child: Text(value)),
          ],
        ),
      );
}
