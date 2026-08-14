import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/intl.dart' as intl;

import 'app_localizations_en.dart';
import 'app_localizations_ru.dart';
import 'app_localizations_uz.dart';

// ignore_for_file: type=lint

/// Callers can lookup localized strings with an instance of AppLocalizations
/// returned by `AppLocalizations.of(context)`.
///
/// Applications need to include `AppLocalizations.delegate()` in their app's
/// `localizationDelegates` list, and the locales they support in the app's
/// `supportedLocales` list. For example:
///
/// ```dart
/// import 'generated/app_localizations.dart';
///
/// return MaterialApp(
///   localizationsDelegates: AppLocalizations.localizationsDelegates,
///   supportedLocales: AppLocalizations.supportedLocales,
///   home: MyApplicationHome(),
/// );
/// ```
///
/// ## Update pubspec.yaml
///
/// Please make sure to update your pubspec.yaml to include the following
/// packages:
///
/// ```yaml
/// dependencies:
///   # Internationalization support.
///   flutter_localizations:
///     sdk: flutter
///   intl: any # Use the pinned version from flutter_localizations
///
///   # Rest of dependencies
/// ```
///
/// ## iOS Applications
///
/// iOS applications define key application metadata, including supported
/// locales, in an Info.plist file that is built into the application bundle.
/// To configure the locales supported by your app, you’ll need to edit this
/// file.
///
/// First, open your project’s ios/Runner.xcworkspace Xcode workspace file.
/// Then, in the Project Navigator, open the Info.plist file under the Runner
/// project’s Runner folder.
///
/// Next, select the Information Property List item, select Add Item from the
/// Editor menu, then select Localizations from the pop-up menu.
///
/// Select and expand the newly-created Localizations item then, for each
/// locale your application supports, add a new item and select the locale
/// you wish to add from the pop-up menu in the Value field. This list should
/// be consistent with the languages listed in the AppLocalizations.supportedLocales
/// property.
abstract class AppLocalizations {
  AppLocalizations(String locale)
      : localeName = intl.Intl.canonicalizedLocale(locale.toString());

  final String localeName;

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const LocalizationsDelegate<AppLocalizations> delegate =
      _AppLocalizationsDelegate();

  /// A list of this localizations delegate along with the default localizations
  /// delegates.
  ///
  /// Returns a list of localizations delegates containing this delegate along with
  /// GlobalMaterialLocalizations.delegate, GlobalCupertinoLocalizations.delegate,
  /// and GlobalWidgetsLocalizations.delegate.
  ///
  /// Additional delegates can be added by appending to this list in
  /// MaterialApp. This list does not have to be used at all if a custom list
  /// of delegates is preferred or required.
  static const List<LocalizationsDelegate<dynamic>> localizationsDelegates =
      <LocalizationsDelegate<dynamic>>[
    delegate,
    GlobalMaterialLocalizations.delegate,
    GlobalCupertinoLocalizations.delegate,
    GlobalWidgetsLocalizations.delegate,
  ];

  /// A list of this localizations delegate's supported locales.
  static const List<Locale> supportedLocales = <Locale>[
    Locale('en'),
    Locale('ru'),
    Locale('uz')
  ];

  /// No description provided for @appTitle.
  ///
  /// In en, this message translates to:
  /// **'Guardian SafeKids'**
  String get appTitle;

  /// No description provided for @navDashboard.
  ///
  /// In en, this message translates to:
  /// **'Dashboard'**
  String get navDashboard;

  /// No description provided for @navAlerts.
  ///
  /// In en, this message translates to:
  /// **'Alerts'**
  String get navAlerts;

  /// No description provided for @navCameras.
  ///
  /// In en, this message translates to:
  /// **'Cameras'**
  String get navCameras;

  /// No description provided for @navHealth.
  ///
  /// In en, this message translates to:
  /// **'Health'**
  String get navHealth;

  /// No description provided for @navSettings.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get navSettings;

  /// No description provided for @connConnected.
  ///
  /// In en, this message translates to:
  /// **'Connected'**
  String get connConnected;

  /// No description provided for @connConnecting.
  ///
  /// In en, this message translates to:
  /// **'Connecting…'**
  String get connConnecting;

  /// No description provided for @connOffline.
  ///
  /// In en, this message translates to:
  /// **'Offline'**
  String get connOffline;

  /// No description provided for @connUnpaired.
  ///
  /// In en, this message translates to:
  /// **'Not paired'**
  String get connUnpaired;

  /// No description provided for @offlineBanner.
  ///
  /// In en, this message translates to:
  /// **'Offline — showing cached data, reconnecting…'**
  String get offlineBanner;

  /// No description provided for @dashSystemStatus.
  ///
  /// In en, this message translates to:
  /// **'System status'**
  String get dashSystemStatus;

  /// No description provided for @statusOk.
  ///
  /// In en, this message translates to:
  /// **'All systems normal'**
  String get statusOk;

  /// No description provided for @statusDegraded.
  ///
  /// In en, this message translates to:
  /// **'Degraded'**
  String get statusDegraded;

  /// No description provided for @statusWarning.
  ///
  /// In en, this message translates to:
  /// **'Needs attention'**
  String get statusWarning;

  /// No description provided for @statusError.
  ///
  /// In en, this message translates to:
  /// **'Problem detected'**
  String get statusError;

  /// No description provided for @statusUnknown.
  ///
  /// In en, this message translates to:
  /// **'Unknown'**
  String get statusUnknown;

  /// No description provided for @dashConnectedCameras.
  ///
  /// In en, this message translates to:
  /// **'Cameras'**
  String get dashConnectedCameras;

  /// No description provided for @dashCamerasOnline.
  ///
  /// In en, this message translates to:
  /// **'{online} of {total} online'**
  String dashCamerasOnline(int online, int total);

  /// No description provided for @dashRecentIncidents.
  ///
  /// In en, this message translates to:
  /// **'Recent incidents'**
  String get dashRecentIncidents;

  /// No description provided for @dashNoIncidents.
  ///
  /// In en, this message translates to:
  /// **'No incidents — all quiet.'**
  String get dashNoIncidents;

  /// No description provided for @dashCpu.
  ///
  /// In en, this message translates to:
  /// **'CPU'**
  String get dashCpu;

  /// No description provided for @dashRam.
  ///
  /// In en, this message translates to:
  /// **'RAM'**
  String get dashRam;

  /// No description provided for @dashLastSync.
  ///
  /// In en, this message translates to:
  /// **'Last sync'**
  String get dashLastSync;

  /// No description provided for @dashNever.
  ///
  /// In en, this message translates to:
  /// **'never'**
  String get dashNever;

  /// No description provided for @justNow.
  ///
  /// In en, this message translates to:
  /// **'just now'**
  String get justNow;

  /// No description provided for @minutesAgo.
  ///
  /// In en, this message translates to:
  /// **'{minutes} min ago'**
  String minutesAgo(int minutes);

  /// No description provided for @dashViewAll.
  ///
  /// In en, this message translates to:
  /// **'View all'**
  String get dashViewAll;

  /// No description provided for @boxVersion.
  ///
  /// In en, this message translates to:
  /// **'Box v{version}'**
  String boxVersion(String version);

  /// No description provided for @alertsTitle.
  ///
  /// In en, this message translates to:
  /// **'Notification center'**
  String get alertsTitle;

  /// No description provided for @alertsSearchHint.
  ///
  /// In en, this message translates to:
  /// **'Search alerts (camera, track, text)'**
  String get alertsSearchHint;

  /// No description provided for @tabUnread.
  ///
  /// In en, this message translates to:
  /// **'Unread'**
  String get tabUnread;

  /// No description provided for @tabRead.
  ///
  /// In en, this message translates to:
  /// **'Read'**
  String get tabRead;

  /// No description provided for @tabArchived.
  ///
  /// In en, this message translates to:
  /// **'Archived'**
  String get tabArchived;

  /// No description provided for @alertsEmpty.
  ///
  /// In en, this message translates to:
  /// **'No notifications here — all quiet.'**
  String get alertsEmpty;

  /// No description provided for @alertsNoMatches.
  ///
  /// In en, this message translates to:
  /// **'Nothing matches your search or filters.'**
  String get alertsNoMatches;

  /// No description provided for @loadMore.
  ///
  /// In en, this message translates to:
  /// **'Load more'**
  String get loadMore;

  /// No description provided for @archive.
  ///
  /// In en, this message translates to:
  /// **'Archive'**
  String get archive;

  /// No description provided for @unarchive.
  ///
  /// In en, this message translates to:
  /// **'Unarchive'**
  String get unarchive;

  /// No description provided for @markAllRead.
  ///
  /// In en, this message translates to:
  /// **'Mark all read'**
  String get markAllRead;

  /// No description provided for @allCameras.
  ///
  /// In en, this message translates to:
  /// **'All cameras'**
  String get allCameras;

  /// No description provided for @today.
  ///
  /// In en, this message translates to:
  /// **'Today'**
  String get today;

  /// No description provided for @yesterday.
  ///
  /// In en, this message translates to:
  /// **'Yesterday'**
  String get yesterday;

  /// No description provided for @potentialFall.
  ///
  /// In en, this message translates to:
  /// **'Potential fall'**
  String get potentialFall;

  /// No description provided for @safetyIncident.
  ///
  /// In en, this message translates to:
  /// **'Safety incident'**
  String get safetyIncident;

  /// No description provided for @severityLow.
  ///
  /// In en, this message translates to:
  /// **'Low'**
  String get severityLow;

  /// No description provided for @severityMedium.
  ///
  /// In en, this message translates to:
  /// **'Medium'**
  String get severityMedium;

  /// No description provided for @severityHigh.
  ///
  /// In en, this message translates to:
  /// **'High'**
  String get severityHigh;

  /// No description provided for @severityCritical.
  ///
  /// In en, this message translates to:
  /// **'Critical'**
  String get severityCritical;

  /// No description provided for @statusPendingReview.
  ///
  /// In en, this message translates to:
  /// **'Pending review'**
  String get statusPendingReview;

  /// No description provided for @statusConfirmed.
  ///
  /// In en, this message translates to:
  /// **'Confirmed'**
  String get statusConfirmed;

  /// No description provided for @statusDismissed.
  ///
  /// In en, this message translates to:
  /// **'Dismissed'**
  String get statusDismissed;

  /// No description provided for @incidentTitle.
  ///
  /// In en, this message translates to:
  /// **'Incident'**
  String get incidentTitle;

  /// No description provided for @incidentTimeline.
  ///
  /// In en, this message translates to:
  /// **'Timeline'**
  String get incidentTimeline;

  /// No description provided for @incidentSignals.
  ///
  /// In en, this message translates to:
  /// **'Signals'**
  String get incidentSignals;

  /// No description provided for @incidentEvidence.
  ///
  /// In en, this message translates to:
  /// **'Evidence'**
  String get incidentEvidence;

  /// No description provided for @incidentReviewStatus.
  ///
  /// In en, this message translates to:
  /// **'Review status'**
  String get incidentReviewStatus;

  /// No description provided for @incidentTrackHistory.
  ///
  /// In en, this message translates to:
  /// **'Track history'**
  String get incidentTrackHistory;

  /// No description provided for @confirmAction.
  ///
  /// In en, this message translates to:
  /// **'Confirm'**
  String get confirmAction;

  /// No description provided for @dismissAction.
  ///
  /// In en, this message translates to:
  /// **'Dismiss'**
  String get dismissAction;

  /// No description provided for @confirmQuestion.
  ///
  /// In en, this message translates to:
  /// **'Confirm this incident as a real safety event?'**
  String get confirmQuestion;

  /// No description provided for @dismissQuestion.
  ///
  /// In en, this message translates to:
  /// **'Dismiss this incident as a false alarm?'**
  String get dismissQuestion;

  /// No description provided for @reviewNoteHint.
  ///
  /// In en, this message translates to:
  /// **'Note (optional)'**
  String get reviewNoteHint;

  /// No description provided for @decisionRecorded.
  ///
  /// In en, this message translates to:
  /// **'Decision recorded on the box.'**
  String get decisionRecorded;

  /// No description provided for @decisionFailed.
  ///
  /// In en, this message translates to:
  /// **'Could not record the decision — check the connection.'**
  String get decisionFailed;

  /// No description provided for @incidentUnavailableOffline.
  ///
  /// In en, this message translates to:
  /// **'Live details unavailable — the box is unreachable. Showing cached notification data.'**
  String get incidentUnavailableOffline;

  /// No description provided for @evidenceMetadataOnly.
  ///
  /// In en, this message translates to:
  /// **'Evidence is metadata only: no images or video ever leave the box. People appear as track numbers, never identities.'**
  String get evidenceMetadataOnly;

  /// No description provided for @trackNumber.
  ///
  /// In en, this message translates to:
  /// **'Track #{number}'**
  String trackNumber(int number);

  /// No description provided for @cameraLabel.
  ///
  /// In en, this message translates to:
  /// **'Camera'**
  String get cameraLabel;

  /// No description provided for @openedAtLabel.
  ///
  /// In en, this message translates to:
  /// **'Opened'**
  String get openedAtLabel;

  /// No description provided for @lastEventLabel.
  ///
  /// In en, this message translates to:
  /// **'Last event'**
  String get lastEventLabel;

  /// No description provided for @confidenceLabel.
  ///
  /// In en, this message translates to:
  /// **'Confidence'**
  String get confidenceLabel;

  /// No description provided for @riskConfidenceLabel.
  ///
  /// In en, this message translates to:
  /// **'Risk confidence'**
  String get riskConfidenceLabel;

  /// No description provided for @eventsCount.
  ///
  /// In en, this message translates to:
  /// **'{count} corroborating events'**
  String eventsCount(int count);

  /// No description provided for @reviewerLabel.
  ///
  /// In en, this message translates to:
  /// **'Reviewed by'**
  String get reviewerLabel;

  /// No description provided for @notificationsOfIncident.
  ///
  /// In en, this message translates to:
  /// **'Notifications of this incident'**
  String get notificationsOfIncident;

  /// No description provided for @camerasTitle.
  ///
  /// In en, this message translates to:
  /// **'Cameras'**
  String get camerasTitle;

  /// No description provided for @camerasEmpty.
  ///
  /// In en, this message translates to:
  /// **'No cameras reported yet — waiting for the box.'**
  String get camerasEmpty;

  /// No description provided for @cameraHealthy.
  ///
  /// In en, this message translates to:
  /// **'Healthy'**
  String get cameraHealthy;

  /// No description provided for @cameraDegraded.
  ///
  /// In en, this message translates to:
  /// **'Degraded'**
  String get cameraDegraded;

  /// No description provided for @cameraUnhealthy.
  ///
  /// In en, this message translates to:
  /// **'Unhealthy'**
  String get cameraUnhealthy;

  /// No description provided for @cameraRecovering.
  ///
  /// In en, this message translates to:
  /// **'Recovering'**
  String get cameraRecovering;

  /// No description provided for @cameraUnknown.
  ///
  /// In en, this message translates to:
  /// **'Unknown'**
  String get cameraUnknown;

  /// No description provided for @fpsLabel.
  ///
  /// In en, this message translates to:
  /// **'FPS'**
  String get fpsLabel;

  /// No description provided for @latencyLabel.
  ///
  /// In en, this message translates to:
  /// **'Latency'**
  String get latencyLabel;

  /// No description provided for @framesProcessed.
  ///
  /// In en, this message translates to:
  /// **'Frames processed'**
  String get framesProcessed;

  /// No description provided for @framesDropped.
  ///
  /// In en, this message translates to:
  /// **'Frames dropped'**
  String get framesDropped;

  /// No description provided for @detectorErrors.
  ///
  /// In en, this message translates to:
  /// **'Detector errors'**
  String get detectorErrors;

  /// No description provided for @trackerErrors.
  ///
  /// In en, this message translates to:
  /// **'Tracker errors'**
  String get trackerErrors;

  /// No description provided for @restartCamera.
  ///
  /// In en, this message translates to:
  /// **'Restart camera'**
  String get restartCamera;

  /// No description provided for @restartUnsupported.
  ///
  /// In en, this message translates to:
  /// **'This box version has no remote restart — automatic recovery already restarts crashed cameras and reconnects dropped streams.'**
  String get restartUnsupported;

  /// No description provided for @restartFailed.
  ///
  /// In en, this message translates to:
  /// **'Restart request failed — check the connection.'**
  String get restartFailed;

  /// No description provided for @restartRequested.
  ///
  /// In en, this message translates to:
  /// **'Restart requested.'**
  String get restartRequested;

  /// No description provided for @healthTitle.
  ///
  /// In en, this message translates to:
  /// **'System health'**
  String get healthTitle;

  /// No description provided for @subsystemsSection.
  ///
  /// In en, this message translates to:
  /// **'Subsystems'**
  String get subsystemsSection;

  /// No description provided for @hostSection.
  ///
  /// In en, this message translates to:
  /// **'Edge box host'**
  String get hostSection;

  /// No description provided for @cpuLabel.
  ///
  /// In en, this message translates to:
  /// **'CPU'**
  String get cpuLabel;

  /// No description provided for @ramLabel.
  ///
  /// In en, this message translates to:
  /// **'RAM'**
  String get ramLabel;

  /// No description provided for @temperatureLabel.
  ///
  /// In en, this message translates to:
  /// **'Temperature'**
  String get temperatureLabel;

  /// No description provided for @diskLabel.
  ///
  /// In en, this message translates to:
  /// **'Disk'**
  String get diskLabel;

  /// No description provided for @networkSection.
  ///
  /// In en, this message translates to:
  /// **'Network'**
  String get networkSection;

  /// No description provided for @uptimeLabel.
  ///
  /// In en, this message translates to:
  /// **'Uptime'**
  String get uptimeLabel;

  /// No description provided for @diskFreeGb.
  ///
  /// In en, this message translates to:
  /// **'{gb} GB free'**
  String diskFreeGb(String gb);

  /// No description provided for @boxUnreachable.
  ///
  /// In en, this message translates to:
  /// **'Box unreachable — showing the last known snapshot.'**
  String get boxUnreachable;

  /// No description provided for @noHealthYet.
  ///
  /// In en, this message translates to:
  /// **'No health data yet. Pair with a box and make sure it is running.'**
  String get noHealthYet;

  /// No description provided for @boxAddressLabel.
  ///
  /// In en, this message translates to:
  /// **'Box address'**
  String get boxAddressLabel;

  /// No description provided for @warningsSection.
  ///
  /// In en, this message translates to:
  /// **'Warnings'**
  String get warningsSection;

  /// No description provided for @notAvailable.
  ///
  /// In en, this message translates to:
  /// **'n/a'**
  String get notAvailable;

  /// No description provided for @pairTitle.
  ///
  /// In en, this message translates to:
  /// **'Pair with Guardian Box'**
  String get pairTitle;

  /// No description provided for @pairIntro.
  ///
  /// In en, this message translates to:
  /// **'Pair this phone with the Guardian Box on your local network. Nothing leaves the building — no accounts, no cloud.'**
  String get pairIntro;

  /// No description provided for @pairScanQr.
  ///
  /// In en, this message translates to:
  /// **'Scan QR code'**
  String get pairScanQr;

  /// No description provided for @pairManualEntry.
  ///
  /// In en, this message translates to:
  /// **'Enter manually'**
  String get pairManualEntry;

  /// No description provided for @pairHostLabel.
  ///
  /// In en, this message translates to:
  /// **'Box address (IP)'**
  String get pairHostLabel;

  /// No description provided for @pairPortLabel.
  ///
  /// In en, this message translates to:
  /// **'Port'**
  String get pairPortLabel;

  /// No description provided for @pairCodeLabel.
  ///
  /// In en, this message translates to:
  /// **'Pairing code'**
  String get pairCodeLabel;

  /// No description provided for @pairDeviceNameLabel.
  ///
  /// In en, this message translates to:
  /// **'This device name'**
  String get pairDeviceNameLabel;

  /// No description provided for @pairButton.
  ///
  /// In en, this message translates to:
  /// **'Pair'**
  String get pairButton;

  /// No description provided for @pairBusy.
  ///
  /// In en, this message translates to:
  /// **'Pairing…'**
  String get pairBusy;

  /// No description provided for @pairQrHint.
  ///
  /// In en, this message translates to:
  /// **'Point the camera at the QR code from the box\'s install report or poster.'**
  String get pairQrHint;

  /// No description provided for @pairQrInvalid.
  ///
  /// In en, this message translates to:
  /// **'That QR code is not a Guardian pairing code.'**
  String get pairQrInvalid;

  /// No description provided for @pairQrFilled.
  ///
  /// In en, this message translates to:
  /// **'Box details filled from QR — enter the pairing code shown on the box.'**
  String get pairQrFilled;

  /// No description provided for @trustedDevicesTitle.
  ///
  /// In en, this message translates to:
  /// **'Trusted devices'**
  String get trustedDevicesTitle;

  /// No description provided for @trustedThisDevice.
  ///
  /// In en, this message translates to:
  /// **'This device'**
  String get trustedThisDevice;

  /// No description provided for @trustedBoxLabel.
  ///
  /// In en, this message translates to:
  /// **'Paired box'**
  String get trustedBoxLabel;

  /// No description provided for @forgetBox.
  ///
  /// In en, this message translates to:
  /// **'Forget this box'**
  String get forgetBox;

  /// No description provided for @forgetBoxQuestion.
  ///
  /// In en, this message translates to:
  /// **'Forget this box? You will need a new pairing code to reconnect. (To revoke this phone on the box, remove it from trusted devices there.)'**
  String get forgetBoxQuestion;

  /// No description provided for @settingsTitle.
  ///
  /// In en, this message translates to:
  /// **'Settings'**
  String get settingsTitle;

  /// No description provided for @themeSection.
  ///
  /// In en, this message translates to:
  /// **'Theme'**
  String get themeSection;

  /// No description provided for @themeSystem.
  ///
  /// In en, this message translates to:
  /// **'System'**
  String get themeSystem;

  /// No description provided for @themeLight.
  ///
  /// In en, this message translates to:
  /// **'Light'**
  String get themeLight;

  /// No description provided for @themeDark.
  ///
  /// In en, this message translates to:
  /// **'Dark'**
  String get themeDark;

  /// No description provided for @languageSection.
  ///
  /// In en, this message translates to:
  /// **'Language'**
  String get languageSection;

  /// No description provided for @langSystem.
  ///
  /// In en, this message translates to:
  /// **'System language'**
  String get langSystem;

  /// No description provided for @notifSection.
  ///
  /// In en, this message translates to:
  /// **'Notification preferences'**
  String get notifSection;

  /// No description provided for @notifEnabled.
  ///
  /// In en, this message translates to:
  /// **'In-app alerts'**
  String get notifEnabled;

  /// No description provided for @notifEnabledHint.
  ///
  /// In en, this message translates to:
  /// **'Highlight new alerts with a banner and badge.'**
  String get notifEnabledHint;

  /// No description provided for @sensitivityLabel.
  ///
  /// In en, this message translates to:
  /// **'Alert sensitivity'**
  String get sensitivityLabel;

  /// No description provided for @sensitivityHint.
  ///
  /// In en, this message translates to:
  /// **'Minimum severity that raises an alert. Lower = more alerts.'**
  String get sensitivityHint;

  /// No description provided for @quietHoursLabel.
  ///
  /// In en, this message translates to:
  /// **'Quiet hours'**
  String get quietHoursLabel;

  /// No description provided for @quietHoursHint.
  ///
  /// In en, this message translates to:
  /// **'Soften non-critical alerts during this period.'**
  String get quietHoursHint;

  /// No description provided for @quietFrom.
  ///
  /// In en, this message translates to:
  /// **'From'**
  String get quietFrom;

  /// No description provided for @quietTo.
  ///
  /// In en, this message translates to:
  /// **'Until'**
  String get quietTo;

  /// No description provided for @criticalAlwaysAlerts.
  ///
  /// In en, this message translates to:
  /// **'Critical alerts always come through — quiet hours never silence an emergency.'**
  String get criticalAlwaysAlerts;

  /// No description provided for @aboutSection.
  ///
  /// In en, this message translates to:
  /// **'About'**
  String get aboutSection;

  /// No description provided for @privacyNote.
  ///
  /// In en, this message translates to:
  /// **'Video never leaves the box. This app receives metadata only.'**
  String get privacyNote;

  /// No description provided for @retry.
  ///
  /// In en, this message translates to:
  /// **'Retry'**
  String get retry;

  /// No description provided for @cancel.
  ///
  /// In en, this message translates to:
  /// **'Cancel'**
  String get cancel;

  /// No description provided for @ok.
  ///
  /// In en, this message translates to:
  /// **'OK'**
  String get ok;

  /// No description provided for @close.
  ///
  /// In en, this message translates to:
  /// **'Close'**
  String get close;

  /// No description provided for @evidenceVideoSection.
  ///
  /// In en, this message translates to:
  /// **'Video evidence'**
  String get evidenceVideoSection;

  /// No description provided for @aiSignalsSection.
  ///
  /// In en, this message translates to:
  /// **'AI signals'**
  String get aiSignalsSection;

  /// No description provided for @evidenceNone.
  ///
  /// In en, this message translates to:
  /// **'No video evidence for this incident (the box may predate evidence support, or the clip has expired).'**
  String get evidenceNone;

  /// No description provided for @evidencePreparing.
  ///
  /// In en, this message translates to:
  /// **'The box is preparing the clip (15 s before + 15 s after the incident)…'**
  String get evidencePreparing;

  /// No description provided for @evidenceFailed.
  ///
  /// In en, this message translates to:
  /// **'Clip export failed on the box — the camera buffer was empty around the incident.'**
  String get evidenceFailed;

  /// No description provided for @evidenceDownload.
  ///
  /// In en, this message translates to:
  /// **'Download clip'**
  String get evidenceDownload;

  /// No description provided for @evidenceDownloading.
  ///
  /// In en, this message translates to:
  /// **'Downloading…'**
  String get evidenceDownloading;

  /// No description provided for @evidenceOfflineNote.
  ///
  /// In en, this message translates to:
  /// **'Saved on this phone — plays offline. Sharing is disabled by design.'**
  String get evidenceOfflineNote;

  /// No description provided for @evidenceOriginal.
  ///
  /// In en, this message translates to:
  /// **'Original'**
  String get evidenceOriginal;

  /// No description provided for @evidenceAiView.
  ///
  /// In en, this message translates to:
  /// **'AI analysis'**
  String get evidenceAiView;

  /// No description provided for @playerPlay.
  ///
  /// In en, this message translates to:
  /// **'Play'**
  String get playerPlay;

  /// No description provided for @playerPause.
  ///
  /// In en, this message translates to:
  /// **'Pause'**
  String get playerPause;

  /// No description provided for @playerReplay.
  ///
  /// In en, this message translates to:
  /// **'Replay'**
  String get playerReplay;

  /// No description provided for @playerFullscreen.
  ///
  /// In en, this message translates to:
  /// **'Fullscreen'**
  String get playerFullscreen;

  /// No description provided for @evidenceCacheLabel.
  ///
  /// In en, this message translates to:
  /// **'Evidence cache size'**
  String get evidenceCacheLabel;

  /// No description provided for @evidenceCacheHint.
  ///
  /// In en, this message translates to:
  /// **'Downloaded clips stay for offline review; oldest are removed beyond this limit.'**
  String get evidenceCacheHint;

  /// No description provided for @clearEvidenceCache.
  ///
  /// In en, this message translates to:
  /// **'Clear downloaded evidence'**
  String get clearEvidenceCache;

  /// No description provided for @cacheCleared.
  ///
  /// In en, this message translates to:
  /// **'Downloaded evidence removed from this phone.'**
  String get cacheCleared;
}

class _AppLocalizationsDelegate
    extends LocalizationsDelegate<AppLocalizations> {
  const _AppLocalizationsDelegate();

  @override
  Future<AppLocalizations> load(Locale locale) {
    return SynchronousFuture<AppLocalizations>(lookupAppLocalizations(locale));
  }

  @override
  bool isSupported(Locale locale) =>
      <String>['en', 'ru', 'uz'].contains(locale.languageCode);

  @override
  bool shouldReload(_AppLocalizationsDelegate old) => false;
}

AppLocalizations lookupAppLocalizations(Locale locale) {
  // Lookup logic when only language code is specified.
  switch (locale.languageCode) {
    case 'en':
      return AppLocalizationsEn();
    case 'ru':
      return AppLocalizationsRu();
    case 'uz':
      return AppLocalizationsUz();
  }

  throw FlutterError(
      'AppLocalizations.delegate failed to load unsupported locale "$locale". This is likely '
      'an issue with the localizations generation tool. Please file an issue '
      'on GitHub with a reproducible sample app and the gen-l10n configuration '
      'that was used.');
}
