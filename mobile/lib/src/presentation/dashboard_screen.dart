import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:guardian_core/guardian_core.dart';

import '../application/connection_controller.dart';
import '../application/notification_repository.dart';
import '../application/status_controller.dart';
import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';
import 'widgets.dart';

/// The director's first glance: is everything fine, and if not — what.
class DashboardScreen extends ConsumerWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final connection = ref.watch(connectionControllerProvider);
    final status = ref.watch(statusControllerProvider);
    final repository = ref.watch(notificationRepositoryProvider);
    final health = status.health;
    final recent = repository
        .page(const AlertFilter(tab: AlertsTab.unread), limit: 3)
        .followedBy(
            repository.page(const AlertFilter(tab: AlertsTab.read), limit: 3))
        .take(3)
        .toList();

    return Scaffold(
      appBar: AppBar(
        title: Text(connection.box?.boxName ?? l10n.appTitle),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: Center(child: ConnectionChip(state: connection.state)),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref.read(statusControllerProvider).refresh(),
        child: ListView(
          key: const Key('dashboard-list'),
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            if (connection.state == BoxConnectionState.offline)
              const OfflineBanner(),
            SectionHeader(l10n.dashSystemStatus),
            _SystemStatusCard(status: status, l10n: l10n),
            SectionHeader(l10n.dashConnectedCameras,
                trailing: TextButton(
                  onPressed: () => context.go('/cameras'),
                  child: Text(l10n.dashViewAll),
                )),
            _CamerasCard(health: health, l10n: l10n),
            SectionHeader(l10n.dashRecentIncidents,
                trailing: TextButton(
                  key: const Key('view-all-alerts'),
                  onPressed: () => context.go('/alerts'),
                  child: Text(l10n.dashViewAll),
                )),
            if (recent.isEmpty)
              PanelCard(
                child: Text(l10n.dashNoIncidents,
                    key: const Key('dashboard-no-incidents')),
              )
            else
              for (final item in recent) _RecentIncidentTile(item: item),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }
}

class _SystemStatusCard extends StatelessWidget {
  const _SystemStatusCard({required this.status, required this.l10n});

  final StatusController status;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final health = status.health;
    final metrics = status.metrics;
    final boxStatus = health?.status ?? BoxStatus.unknown;
    final color = boxStatusColor(boxStatus, scheme);
    final age = status.snapshotAge();
    final host = metrics?.host ?? health?.host;

    return PanelCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              StatusDot(color: color, size: 14),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  boxStatusLabel(l10n, boxStatus),
                  key: const Key('system-status'),
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              if (health != null && health.version.isNotEmpty)
                Text(
                  l10n.boxVersion(health.version),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: scheme.outline),
                ),
            ],
          ),
          if (health != null && health.warnings.isNotEmpty) ...[
            const SizedBox(height: 8),
            for (final warning in health.warnings.entries)
              Text(
                '! ${warning.key}: ${warning.value}',
                style: TextStyle(color: Colors.orange.shade800, fontSize: 13),
              ),
          ],
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(
                child: MetricGauge(
                  label: l10n.dashCpu,
                  percent: host?.cpuPercent,
                ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: MetricGauge(
                  label: l10n.dashRam,
                  percent: host?.memoryPercent,
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                '${l10n.dashLastSync}: ${agoLabel(l10n, age)}',
                key: const Key('last-sync'),
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: scheme.outline),
              ),
              if (!status.live)
                Text(
                  l10n.connOffline,
                  style: TextStyle(color: scheme.error, fontSize: 12),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CamerasCard extends StatelessWidget {
  const _CamerasCard({required this.health, required this.l10n});

  final BoxHealth? health;
  final AppLocalizations l10n;

  @override
  Widget build(BuildContext context) {
    final cameras = health?.cameras ?? const <CameraHealth>[];
    final online = cameras.where((camera) => camera.isHealthy).length;
    return PanelCard(
      child: cameras.isEmpty
          ? Text(l10n.camerasEmpty)
          : Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  l10n.dashCamerasOnline(online, cameras.length),
                  key: const Key('cameras-online'),
                  style: Theme.of(context)
                      .textTheme
                      .titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                for (final camera in cameras)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        StatusDot(color: cameraStatusColor(camera.status)),
                        const SizedBox(width: 8),
                        Expanded(child: Text(camera.cameraId)),
                        Text(
                          camera.fps == null
                              ? '—'
                              : '${camera.fps!.toStringAsFixed(1)} ${l10n.fpsLabel}',
                          style: Theme.of(context).textTheme.bodySmall,
                        ),
                      ],
                    ),
                  ),
              ],
            ),
    );
  }
}

class _RecentIncidentTile extends ConsumerWidget {
  const _RecentIncidentTile({required this.item});

  final NotificationItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final message = item.message;
    final color = severityColor(message.severity);
    return PanelCard(
      onTap: () {
        ref
            .read(notificationRepositoryProvider)
            .markRead(message.notificationId);
        context.push('/incident/${message.notificationId}');
      },
      child: Row(
        children: [
          StatusDot(color: color, size: 12),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '${l10n.potentialFall} — '
                  '${severityLabel(l10n, message.severity)}',
                  style: TextStyle(
                    fontWeight: item.read ? FontWeight.normal : FontWeight.bold,
                  ),
                ),
                Text(
                  '${message.cameraId} · ${formatTime(message.timestamp)} · '
                  '${incidentStatusLabel(l10n, message.incidentStatus)}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right),
        ],
      ),
    );
  }
}
