import 'package:flutter/material.dart';
import 'package:guardian_core/guardian_core.dart';

import '../../l10n/generated/app_localizations.dart';

/// Shared severity color scale (calm green never appears on alerts).
Color severityColor(Severity severity) => switch (severity) {
      Severity.low => Colors.blueGrey,
      Severity.medium => Colors.orange,
      Severity.high => Colors.deepOrange,
      Severity.critical => Colors.red.shade700,
    };

Color boxStatusColor(BoxStatus status, ColorScheme scheme) => switch (status) {
      BoxStatus.ok => Colors.green.shade600,
      BoxStatus.degraded => Colors.orange,
      BoxStatus.warning => Colors.orange.shade800,
      BoxStatus.error => scheme.error,
      BoxStatus.unknown => Colors.grey,
    };

Color cameraStatusColor(String status) => switch (status) {
      'healthy' => Colors.green.shade600,
      'degraded' || 'recovering' => Colors.orange,
      'unhealthy' => Colors.red.shade700,
      _ => Colors.grey,
    };

String severityLabel(AppLocalizations l10n, Severity severity) =>
    switch (severity) {
      Severity.low => l10n.severityLow,
      Severity.medium => l10n.severityMedium,
      Severity.high => l10n.severityHigh,
      Severity.critical => l10n.severityCritical,
    };

/// The event's own name — read from the incident, never assumed.
///
/// An event type this build does not know renders as the neutral
/// "Safety incident": severity, camera, time and summary still tell the
/// director what to look at, and nothing claims to be something it isn't.
String incidentTypeLabel(AppLocalizations l10n, IncidentType type) =>
    switch (type) {
      IncidentType.potentialFall => l10n.potentialFall,
      IncidentType.zoneExit => l10n.zoneExit,
      IncidentType.unknown => l10n.safetyIncident,
    };

String incidentStatusLabel(AppLocalizations l10n, IncidentStatus status) =>
    switch (status) {
      IncidentStatus.pendingReview => l10n.statusPendingReview,
      IncidentStatus.confirmed => l10n.statusConfirmed,
      IncidentStatus.dismissed => l10n.statusDismissed,
    };

String boxStatusLabel(AppLocalizations l10n, BoxStatus status) =>
    switch (status) {
      BoxStatus.ok => l10n.statusOk,
      BoxStatus.degraded => l10n.statusDegraded,
      BoxStatus.warning => l10n.statusWarning,
      BoxStatus.error => l10n.statusError,
      BoxStatus.unknown => l10n.statusUnknown,
    };

String cameraStatusLabel(AppLocalizations l10n, String status) =>
    switch (status) {
      'healthy' => l10n.cameraHealthy,
      'degraded' => l10n.cameraDegraded,
      'unhealthy' => l10n.cameraUnhealthy,
      'recovering' => l10n.cameraRecovering,
      _ => l10n.cameraUnknown,
    };

String formatTime(DateTime timestamp) {
  final local = timestamp.toLocal();
  String pad(int value) => value.toString().padLeft(2, '0');
  return '${pad(local.hour)}:${pad(local.minute)}:${pad(local.second)}';
}

String formatDate(DateTime timestamp) {
  final local = timestamp.toLocal();
  String pad(int value) => value.toString().padLeft(2, '0');
  return '${local.year}-${pad(local.month)}-${pad(local.day)}';
}

/// Localized "Today"/"Yesterday"/date header for list grouping.
String dateHeader(AppLocalizations l10n, DateTime timestamp, DateTime now) {
  final local = timestamp.toLocal();
  final today = DateTime(now.year, now.month, now.day);
  final day = DateTime(local.year, local.month, local.day);
  if (day == today) {
    return l10n.today;
  }
  if (day == today.subtract(const Duration(days: 1))) {
    return l10n.yesterday;
  }
  return formatDate(timestamp);
}

String agoLabel(AppLocalizations l10n, Duration? age) {
  if (age == null) {
    return l10n.dashNever;
  }
  if (age.inMinutes < 1) {
    return l10n.justNow;
  }
  return l10n.minutesAgo(age.inMinutes);
}

String formatUptime(double? seconds) {
  if (seconds == null) {
    return '—';
  }
  final duration = Duration(seconds: seconds.round());
  final days = duration.inDays;
  final hours = duration.inHours % 24;
  final minutes = duration.inMinutes % 60;
  if (days > 0) {
    return '${days}d ${hours}h';
  }
  if (duration.inHours > 0) {
    return '${hours}h ${minutes}m';
  }
  return '${minutes}m';
}

String formatMinutesOfDay(int minutes) {
  String pad(int value) => value.toString().padLeft(2, '0');
  return '${pad(minutes ~/ 60)}:${pad(minutes % 60)}';
}
