/// SafeKids Director design system — the one place a colour or a radius is
/// decided (design comp: "SafeKids Director App").
///
/// The comp is a warm-paper light interface with a single orange action
/// colour and four severity palettes. Every value here comes from it; a
/// screen that hardcodes a hex is a bug (ENGINEERING.md: avoid magic numbers).
///
/// Two deliberate departures from the comp, both documented rather than
/// silently improvised:
///
/// * **Dark mode is derived, not given.** The comp specifies light only,
///   but the app has shipped a system/light/dark setting since Sprint 13.
///   The dark palette below keeps every role and hue relationship and
///   re-lights it; it is a reading of the comp, not a quotation of it.
/// * **Typography is the comp's scale, not its typefaces.** The comp loads
///   Inter and JetBrains Mono from fonts.googleapis.com. This app promises
///   its users that nothing leaves the building — a runtime font fetch
///   would break that promise on the first launch. Sizes, weights and
///   letter-spacing are reproduced exactly on the platform font; if the
///   exact typefaces are wanted, bundle the files as local assets and set
///   [fontFamily] here. Never through a network loader.
library;

import 'package:flutter/material.dart';
import 'package:guardian_core/guardian_core.dart';

/// Corner radii, in the comp's own steps.
abstract final class SkRadius {
  static const card = 14.0;
  static const control = 10.0;
  static const chip = 9.0;
  static const inner = 8.0;
  static const pill = 999.0;
}

/// Spacing steps used by the comp's layouts.
abstract final class SkSpace {
  static const screenGutter = 16.0;
  static const cardPadding = 14.0;
  static const sectionTop = 18.0;
  static const rowGap = 10.0;
}

/// One severity's three roles: a soft background, a readable foreground,
/// and a saturated dot that must stay legible against a card.
@immutable
class SkTone {
  const SkTone(
      {required this.background, required this.foreground, required this.dot});

  final Color background;
  final Color foreground;
  final Color dot;

  static SkTone lerp(SkTone a, SkTone b, double t) => SkTone(
        background: Color.lerp(a.background, b.background, t)!,
        foreground: Color.lerp(a.foreground, b.foreground, t)!,
        dot: Color.lerp(a.dot, b.dot, t)!,
      );
}

/// The palette, carried on the theme so no widget reaches for a constant.
@immutable
class SkColors extends ThemeExtension<SkColors> {
  const SkColors({
    required this.surface,
    required this.card,
    required this.fill,
    required this.track,
    required this.divider,
    required this.border,
    required this.borderStrong,
    required this.textPrimary,
    required this.textSecondary,
    required this.textMuted,
    required this.textFaint,
    required this.accent,
    required this.onAccent,
    required this.positive,
    required this.positiveTone,
    required this.warning,
    required this.danger,
    required this.dangerText,
    required this.low,
    required this.medium,
    required this.high,
    required this.critical,
    required this.neutralTone,
  });

  final Color surface;
  final Color card;
  final Color fill;
  final Color track;
  final Color divider;
  final Color border;
  final Color borderStrong;

  final Color textPrimary;
  final Color textSecondary;
  final Color textMuted;
  final Color textFaint;

  final Color accent;
  final Color onAccent;

  /// Healthy/connected. The comp uses green only for calm states — never
  /// on an alert, so "green" never reads as "an incident you can ignore".
  final Color positive;
  final SkTone positiveTone;
  final Color warning;
  final Color danger;

  /// Destructive text (forget box, clear cache) — readable, not shouting.
  final Color dangerText;

  final SkTone low;
  final SkTone medium;
  final SkTone high;
  final SkTone critical;

  /// Dismissed/inactive chips.
  final SkTone neutralTone;

  SkTone toneFor(Severity severity) => switch (severity) {
        Severity.low => low,
        Severity.medium => medium,
        Severity.high => high,
        Severity.critical => critical,
      };

  SkTone toneForStatus(IncidentStatus status) => switch (status) {
        IncidentStatus.pendingReview => medium,
        IncidentStatus.confirmed => critical,
        IncidentStatus.dismissed => neutralTone,
      };

  /// Health colours for the box and its cameras.
  Color statusColor(BoxStatus status) => switch (status) {
        BoxStatus.ok => positive,
        BoxStatus.degraded || BoxStatus.warning => warning,
        BoxStatus.error => danger,
        BoxStatus.unknown => textFaint,
      };

  Color cameraColor(String status) => switch (status) {
        'healthy' => positive,
        'degraded' || 'recovering' => warning,
        'unhealthy' => danger,
        _ => textFaint,
      };

  static const light = SkColors(
    surface: Color(0xFFF7F7F4),
    card: Color(0xFFFFFFFF),
    fill: Color(0xFFFAFAF7),
    track: Color(0xFFEEEDE8),
    divider: Color(0xFFEFEEE8),
    border: Color(0xFFE6E5E0),
    borderStrong: Color(0xFFCFCDC4),
    textPrimary: Color(0xFF26251E),
    textSecondary: Color(0xFF5A5852),
    textMuted: Color(0xFF807D72),
    textFaint: Color(0xFFA09C92),
    accent: Color(0xFFF54E00),
    onAccent: Color(0xFFFFFFFF),
    positive: Color(0xFF1F8A65),
    positiveTone: SkTone(
      background: Color(0xFFE3EFE2),
      foreground: Color(0xFF1F6A3E),
      dot: Color(0xFF1F8A65),
    ),
    warning: Color(0xFFC08532),
    danger: Color(0xFFCF2D56),
    dangerText: Color(0xFF8E1D36),
    low: SkTone(
      background: Color(0xFFE1EBF6),
      foreground: Color(0xFF2C4F7C),
      dot: Color(0xFF2C4F7C),
    ),
    medium: SkTone(
      background: Color(0xFFF7E6DC),
      foreground: Color(0xFF7A3D1D),
      dot: Color(0xFF7A3D1D),
    ),
    high: SkTone(
      background: Color(0xFFEDE0C5),
      foreground: Color(0xFF6C4A14),
      dot: Color(0xFF6C4A14),
    ),
    critical: SkTone(
      background: Color(0xFFFBE2E8),
      foreground: Color(0xFF8E1D36),
      dot: Color(0xFFCF2D56),
    ),
    neutralTone: SkTone(
      background: Color(0xFFEEEDE8),
      foreground: Color(0xFF26251E),
      dot: Color(0xFFA09C92),
    ),
  );

  /// Derived from [light]: same roles, same hues, re-lit for a dark room.
  /// A director checking a 03:00 alert should not be flashbanged.
  static const dark = SkColors(
    surface: Color(0xFF16150F),
    card: Color(0xFF232219),
    fill: Color(0xFF1D1C15),
    track: Color(0xFF33312A),
    divider: Color(0xFF2E2C25),
    border: Color(0xFF34322A),
    borderStrong: Color(0xFF4A473D),
    textPrimary: Color(0xFFF2F0E8),
    textSecondary: Color(0xFFCFCCC0),
    textMuted: Color(0xFFA09C92),
    textFaint: Color(0xFF807D72),
    accent: Color(0xFFFF6A26),
    onAccent: Color(0xFF1A0B03),
    positive: Color(0xFF35C48F),
    positiveTone: SkTone(
      background: Color(0xFF1B3328),
      foreground: Color(0xFF8FD9B6),
      dot: Color(0xFF35C48F),
    ),
    warning: Color(0xFFD9A253),
    danger: Color(0xFFE0567F),
    dangerText: Color(0xFFF2A8BC),
    low: SkTone(
      background: Color(0xFF1E2C3D),
      foreground: Color(0xFFA8C6E8),
      dot: Color(0xFF6F9FD0),
    ),
    medium: SkTone(
      background: Color(0xFF3A2A1D),
      foreground: Color(0xFFE8BF9C),
      dot: Color(0xFFC98F5E),
    ),
    high: SkTone(
      background: Color(0xFF362C17),
      foreground: Color(0xFFE0C68B),
      dot: Color(0xFFC2A04F),
    ),
    critical: SkTone(
      background: Color(0xFF3D1B26),
      foreground: Color(0xFFF2A8BC),
      dot: Color(0xFFE0567F),
    ),
    neutralTone: SkTone(
      background: Color(0xFF2E2C25),
      foreground: Color(0xFFF2F0E8),
      dot: Color(0xFF807D72),
    ),
  );

  @override
  SkColors copyWith() => this;

  @override
  SkColors lerp(ThemeExtension<SkColors>? other, double t) {
    if (other is! SkColors) {
      return this;
    }
    return SkColors(
      surface: Color.lerp(surface, other.surface, t)!,
      card: Color.lerp(card, other.card, t)!,
      fill: Color.lerp(fill, other.fill, t)!,
      track: Color.lerp(track, other.track, t)!,
      divider: Color.lerp(divider, other.divider, t)!,
      border: Color.lerp(border, other.border, t)!,
      borderStrong: Color.lerp(borderStrong, other.borderStrong, t)!,
      textPrimary: Color.lerp(textPrimary, other.textPrimary, t)!,
      textSecondary: Color.lerp(textSecondary, other.textSecondary, t)!,
      textMuted: Color.lerp(textMuted, other.textMuted, t)!,
      textFaint: Color.lerp(textFaint, other.textFaint, t)!,
      accent: Color.lerp(accent, other.accent, t)!,
      onAccent: Color.lerp(onAccent, other.onAccent, t)!,
      positive: Color.lerp(positive, other.positive, t)!,
      positiveTone: SkTone.lerp(positiveTone, other.positiveTone, t),
      warning: Color.lerp(warning, other.warning, t)!,
      danger: Color.lerp(danger, other.danger, t)!,
      dangerText: Color.lerp(dangerText, other.dangerText, t)!,
      low: SkTone.lerp(low, other.low, t),
      medium: SkTone.lerp(medium, other.medium, t),
      high: SkTone.lerp(high, other.high, t),
      critical: SkTone.lerp(critical, other.critical, t),
      neutralTone: SkTone.lerp(neutralTone, other.neutralTone, t),
    );
  }
}

/// The comp's type scale. Sizes and weights are quoted exactly; the family
/// is the platform's (see the library doc for why).
abstract final class SkType {
  /// Numeric identity — track ids, versions, addresses, FPS. Monospace so
  /// digits line up and an id never re-flows as it changes.
  static const mono = <String>['monospace'];

  static const tabTitle = TextStyle(
    fontSize: 22,
    fontWeight: FontWeight.w600,
    letterSpacing: -0.33,
    height: 1.2,
  );
  static const pushTitle = TextStyle(
      fontSize: 16, fontWeight: FontWeight.w600, letterSpacing: -0.16);

  /// The uppercase section labels that separate every group in the comp.
  static const sectionLabel = TextStyle(
    fontSize: 11,
    fontWeight: FontWeight.w700,
    letterSpacing: 0.88,
    height: 1.3,
  );

  static const cardTitle = TextStyle(fontSize: 15, fontWeight: FontWeight.w600);
  static const rowTitle =
      TextStyle(fontSize: 13.5, fontWeight: FontWeight.w600);
  static const rowTitleQuiet =
      TextStyle(fontSize: 13.5, fontWeight: FontWeight.w400);
  static const rowMeta = TextStyle(fontSize: 12, height: 1.3);
  static const body = TextStyle(fontSize: 13, height: 1.5);
  static const detail = TextStyle(fontSize: 12.5);
  static const caption = TextStyle(fontSize: 11.5, height: 1.5);
  static const badge = TextStyle(
    fontSize: 10,
    fontWeight: FontWeight.w700,
    letterSpacing: 0.4,
  );
  static const navLabel = TextStyle(fontSize: 10, fontWeight: FontWeight.w600);
}

/// Convenience: `context.sk` instead of a Theme lookup at every call site.
extension SkTheme on BuildContext {
  SkColors get sk => Theme.of(this).extension<SkColors>() ?? SkColors.light;
}
