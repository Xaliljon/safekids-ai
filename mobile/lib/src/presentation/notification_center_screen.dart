import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:guardian_core/guardian_core.dart';

import '../application/connection_controller.dart';
import '../application/notification_repository.dart';
import '../app.dart';
import '../providers.dart';

/// The notification center: newest first, unread bold, severity color-coded.
class NotificationCenterScreen extends ConsumerWidget {
  const NotificationCenterScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repository = ref.watch(notificationRepositoryProvider);
    final controller = ref.watch(connectionControllerProvider);
    final items = repository.items;
    return Scaffold(
      appBar: AppBar(
        title: Text(controller.box?.boxName ?? 'Guardian SafeKids'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(child: _ConnectionChip(state: controller.state)),
          ),
        ],
      ),
      body: Column(
        children: [
          if (controller.state == BoxConnectionState.offline)
            Container(
              key: const Key('offline-banner'),
              width: double.infinity,
              color: Colors.amber.shade200,
              padding: const EdgeInsets.all(8),
              child: const Text(
                'Offline — showing cached notifications, reconnecting…',
                textAlign: TextAlign.center,
              ),
            ),
          Expanded(
            child: items.isEmpty
                ? const Center(
                    key: Key('empty-state'),
                    child: Text('No notifications — all quiet.'),
                  )
                : ListView.builder(
                    key: const Key('notification-list'),
                    itemCount: items.length,
                    itemBuilder: (context, index) =>
                        _NotificationTile(item: items[index]),
                  ),
          ),
        ],
      ),
    );
  }
}

class _ConnectionChip extends StatelessWidget {
  const _ConnectionChip({required this.state});

  final BoxConnectionState state;

  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (state) {
      BoxConnectionState.connected => ('Connected', Colors.green),
      BoxConnectionState.connecting => ('Connecting…', Colors.orange),
      BoxConnectionState.offline => ('Offline', Colors.red),
      BoxConnectionState.unpaired => ('Not paired', Colors.grey),
    };
    return Chip(
      key: const Key('connection-chip'),
      label: Text(label, style: const TextStyle(fontSize: 12)),
      backgroundColor: color.withValues(alpha: 0.15),
      side: BorderSide(color: color),
    );
  }
}

class _NotificationTile extends ConsumerWidget {
  const _NotificationTile({required this.item});

  final NotificationItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final message = item.message;
    final color = severityColor(message.severity.wire);
    final weight = item.read ? FontWeight.normal : FontWeight.bold;
    final local = message.timestamp.toLocal();
    final time =
        '${local.hour.toString().padLeft(2, '0')}:${local.minute.toString().padLeft(2, '0')}:${local.second.toString().padLeft(2, '0')}';
    return ListTile(
      key: Key('notification-${message.notificationId}'),
      leading: CircleAvatar(
        backgroundColor: color,
        radius: 10,
        child: item.read
            ? null
            : const Icon(Icons.circle, size: 8, color: Colors.white),
      ),
      title: Text(
        'POTENTIAL FALL — ${message.severity.wire.toUpperCase()} '
        '${(message.confidence * 100).round()}%',
        style: TextStyle(fontWeight: weight),
      ),
      subtitle: Text(
        '${message.cameraId} · $time · ${_statusLabel(message.incidentStatus)}',
        style: TextStyle(fontWeight: weight),
      ),
      trailing: item.read
          ? null
          : Icon(Icons.brightness_1,
              size: 10, color: color, key: const Key('unread-dot')),
      onTap: () {
        ref
            .read(notificationRepositoryProvider)
            .markRead(message.notificationId);
        context.go('/incident/${message.notificationId}');
      },
    );
  }
}

String _statusLabel(IncidentStatus status) => switch (status) {
      IncidentStatus.pendingReview => 'PENDING REVIEW',
      IncidentStatus.confirmed => 'CONFIRMED',
      IncidentStatus.dismissed => 'DISMISSED',
    };
