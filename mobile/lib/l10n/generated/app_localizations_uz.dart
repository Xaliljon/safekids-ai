// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Uzbek (`uz`).
class AppLocalizationsUz extends AppLocalizations {
  AppLocalizationsUz([String locale = 'uz']) : super(locale);

  @override
  String get appTitle => 'Guardian SafeKids';

  @override
  String get navDashboard => 'Boshqaruv';

  @override
  String get navAlerts => 'Bildirishnomalar';

  @override
  String get navCameras => 'Kameralar';

  @override
  String get navHealth => 'Tizim';

  @override
  String get navSettings => 'Sozlamalar';

  @override
  String get connConnected => 'Ulangan';

  @override
  String get connConnecting => 'Ulanmoqda…';

  @override
  String get connOffline => 'Oflayn';

  @override
  String get connUnpaired => 'Ulanmagan';

  @override
  String get offlineBanner =>
      'Oflayn — saqlangan ma\'lumotlar ko\'rsatilmoqda, qayta ulanmoqda…';

  @override
  String get dashSystemStatus => 'Tizim holati';

  @override
  String get statusOk => 'Barcha tizimlar normal';

  @override
  String get statusDegraded => 'Cheklangan ish';

  @override
  String get statusWarning => 'E\'tibor talab qiladi';

  @override
  String get statusError => 'Muammo aniqlandi';

  @override
  String get statusUnknown => 'Noma\'lum';

  @override
  String get dashConnectedCameras => 'Kameralar';

  @override
  String dashCamerasOnline(int online, int total) {
    return '$total tadan $online tasi onlayn';
  }

  @override
  String get dashRecentIncidents => 'So\'nggi hodisalar';

  @override
  String get dashNoIncidents => 'Hodisalar yo\'q — hammasi tinch.';

  @override
  String get dashCpu => 'CPU';

  @override
  String get dashRam => 'RAM';

  @override
  String get dashLastSync => 'So\'nggi sinxronlash';

  @override
  String get dashNever => 'hech qachon';

  @override
  String get justNow => 'hozirgina';

  @override
  String minutesAgo(int minutes) {
    return '$minutes daqiqa oldin';
  }

  @override
  String get dashViewAll => 'Hammasini ko\'rish';

  @override
  String boxVersion(String version) {
    return 'Boks v$version';
  }

  @override
  String get alertsTitle => 'Bildirishnomalar markazi';

  @override
  String get alertsSearchHint => 'Qidirish (kamera, trek, matn)';

  @override
  String get tabUnread => 'Yangi';

  @override
  String get tabRead => 'O\'qilgan';

  @override
  String get tabArchived => 'Arxiv';

  @override
  String get alertsEmpty => 'Bu yer bo\'sh — hammasi tinch.';

  @override
  String get alertsNoMatches => 'Qidiruv yoki filtrga mos narsa topilmadi.';

  @override
  String get loadMore => 'Yana ko\'rsatish';

  @override
  String get archive => 'Arxivga';

  @override
  String get unarchive => 'Arxivdan chiqarish';

  @override
  String get markAllRead => 'Barchasini o\'qilgan qilish';

  @override
  String get allCameras => 'Barcha kameralar';

  @override
  String get today => 'Bugun';

  @override
  String get yesterday => 'Kecha';

  @override
  String get potentialFall => 'Ehtimoliy yiqilish';

  @override
  String get severityLow => 'Past';

  @override
  String get severityMedium => 'O\'rta';

  @override
  String get severityHigh => 'Yuqori';

  @override
  String get severityCritical => 'Kritik';

  @override
  String get statusPendingReview => 'Tekshiruv kutilmoqda';

  @override
  String get statusConfirmed => 'Tasdiqlangan';

  @override
  String get statusDismissed => 'Rad etilgan';

  @override
  String get incidentTitle => 'Hodisa';

  @override
  String get incidentTimeline => 'Xronologiya';

  @override
  String get incidentSignals => 'Signallar';

  @override
  String get incidentEvidence => 'Dalillar';

  @override
  String get incidentReviewStatus => 'Tekshiruv holati';

  @override
  String get incidentTrackHistory => 'Trek tarixi';

  @override
  String get confirmAction => 'Tasdiqlash';

  @override
  String get dismissAction => 'Rad etish';

  @override
  String get confirmQuestion =>
      'Bu hodisa haqiqiy xavfli holat sifatida tasdiqlansinmi?';

  @override
  String get dismissQuestion =>
      'Bu hodisa yolg\'on signal sifatida rad etilsinmi?';

  @override
  String get reviewNoteHint => 'Izoh (ixtiyoriy)';

  @override
  String get decisionRecorded => 'Qaror boksga yozildi.';

  @override
  String get decisionFailed =>
      'Qarorni yozib bo\'lmadi — ulanishni tekshiring.';

  @override
  String get incidentUnavailableOffline =>
      'Boks bilan aloqa yo\'q — bildirishnomaning saqlangan ma\'lumotlari ko\'rsatilmoqda.';

  @override
  String get evidenceMetadataOnly =>
      'Dalillar faqat metama\'lumotlar: rasm va video hech qachon boksdan chiqmaydi. Odamlar trek raqamlari bilan ko\'rsatiladi, ism-shariflarsiz.';

  @override
  String trackNumber(int number) {
    return 'Trek №$number';
  }

  @override
  String get cameraLabel => 'Kamera';

  @override
  String get openedAtLabel => 'Ochilgan';

  @override
  String get lastEventLabel => 'So\'nggi hodisa';

  @override
  String get confidenceLabel => 'Ishonchlilik';

  @override
  String get riskConfidenceLabel => 'Xavf bahosi';

  @override
  String eventsCount(int count) {
    return 'Tasdiqlovchi hodisalar: $count';
  }

  @override
  String get reviewerLabel => 'Tekshirdi';

  @override
  String get notificationsOfIncident => 'Ushbu hodisa bildirishnomalari';

  @override
  String get camerasTitle => 'Kameralar';

  @override
  String get camerasEmpty => 'Kameralar hali kelmadi — boks kutilmoqda.';

  @override
  String get cameraHealthy => 'Normal';

  @override
  String get cameraDegraded => 'Nosozlik bor';

  @override
  String get cameraUnhealthy => 'Ishlamayapti';

  @override
  String get cameraRecovering => 'Tiklanmoqda';

  @override
  String get cameraUnknown => 'Noma\'lum';

  @override
  String get fpsLabel => 'Kadr/s';

  @override
  String get latencyLabel => 'Kechikish';

  @override
  String get framesProcessed => 'Qayta ishlangan kadrlar';

  @override
  String get framesDropped => 'Tashlab yuborilgan kadrlar';

  @override
  String get detectorErrors => 'Detektor xatolari';

  @override
  String get trackerErrors => 'Treker xatolari';

  @override
  String get restartCamera => 'Kamerani qayta ishga tushirish';

  @override
  String get restartUnsupported =>
      'Bu boks versiyasi masofaviy qayta ishga tushirishni qo\'llamaydi — avtomatik tiklanish qulagan kameralarni o\'zi qayta ishga tushiradi va uzilgan oqimlarni qayta ulaydi.';

  @override
  String get restartFailed => 'So\'rov yuborilmadi — ulanishni tekshiring.';

  @override
  String get restartRequested => 'Qayta ishga tushirish so\'raldi.';

  @override
  String get healthTitle => 'Tizim holati';

  @override
  String get subsystemsSection => 'Quyi tizimlar';

  @override
  String get hostSection => 'Edge boks hosti';

  @override
  String get cpuLabel => 'CPU';

  @override
  String get ramLabel => 'RAM';

  @override
  String get temperatureLabel => 'Harorat';

  @override
  String get diskLabel => 'Disk';

  @override
  String get networkSection => 'Tarmoq';

  @override
  String get uptimeLabel => 'Ish vaqti';

  @override
  String diskFreeGb(String gb) {
    return '$gb GB bo\'sh';
  }

  @override
  String get boxUnreachable =>
      'Boks bilan aloqa yo\'q — oxirgi ma\'lum holat ko\'rsatilmoqda.';

  @override
  String get noHealthYet =>
      'Hozircha ma\'lumot yo\'q. Boks bilan ulanib, u ishlayotganini tekshiring.';

  @override
  String get boxAddressLabel => 'Boks manzili';

  @override
  String get warningsSection => 'Ogohlantirishlar';

  @override
  String get notAvailable => 'yo\'q';

  @override
  String get pairTitle => 'Guardian Box bilan ulanish';

  @override
  String get pairIntro =>
      'Telefonni mahalliy tarmoqdagi Guardian Box bilan ulang. Hech narsa binodan chiqmaydi — akkauntlarsiz, bulutsiz.';

  @override
  String get pairScanQr => 'QR kodni skanerlash';

  @override
  String get pairManualEntry => 'Qo\'lda kiritish';

  @override
  String get pairHostLabel => 'Boks manzili (IP)';

  @override
  String get pairPortLabel => 'Port';

  @override
  String get pairCodeLabel => 'Ulanish kodi';

  @override
  String get pairDeviceNameLabel => 'Bu qurilma nomi';

  @override
  String get pairButton => 'Ulanish';

  @override
  String get pairBusy => 'Ulanmoqda…';

  @override
  String get pairQrHint =>
      'Kamerani boksning o\'rnatish hisobotidagi yoki plakatidagi QR kodga qarating.';

  @override
  String get pairQrInvalid => 'Bu Guardian ulanish QR kodi emas.';

  @override
  String get pairQrFilled =>
      'Boks ma\'lumotlari QR\'dan to\'ldirildi — boks ekranidagi ulanish kodini kiriting.';

  @override
  String get trustedDevicesTitle => 'Ishonchli qurilmalar';

  @override
  String get trustedThisDevice => 'Bu qurilma';

  @override
  String get trustedBoxLabel => 'Ulangan boks';

  @override
  String get forgetBox => 'Bu boksni unutish';

  @override
  String get forgetBoxQuestion =>
      'Bu boks unutilsinmi? Qayta ulanish uchun yangi kod kerak bo\'ladi. (Bu telefonni boks tomonida bekor qilish uchun uni u yerdagi ishonchli qurilmalardan o\'chiring.)';

  @override
  String get settingsTitle => 'Sozlamalar';

  @override
  String get themeSection => 'Mavzu';

  @override
  String get themeSystem => 'Tizim bo\'yicha';

  @override
  String get themeLight => 'Yorug\'';

  @override
  String get themeDark => 'Qorong\'i';

  @override
  String get languageSection => 'Til';

  @override
  String get langSystem => 'Tizim tili';

  @override
  String get notifSection => 'Bildirishnoma sozlamalari';

  @override
  String get notifEnabled => 'Ilova ichidagi ogohlantirishlar';

  @override
  String get notifEnabledHint =>
      'Yangi bildirishnomalarni banner va belgi bilan ajratish.';

  @override
  String get sensitivityLabel => 'Sezgirlik';

  @override
  String get sensitivityHint =>
      'Ogohlantirish uchun minimal daraja. Pastroq = ko\'proq ogohlantirish.';

  @override
  String get quietHoursLabel => 'Tinch soatlar';

  @override
  String get quietHoursHint =>
      'Bu davrda kritik bo\'lmagan ogohlantirishlarni pasaytirish.';

  @override
  String get quietFrom => 'Boshlanishi';

  @override
  String get quietTo => 'Tugashi';

  @override
  String get criticalAlwaysAlerts =>
      'Kritik ogohlantirishlar doim yetib boradi — tinch soatlar favqulodda holatni o\'chirmaydi.';

  @override
  String get aboutSection => 'Ilova haqida';

  @override
  String get privacyNote =>
      'Video hech qachon boksdan chiqmaydi. Ilova faqat metama\'lumot oladi.';

  @override
  String get retry => 'Qayta urinish';

  @override
  String get cancel => 'Bekor qilish';

  @override
  String get ok => 'OK';

  @override
  String get close => 'Yopish';
}
