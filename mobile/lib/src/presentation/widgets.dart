/// Shared building blocks, drawn to the SafeKids Director design comp.
///
/// Every screen is assembled from these, so the comp is honoured in one
/// place rather than re-derived per screen. Colours come from [SkColors] —
/// nothing here holds a hex.
library;

import 'package:flutter/material.dart';

import '../../l10n/generated/app_localizations.dart';
import '../application/connection_controller.dart';
import 'design.dart';

/// The comp's uppercase group label, optionally with a "View all" action.
class SectionHeader extends StatelessWidget {
  const SectionHeader(this.title, {super.key, this.trailing});

  final String title;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          SkSpace.screenGutter, SkSpace.sectionTop, SkSpace.screenGutter, 8),
      // The label and its action share one line, as in the comp. A default
      // TextButton is taller than the label and would push itself onto a
      // line of its own, which is what this row is sized against.
      child: Row(
        children: [
          Expanded(
            child: Text(
              title.toUpperCase(),
              style: SkType.sectionLabel.copyWith(color: sk.textMuted),
            ),
          ),
          if (trailing != null)
            ConstrainedBox(
              constraints: const BoxConstraints(maxHeight: 20),
              child: trailing!,
            ),
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

/// The comp's pill: a soft tone behind short, loud, uppercase text.
class TonePill extends StatelessWidget {
  const TonePill(this.label,
      {super.key, required this.tone, this.dense = false});

  final String label;
  final SkTone tone;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: EdgeInsets.symmetric(
          horizontal: dense ? 9 : 10, vertical: dense ? 3 : 4),
      decoration: BoxDecoration(
        color: tone.background,
        borderRadius: BorderRadius.circular(SkRadius.pill),
      ),
      child: Text(
        label.toUpperCase(),
        style: SkType.badge.copyWith(color: tone.foreground),
      ),
    );
  }
}

/// A labeled percentage gauge (CPU, RAM, disk) — text + linear bar, no
/// decorative dials; a director glances at this, they don't study it.
///
/// The comp draws every bar in the action colour. That reads as "this is a
/// number", not "this is a problem", so a genuinely alarming value still
/// escalates to the warning and danger tones.
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
    final sk = context.sk;
    final value = percent;
    final color = switch (value) {
      null => sk.borderStrong,
      >= 90 => sk.danger,
      >= 75 => sk.warning,
      _ => sk.accent,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: SkType.detail.copyWith(color: sk.textSecondary)),
            Text(
              value == null ? '—' : '${value.toStringAsFixed(0)}%',
              style: SkType.detail.copyWith(
                fontWeight: FontWeight.w600,
                color: sk.textPrimary,
              ),
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
            backgroundColor: sk.track,
          ),
        ),
        if (detail != null)
          Padding(
            padding: const EdgeInsets.only(top: 3),
            child: Text(
              detail!,
              style: SkType.caption.copyWith(color: sk.textFaint),
            ),
          ),
      ],
    );
  }
}

/// The comp's live-connection badge: a status dot and one word.
///
/// The comp pulses the dot. That is decoration — the state is already
/// carried by the word and the tone — and a repeating animation means
/// `pumpAndSettle` can never settle, which would cost every widget test in
/// the suite and every one written after it. Not a trade worth making for
/// a breathing dot.
class ConnectionChip extends StatelessWidget {
  const ConnectionChip({super.key, required this.state});

  final BoxConnectionState state;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    final l10n = AppLocalizations.of(context);
    final (label, tone) = switch (state) {
      BoxConnectionState.connected => (l10n.connConnected, sk.positiveTone),
      BoxConnectionState.connecting => (l10n.connConnecting, sk.medium),
      BoxConnectionState.offline => (l10n.connOffline, sk.critical),
      BoxConnectionState.unpaired => (l10n.connUnpaired, sk.neutralTone),
    };
    return Container(
      key: const Key('connection-chip'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: tone.background,
        borderRadius: BorderRadius.circular(SkRadius.pill),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          StatusDot(color: tone.dot, size: 5),
          const SizedBox(width: 5),
          Text(
            label.toUpperCase(),
            style: SkType.badge.copyWith(
              color: tone.foreground,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}

class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, this.text});

  final String? text;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    return Container(
      key: const Key('offline-banner'),
      width: double.infinity,
      margin: const EdgeInsets.fromLTRB(
          SkSpace.screenGutter, 0, SkSpace.screenGutter, 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: sk.medium.background,
        borderRadius: BorderRadius.circular(SkRadius.chip),
      ),
      child: Text(
        text ?? AppLocalizations.of(context).offlineBanner,
        textAlign: TextAlign.center,
        style: SkType.caption.copyWith(color: sk.medium.foreground),
      ),
    );
  }
}

/// Label/value row that never overflows: the value truncates gracefully
/// (long box names, IPs, and translated labels must coexist on 390px).
class KeyValueRow extends StatelessWidget {
  const KeyValueRow(
    this.label,
    this.value, {
    super.key,
    this.valueKey,
    this.mono = false,
  });

  final String label;
  final String value;
  final Key? valueKey;

  /// Ids, addresses and versions are monospaced in the comp so digits line
  /// up and a value does not re-flow as it changes.
  final bool mono;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        children: [
          Expanded(
            child:
                Text(label, style: SkType.detail.copyWith(color: sk.textMuted)),
          ),
          const SizedBox(width: 12),
          Flexible(
            child: Text(
              value,
              key: valueKey,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.end,
              style: SkType.detail.copyWith(
                fontWeight: FontWeight.w600,
                color: sk.textPrimary,
                fontFamilyFallback: mono ? SkType.mono : null,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// The comp's white card: one-pixel border, no shadow, generous radius.
class PanelCard extends StatelessWidget {
  const PanelCard({
    super.key,
    required this.child,
    this.onTap,
    this.padding = const EdgeInsets.all(SkSpace.cardPadding),
  });

  final Widget child;
  final VoidCallback? onTap;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.symmetric(
          horizontal: SkSpace.screenGutter, vertical: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(SkRadius.card),
        child: Padding(padding: padding, child: child),
      ),
    );
  }
}

/// A tappable settings/navigation row: icon, label, chevron.
class NavRow extends StatelessWidget {
  const NavRow({
    super.key,
    required this.icon,
    required this.label,
    required this.onTap,
    this.last = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool last;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 13),
        decoration: BoxDecoration(
          border: last ? null : Border(bottom: BorderSide(color: sk.divider)),
        ),
        child: Row(
          children: [
            Icon(icon, size: 18, color: sk.textSecondary),
            const SizedBox(width: 11),
            Expanded(
              child: Text(label,
                  style: SkType.rowTitle.copyWith(
                      fontWeight: FontWeight.w400, color: sk.textPrimary)),
            ),
            Icon(Icons.chevron_right, size: 18, color: sk.borderStrong),
          ],
        ),
      ),
    );
  }
}

/// The comp's segmented control (alert shelves, theme, cache size).
class SkSegmented<T> extends StatelessWidget {
  const SkSegmented({
    super.key,
    required this.options,
    required this.selected,
    required this.onSelect,
    this.keyPrefix,
  });

  final List<(T value, String label)> options;
  final T selected;
  final ValueChanged<T> onSelect;
  final String? keyPrefix;

  @override
  Widget build(BuildContext context) {
    final sk = context.sk;
    return Container(
      padding: const EdgeInsets.all(3),
      decoration: BoxDecoration(
        color: sk.track,
        borderRadius: BorderRadius.circular(SkRadius.chip),
      ),
      child: Row(
        children: [
          for (final (value, label) in options)
            Expanded(
              child: GestureDetector(
                key: keyPrefix == null ? null : Key('$keyPrefix-$value'),
                onTap: () => onSelect(value),
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 7),
                  decoration: BoxDecoration(
                    color: value == selected ? sk.card : Colors.transparent,
                    borderRadius: BorderRadius.circular(7),
                  ),
                  child: Text(
                    label,
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                      color: value == selected ? sk.textPrimary : sk.textMuted,
                    ),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
