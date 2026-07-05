import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:guardian_core/guardian_core.dart';

import 'notification_cache.dart';

/// Director-facing app settings. Everything is device-local — the box's
/// detection behavior is never changed from the phone (frozen engines;
/// humans tune presentation, not the safety pipeline).
@immutable
class AppSettings {
  const AppSettings({
    this.themeMode = ThemeMode.system,
    this.localeCode,
    this.notificationsEnabled = true,
    this.minAlertSeverity = Severity.medium,
    this.quietHoursEnabled = false,
    this.quietStartMinutes = 22 * 60,
    this.quietEndMinutes = 7 * 60,
  });

  final ThemeMode themeMode;

  /// null = follow the system locale.
  final String? localeCode;

  /// Master switch for in-app alerting emphasis (list still shows all).
  final bool notificationsEnabled;

  /// Sensitivity: the minimum severity that raises an in-app alert.
  final Severity minAlertSeverity;

  final bool quietHoursEnabled;

  /// Minutes from midnight, local time. A range may cross midnight.
  final int quietStartMinutes;
  final int quietEndMinutes;

  Locale? get locale => localeCode == null ? null : Locale(localeCode!);

  bool isQuietAt(DateTime now) {
    if (!quietHoursEnabled) {
      return false;
    }
    final minutes = now.hour * 60 + now.minute;
    if (quietStartMinutes <= quietEndMinutes) {
      return minutes >= quietStartMinutes && minutes < quietEndMinutes;
    }
    // Overnight range, e.g. 22:00 -> 07:00.
    return minutes >= quietStartMinutes || minutes < quietEndMinutes;
  }

  /// Should this notification alert the director right now?
  ///
  /// CRITICAL always alerts — quiet hours and sensitivity soften noise,
  /// they never silence a child-safety emergency (docs/04).
  bool shouldAlert(Severity severity, DateTime now) {
    if (severity == Severity.critical) {
      return true;
    }
    if (!notificationsEnabled) {
      return false;
    }
    if (severity.rank < minAlertSeverity.rank) {
      return false;
    }
    return !isQuietAt(now);
  }

  AppSettings copyWith({
    ThemeMode? themeMode,
    String? Function()? localeCode,
    bool? notificationsEnabled,
    Severity? minAlertSeverity,
    bool? quietHoursEnabled,
    int? quietStartMinutes,
    int? quietEndMinutes,
  }) {
    return AppSettings(
      themeMode: themeMode ?? this.themeMode,
      localeCode: localeCode == null ? this.localeCode : localeCode(),
      notificationsEnabled: notificationsEnabled ?? this.notificationsEnabled,
      minAlertSeverity: minAlertSeverity ?? this.minAlertSeverity,
      quietHoursEnabled: quietHoursEnabled ?? this.quietHoursEnabled,
      quietStartMinutes: quietStartMinutes ?? this.quietStartMinutes,
      quietEndMinutes: quietEndMinutes ?? this.quietEndMinutes,
    );
  }

  Map<String, dynamic> toJson() => {
        'theme_mode': themeMode.name,
        'locale': localeCode,
        'notifications_enabled': notificationsEnabled,
        'min_alert_severity': minAlertSeverity.wire,
        'quiet_hours_enabled': quietHoursEnabled,
        'quiet_start_minutes': quietStartMinutes,
        'quiet_end_minutes': quietEndMinutes,
      };

  factory AppSettings.fromJson(Map<String, dynamic> json) => AppSettings(
        themeMode: ThemeMode.values.asNameMap()[json['theme_mode']] ??
            ThemeMode.system,
        localeCode: json['locale'] as String?,
        notificationsEnabled: json['notifications_enabled'] as bool? ?? true,
        minAlertSeverity:
            _severityOr(json['min_alert_severity'] as String?, Severity.medium),
        quietHoursEnabled: json['quiet_hours_enabled'] as bool? ?? false,
        quietStartMinutes: json['quiet_start_minutes'] as int? ?? 22 * 60,
        quietEndMinutes: json['quiet_end_minutes'] as int? ?? 7 * 60,
      );

  static Severity _severityOr(String? wire, Severity fallback) {
    if (wire == null) {
      return fallback;
    }
    try {
      return Severity.fromWire(wire);
    } on FormatException {
      return fallback;
    }
  }
}

/// Loads, exposes and persists [AppSettings]; every mutation writes the
/// cache first so a crash never loses a preference.
class SettingsController extends ChangeNotifier {
  SettingsController(this._cache);

  final NotificationCache _cache;
  AppSettings _settings = const AppSettings();

  AppSettings get settings => _settings;

  Future<void> initialize() async {
    final raw = await _cache.loadSettings();
    if (raw != null) {
      try {
        _settings =
            AppSettings.fromJson(jsonDecode(raw) as Map<String, dynamic>);
      } on Object {
        _settings = const AppSettings(); // corrupt settings reset to defaults
      }
    }
    notifyListeners();
  }

  Future<void> update(AppSettings next) async {
    await _cache.saveSettings(jsonEncode(next.toJson()));
    _settings = next;
    notifyListeners();
  }
}
