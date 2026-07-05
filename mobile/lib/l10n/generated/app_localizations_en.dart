// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for English (`en`).
class AppLocalizationsEn extends AppLocalizations {
  AppLocalizationsEn([String locale = 'en']) : super(locale);

  @override
  String get appTitle => 'Guardian SafeKids';

  @override
  String get navDashboard => 'Dashboard';

  @override
  String get navAlerts => 'Alerts';

  @override
  String get navCameras => 'Cameras';

  @override
  String get navHealth => 'Health';

  @override
  String get navSettings => 'Settings';

  @override
  String get connConnected => 'Connected';

  @override
  String get connConnecting => 'Connecting…';

  @override
  String get connOffline => 'Offline';

  @override
  String get connUnpaired => 'Not paired';

  @override
  String get offlineBanner => 'Offline — showing cached data, reconnecting…';

  @override
  String get dashSystemStatus => 'System status';

  @override
  String get statusOk => 'All systems normal';

  @override
  String get statusDegraded => 'Degraded';

  @override
  String get statusWarning => 'Needs attention';

  @override
  String get statusError => 'Problem detected';

  @override
  String get statusUnknown => 'Unknown';

  @override
  String get dashConnectedCameras => 'Cameras';

  @override
  String dashCamerasOnline(int online, int total) {
    return '$online of $total online';
  }

  @override
  String get dashRecentIncidents => 'Recent incidents';

  @override
  String get dashNoIncidents => 'No incidents — all quiet.';

  @override
  String get dashCpu => 'CPU';

  @override
  String get dashRam => 'RAM';

  @override
  String get dashLastSync => 'Last sync';

  @override
  String get dashNever => 'never';

  @override
  String get justNow => 'just now';

  @override
  String minutesAgo(int minutes) {
    return '$minutes min ago';
  }

  @override
  String get dashViewAll => 'View all';

  @override
  String boxVersion(String version) {
    return 'Box v$version';
  }

  @override
  String get alertsTitle => 'Notification center';

  @override
  String get alertsSearchHint => 'Search alerts (camera, track, text)';

  @override
  String get tabUnread => 'Unread';

  @override
  String get tabRead => 'Read';

  @override
  String get tabArchived => 'Archived';

  @override
  String get alertsEmpty => 'No notifications here — all quiet.';

  @override
  String get alertsNoMatches => 'Nothing matches your search or filters.';

  @override
  String get loadMore => 'Load more';

  @override
  String get archive => 'Archive';

  @override
  String get unarchive => 'Unarchive';

  @override
  String get markAllRead => 'Mark all read';

  @override
  String get allCameras => 'All cameras';

  @override
  String get today => 'Today';

  @override
  String get yesterday => 'Yesterday';

  @override
  String get potentialFall => 'Potential fall';

  @override
  String get severityLow => 'Low';

  @override
  String get severityMedium => 'Medium';

  @override
  String get severityHigh => 'High';

  @override
  String get severityCritical => 'Critical';

  @override
  String get statusPendingReview => 'Pending review';

  @override
  String get statusConfirmed => 'Confirmed';

  @override
  String get statusDismissed => 'Dismissed';

  @override
  String get incidentTitle => 'Incident';

  @override
  String get incidentTimeline => 'Timeline';

  @override
  String get incidentSignals => 'Signals';

  @override
  String get incidentEvidence => 'Evidence';

  @override
  String get incidentReviewStatus => 'Review status';

  @override
  String get incidentTrackHistory => 'Track history';

  @override
  String get confirmAction => 'Confirm';

  @override
  String get dismissAction => 'Dismiss';

  @override
  String get confirmQuestion => 'Confirm this incident as a real safety event?';

  @override
  String get dismissQuestion => 'Dismiss this incident as a false alarm?';

  @override
  String get reviewNoteHint => 'Note (optional)';

  @override
  String get decisionRecorded => 'Decision recorded on the box.';

  @override
  String get decisionFailed =>
      'Could not record the decision — check the connection.';

  @override
  String get incidentUnavailableOffline =>
      'Live details unavailable — the box is unreachable. Showing cached notification data.';

  @override
  String get evidenceMetadataOnly =>
      'Evidence is metadata only: no images or video ever leave the box. People appear as track numbers, never identities.';

  @override
  String trackNumber(int number) {
    return 'Track #$number';
  }

  @override
  String get cameraLabel => 'Camera';

  @override
  String get openedAtLabel => 'Opened';

  @override
  String get lastEventLabel => 'Last event';

  @override
  String get confidenceLabel => 'Confidence';

  @override
  String get riskConfidenceLabel => 'Risk confidence';

  @override
  String eventsCount(int count) {
    return '$count corroborating events';
  }

  @override
  String get reviewerLabel => 'Reviewed by';

  @override
  String get notificationsOfIncident => 'Notifications of this incident';

  @override
  String get camerasTitle => 'Cameras';

  @override
  String get camerasEmpty => 'No cameras reported yet — waiting for the box.';

  @override
  String get cameraHealthy => 'Healthy';

  @override
  String get cameraDegraded => 'Degraded';

  @override
  String get cameraUnhealthy => 'Unhealthy';

  @override
  String get cameraRecovering => 'Recovering';

  @override
  String get cameraUnknown => 'Unknown';

  @override
  String get fpsLabel => 'FPS';

  @override
  String get latencyLabel => 'Latency';

  @override
  String get framesProcessed => 'Frames processed';

  @override
  String get framesDropped => 'Frames dropped';

  @override
  String get detectorErrors => 'Detector errors';

  @override
  String get trackerErrors => 'Tracker errors';

  @override
  String get restartCamera => 'Restart camera';

  @override
  String get restartUnsupported =>
      'This box version has no remote restart — automatic recovery already restarts crashed cameras and reconnects dropped streams.';

  @override
  String get restartFailed => 'Restart request failed — check the connection.';

  @override
  String get restartRequested => 'Restart requested.';

  @override
  String get healthTitle => 'System health';

  @override
  String get subsystemsSection => 'Subsystems';

  @override
  String get hostSection => 'Edge box host';

  @override
  String get cpuLabel => 'CPU';

  @override
  String get ramLabel => 'RAM';

  @override
  String get temperatureLabel => 'Temperature';

  @override
  String get diskLabel => 'Disk';

  @override
  String get networkSection => 'Network';

  @override
  String get uptimeLabel => 'Uptime';

  @override
  String diskFreeGb(String gb) {
    return '$gb GB free';
  }

  @override
  String get boxUnreachable =>
      'Box unreachable — showing the last known snapshot.';

  @override
  String get noHealthYet =>
      'No health data yet. Pair with a box and make sure it is running.';

  @override
  String get boxAddressLabel => 'Box address';

  @override
  String get warningsSection => 'Warnings';

  @override
  String get notAvailable => 'n/a';

  @override
  String get pairTitle => 'Pair with Guardian Box';

  @override
  String get pairIntro =>
      'Pair this phone with the Guardian Box on your local network. Nothing leaves the building — no accounts, no cloud.';

  @override
  String get pairScanQr => 'Scan QR code';

  @override
  String get pairManualEntry => 'Enter manually';

  @override
  String get pairHostLabel => 'Box address (IP)';

  @override
  String get pairPortLabel => 'Port';

  @override
  String get pairCodeLabel => 'Pairing code';

  @override
  String get pairDeviceNameLabel => 'This device name';

  @override
  String get pairButton => 'Pair';

  @override
  String get pairBusy => 'Pairing…';

  @override
  String get pairQrHint =>
      'Point the camera at the QR code from the box\'s install report or poster.';

  @override
  String get pairQrInvalid => 'That QR code is not a Guardian pairing code.';

  @override
  String get pairQrFilled =>
      'Box details filled from QR — enter the pairing code shown on the box.';

  @override
  String get trustedDevicesTitle => 'Trusted devices';

  @override
  String get trustedThisDevice => 'This device';

  @override
  String get trustedBoxLabel => 'Paired box';

  @override
  String get forgetBox => 'Forget this box';

  @override
  String get forgetBoxQuestion =>
      'Forget this box? You will need a new pairing code to reconnect. (To revoke this phone on the box, remove it from trusted devices there.)';

  @override
  String get settingsTitle => 'Settings';

  @override
  String get themeSection => 'Theme';

  @override
  String get themeSystem => 'System';

  @override
  String get themeLight => 'Light';

  @override
  String get themeDark => 'Dark';

  @override
  String get languageSection => 'Language';

  @override
  String get langSystem => 'System language';

  @override
  String get notifSection => 'Notification preferences';

  @override
  String get notifEnabled => 'In-app alerts';

  @override
  String get notifEnabledHint =>
      'Highlight new alerts with a banner and badge.';

  @override
  String get sensitivityLabel => 'Alert sensitivity';

  @override
  String get sensitivityHint =>
      'Minimum severity that raises an alert. Lower = more alerts.';

  @override
  String get quietHoursLabel => 'Quiet hours';

  @override
  String get quietHoursHint => 'Soften non-critical alerts during this period.';

  @override
  String get quietFrom => 'From';

  @override
  String get quietTo => 'Until';

  @override
  String get criticalAlwaysAlerts =>
      'Critical alerts always come through — quiet hours never silence an emergency.';

  @override
  String get aboutSection => 'About';

  @override
  String get privacyNote =>
      'Video never leaves the box. This app receives metadata only.';

  @override
  String get retry => 'Retry';

  @override
  String get cancel => 'Cancel';

  @override
  String get ok => 'OK';

  @override
  String get close => 'Close';
}
