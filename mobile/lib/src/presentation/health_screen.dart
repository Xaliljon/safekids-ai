import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';
import 'widgets.dart';

/// Full system health: every subsystem's status plus host metrics
/// (CPU/RAM/temperature/disk) and the network picture. Renders the last
/// cached snapshot when the box is unreachable, with its age visible.
class HealthScreen extends ConsumerWidget {
  const HealthScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final status = ref.watch(statusControllerProvider);
    final connection = ref.watch(connectionControllerProvider);
    final health = status.health;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.healthTitle)),
      body: RefreshIndicator(
        onRefresh: () => ref.read(statusControllerProvider).refresh(),
        child: health == null
            ? ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  Padding(
                    padding: const EdgeInsets.all(32),
                    child: Center(
                      child: Text(
                        l10n.noHealthYet,
                        key: const Key('health-empty'),
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                ],
              )
            : ListView(
                key: const Key('health-list'),
                physics: const AlwaysScrollableScrollPhysics(),
                children: [
                  if (!status.live) OfflineBanner(text: l10n.boxUnreachable),
                  // ------------------------------------------ subsystems
                  SectionHeader(l10n.subsystemsSection),
                  PanelCard(
                    child: Column(
                      children: [
                        for (final subsystem in health.subsystems)
                          Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Row(
                              children: [
                                StatusDot(
                                  color: boxStatusColor(
                                    subsystem.status,
                                    Theme.of(context).colorScheme,
                                  ),
                                ),
                                const SizedBox(width: 10),
                                Expanded(
                                  child: Text(
                                    subsystem.name,
                                    key: Key('subsystem-${subsystem.name}'),
                                  ),
                                ),
                                Text(
                                  boxStatusLabel(l10n, subsystem.status),
                                  style: Theme.of(context).textTheme.bodySmall,
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                  if (health.warnings.isNotEmpty) ...[
                    SectionHeader(l10n.warningsSection),
                    PanelCard(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          for (final warning in health.warnings.entries)
                            Padding(
                              padding: const EdgeInsets.symmetric(vertical: 2),
                              child: Text(
                                '! ${warning.key}: ${warning.value}',
                                style: TextStyle(
                                    color: Colors.orange.shade800,
                                    fontSize: 13),
                              ),
                            ),
                        ],
                      ),
                    ),
                  ],
                  // ------------------------------------------------ host
                  SectionHeader(l10n.hostSection),
                  PanelCard(
                    child: Column(
                      children: [
                        MetricGauge(
                          label: l10n.cpuLabel,
                          percent: health.host.cpuPercent,
                        ),
                        const SizedBox(height: 12),
                        MetricGauge(
                          label: l10n.ramLabel,
                          percent: health.host.memoryPercent,
                          detail: health.host.memoryUsedMb == null
                              ? null
                              : '${health.host.memoryUsedMb} MB',
                        ),
                        const SizedBox(height: 12),
                        MetricGauge(
                          label: l10n.diskLabel,
                          percent: health.host.diskPercent,
                          detail: health.host.diskFreeGb == null
                              ? null
                              : l10n.diskFreeGb(
                                  health.host.diskFreeGb!.toStringAsFixed(1)),
                        ),
                        const SizedBox(height: 12),
                        KeyValueRow(
                          l10n.temperatureLabel,
                          health.host.temperatureC == null
                              ? l10n.notAvailable
                              : '${health.host.temperatureC!.toStringAsFixed(1)}°C',
                          valueKey: const Key('temperature'),
                        ),
                        KeyValueRow(
                          l10n.uptimeLabel,
                          formatUptime(health.host.uptimeSeconds),
                        ),
                      ],
                    ),
                  ),
                  // --------------------------------------------- network
                  SectionHeader(l10n.networkSection),
                  PanelCard(
                    child: Column(
                      children: [
                        KeyValueRow(
                          l10n.boxAddressLabel,
                          connection.box?.host ?? '—',
                          valueKey: const Key('box-address'),
                        ),
                        KeyValueRow(
                          l10n.dashLastSync,
                          agoLabel(l10n, status.snapshotAge()),
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            Expanded(child: Text(l10n.appTitle)),
                            ConnectionChip(state: connection.state),
                          ],
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),
                ],
              ),
      ),
    );
  }
}
