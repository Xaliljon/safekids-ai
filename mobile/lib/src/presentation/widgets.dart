import 'package:flutter/material.dart';

import '../application/connection_controller.dart';
import '../../l10n/generated/app_localizations.dart';

class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 20, 16, 8),
      child: Row(
        children: [
          Expanded(
            child: Text(
              title.toUpperCase(),
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                    color: Theme.of(context).colorScheme.outline,
                    letterSpacing: 1.1,
                  ),
            ),
          ),
          if (trailing != null) trailing!,
        ],
      ),
    );
  }
}

class StatusDot extends StatelessWidget {
  const StatusDot({super.key, required this.color, this.size = 10});

  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }
}

/// A labeled percentage gauge (CPU, RAM, disk) — text + linear bar, no
/// decorative dials; a director glances at this, they don't study it.
class MetricGauge extends StatelessWidget {
  const MetricGauge({
    super.key,
    required this.label,
    required this.percent,
    this.detail,
  });

  final String label;
  final double? percent;
  final String? detail;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final value = percent;
    final color = value == null
        ? scheme.outlineVariant
        : value >= 90
            ? scheme.error
            : value >= 75
                ? Colors.orange
                : scheme.primary;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: Theme.of(context).textTheme.bodyMedium),
            Text(
              value == null ? '—' : '${value.toStringAsFixed(0)}%',
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: value == null ? 0 : (value / 100).clamp(0.0, 1.0),
            minHeight: 6,
            color: color,
            backgroundColor: scheme.surfaceContainerHighest,
          ),
        ),
        if (detail != null)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(
              detail!,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: scheme.outline),
            ),
          ),
      ],
    );
  }
}

class ConnectionChip extends StatelessWidget {
  const ConnectionChip({super.key, required this.state});

  final BoxConnectionState state;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final (label, color) = switch (state) {
      BoxConnectionState.connected => (l10n.connConnected, Colors.green),
      BoxConnectionState.connecting => (l10n.connConnecting, Colors.orange),
      BoxConnectionState.offline => (l10n.connOffline, Colors.red),
      BoxConnectionState.unpaired => (l10n.connUnpaired, Colors.grey),
    };
    return Chip(
      key: const Key('connection-chip'),
      label: Text(label, style: const TextStyle(fontSize: 12)),
      backgroundColor: color.withValues(alpha: 0.15),
      side: BorderSide(color: color),
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }
}

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, this.text});

  final String? text;

  @override
  Widget build(BuildContext context) {
    return Container(
      key: const Key('offline-banner'),
      width: double.infinity,
      color: Colors.amber.shade200,
      padding: const EdgeInsets.all(8),
      child: Text(
        text ?? AppLocalizations.of(context).offlineBanner,
        textAlign: TextAlign.center,
        style: const TextStyle(color: Colors.black87, fontSize: 13),
      ),
    );
  }
}

/// Label/value row that never overflows: the value truncates gracefully
/// (long box names, IPs, and translated labels must coexist on 390px).
class KeyValueRow extends StatelessWidget {
  const KeyValueRow(this.label, this.value, {super.key, this.valueKey});

  final String label;
  final String value;
  final Key? valueKey;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(child: Text(label)),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              value,
              key: valueKey,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.end,
              style: const TextStyle(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

/// Card with consistent padding used across dashboard/health screens.
class PanelCard extends StatelessWidget {
  const PanelCard({super.key, required this.child, this.onTap});

  final Widget child;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(padding: const EdgeInsets.all(16), child: child),
      ),
    );
  }
}
