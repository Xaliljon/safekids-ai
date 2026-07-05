// ignore: unused_import
import 'package:intl/intl.dart' as intl;
import 'app_localizations.dart';

// ignore_for_file: type=lint

/// The translations for Russian (`ru`).
class AppLocalizationsRu extends AppLocalizations {
  AppLocalizationsRu([String locale = 'ru']) : super(locale);

  @override
  String get appTitle => 'Guardian SafeKids';

  @override
  String get navDashboard => 'Панель';

  @override
  String get navAlerts => 'Уведомления';

  @override
  String get navCameras => 'Камеры';

  @override
  String get navHealth => 'Система';

  @override
  String get navSettings => 'Настройки';

  @override
  String get connConnected => 'Подключено';

  @override
  String get connConnecting => 'Подключение…';

  @override
  String get connOffline => 'Офлайн';

  @override
  String get connUnpaired => 'Не сопряжено';

  @override
  String get offlineBanner =>
      'Офлайн — показаны сохранённые данные, переподключение…';

  @override
  String get dashSystemStatus => 'Состояние системы';

  @override
  String get statusOk => 'Все системы в норме';

  @override
  String get statusDegraded => 'Сниженная работа';

  @override
  String get statusWarning => 'Требует внимания';

  @override
  String get statusError => 'Обнаружена проблема';

  @override
  String get statusUnknown => 'Неизвестно';

  @override
  String get dashConnectedCameras => 'Камеры';

  @override
  String dashCamerasOnline(int online, int total) {
    return '$online из $total онлайн';
  }

  @override
  String get dashRecentIncidents => 'Последние инциденты';

  @override
  String get dashNoIncidents => 'Инцидентов нет — всё спокойно.';

  @override
  String get dashCpu => 'ЦП';

  @override
  String get dashRam => 'ОЗУ';

  @override
  String get dashLastSync => 'Последняя синхронизация';

  @override
  String get dashNever => 'никогда';

  @override
  String get justNow => 'только что';

  @override
  String minutesAgo(int minutes) {
    return '$minutes мин назад';
  }

  @override
  String get dashViewAll => 'Показать все';

  @override
  String boxVersion(String version) {
    return 'Бокс v$version';
  }

  @override
  String get alertsTitle => 'Центр уведомлений';

  @override
  String get alertsSearchHint => 'Поиск (камера, трек, текст)';

  @override
  String get tabUnread => 'Новые';

  @override
  String get tabRead => 'Прочитанные';

  @override
  String get tabArchived => 'Архив';

  @override
  String get alertsEmpty => 'Здесь пусто — всё спокойно.';

  @override
  String get alertsNoMatches => 'Ничего не найдено по фильтрам.';

  @override
  String get loadMore => 'Показать ещё';

  @override
  String get archive => 'В архив';

  @override
  String get unarchive => 'Из архива';

  @override
  String get markAllRead => 'Прочитать все';

  @override
  String get allCameras => 'Все камеры';

  @override
  String get today => 'Сегодня';

  @override
  String get yesterday => 'Вчера';

  @override
  String get potentialFall => 'Возможное падение';

  @override
  String get severityLow => 'Низкая';

  @override
  String get severityMedium => 'Средняя';

  @override
  String get severityHigh => 'Высокая';

  @override
  String get severityCritical => 'Критическая';

  @override
  String get statusPendingReview => 'Ожидает проверки';

  @override
  String get statusConfirmed => 'Подтверждено';

  @override
  String get statusDismissed => 'Отклонено';

  @override
  String get incidentTitle => 'Инцидент';

  @override
  String get incidentTimeline => 'Хронология';

  @override
  String get incidentSignals => 'Сигналы';

  @override
  String get incidentEvidence => 'Доказательства';

  @override
  String get incidentReviewStatus => 'Статус проверки';

  @override
  String get incidentTrackHistory => 'История трека';

  @override
  String get confirmAction => 'Подтвердить';

  @override
  String get dismissAction => 'Отклонить';

  @override
  String get confirmQuestion =>
      'Подтвердить инцидент как реальное происшествие?';

  @override
  String get dismissQuestion => 'Отклонить инцидент как ложную тревогу?';

  @override
  String get reviewNoteHint => 'Заметка (необязательно)';

  @override
  String get decisionRecorded => 'Решение записано на боксе.';

  @override
  String get decisionFailed =>
      'Не удалось записать решение — проверьте соединение.';

  @override
  String get incidentUnavailableOffline =>
      'Бокс недоступен — показаны сохранённые данные уведомления.';

  @override
  String get evidenceMetadataOnly =>
      'Доказательства — только метаданные: изображения и видео никогда не покидают бокс. Люди отображаются номерами треков, без имён.';

  @override
  String trackNumber(int number) {
    return 'Трек №$number';
  }

  @override
  String get cameraLabel => 'Камера';

  @override
  String get openedAtLabel => 'Открыт';

  @override
  String get lastEventLabel => 'Последнее событие';

  @override
  String get confidenceLabel => 'Уверенность';

  @override
  String get riskConfidenceLabel => 'Оценка риска';

  @override
  String eventsCount(int count) {
    return 'Подтверждающих событий: $count';
  }

  @override
  String get reviewerLabel => 'Проверил';

  @override
  String get notificationsOfIncident => 'Уведомления этого инцидента';

  @override
  String get camerasTitle => 'Камеры';

  @override
  String get camerasEmpty => 'Камеры ещё не переданы — ждём бокс.';

  @override
  String get cameraHealthy => 'В норме';

  @override
  String get cameraDegraded => 'Сбоит';

  @override
  String get cameraUnhealthy => 'Не работает';

  @override
  String get cameraRecovering => 'Восстанавливается';

  @override
  String get cameraUnknown => 'Неизвестно';

  @override
  String get fpsLabel => 'Кадров/с';

  @override
  String get latencyLabel => 'Задержка';

  @override
  String get framesProcessed => 'Кадров обработано';

  @override
  String get framesDropped => 'Кадров пропущено';

  @override
  String get detectorErrors => 'Ошибки детектора';

  @override
  String get trackerErrors => 'Ошибки трекера';

  @override
  String get restartCamera => 'Перезапустить камеру';

  @override
  String get restartUnsupported =>
      'Эта версия бокса не поддерживает удалённый перезапуск — автоматическое восстановление само перезапускает камеры и переподключает потоки.';

  @override
  String get restartFailed =>
      'Не удалось отправить запрос — проверьте соединение.';

  @override
  String get restartRequested => 'Перезапуск запрошен.';

  @override
  String get healthTitle => 'Состояние системы';

  @override
  String get subsystemsSection => 'Подсистемы';

  @override
  String get hostSection => 'Хост Edge-бокса';

  @override
  String get cpuLabel => 'ЦП';

  @override
  String get ramLabel => 'ОЗУ';

  @override
  String get temperatureLabel => 'Температура';

  @override
  String get diskLabel => 'Диск';

  @override
  String get networkSection => 'Сеть';

  @override
  String get uptimeLabel => 'Время работы';

  @override
  String diskFreeGb(String gb) {
    return 'Свободно $gb ГБ';
  }

  @override
  String get boxUnreachable =>
      'Бокс недоступен — показан последний снимок состояния.';

  @override
  String get noHealthYet =>
      'Данных пока нет. Сопрягитесь с боксом и убедитесь, что он запущен.';

  @override
  String get boxAddressLabel => 'Адрес бокса';

  @override
  String get warningsSection => 'Предупреждения';

  @override
  String get notAvailable => 'н/д';

  @override
  String get pairTitle => 'Сопряжение с Guardian Box';

  @override
  String get pairIntro =>
      'Сопрягите телефон с Guardian Box в локальной сети. Ничего не покидает здание — без аккаунтов и облака.';

  @override
  String get pairScanQr => 'Сканировать QR-код';

  @override
  String get pairManualEntry => 'Ввести вручную';

  @override
  String get pairHostLabel => 'Адрес бокса (IP)';

  @override
  String get pairPortLabel => 'Порт';

  @override
  String get pairCodeLabel => 'Код сопряжения';

  @override
  String get pairDeviceNameLabel => 'Имя этого устройства';

  @override
  String get pairButton => 'Сопрячь';

  @override
  String get pairBusy => 'Сопряжение…';

  @override
  String get pairQrHint =>
      'Наведите камеру на QR-код из отчёта об установке или с плаката бокса.';

  @override
  String get pairQrInvalid => 'Это не QR-код сопряжения Guardian.';

  @override
  String get pairQrFilled =>
      'Данные бокса заполнены из QR — введите код сопряжения с экрана бокса.';

  @override
  String get trustedDevicesTitle => 'Доверенные устройства';

  @override
  String get trustedThisDevice => 'Это устройство';

  @override
  String get trustedBoxLabel => 'Сопряжённый бокс';

  @override
  String get forgetBox => 'Забыть этот бокс';

  @override
  String get forgetBoxQuestion =>
      'Забыть этот бокс? Для повторного подключения понадобится новый код. (Чтобы отозвать этот телефон на боксе, удалите его из доверенных устройств там.)';

  @override
  String get settingsTitle => 'Настройки';

  @override
  String get themeSection => 'Тема';

  @override
  String get themeSystem => 'Системная';

  @override
  String get themeLight => 'Светлая';

  @override
  String get themeDark => 'Тёмная';

  @override
  String get languageSection => 'Язык';

  @override
  String get langSystem => 'Язык системы';

  @override
  String get notifSection => 'Уведомления';

  @override
  String get notifEnabled => 'Оповещения в приложении';

  @override
  String get notifEnabledHint =>
      'Выделять новые уведомления баннером и значком.';

  @override
  String get sensitivityLabel => 'Чувствительность';

  @override
  String get sensitivityHint =>
      'Минимальная важность для оповещения. Ниже = больше оповещений.';

  @override
  String get quietHoursLabel => 'Тихие часы';

  @override
  String get quietHoursHint =>
      'Приглушать некритичные оповещения в этот период.';

  @override
  String get quietFrom => 'С';

  @override
  String get quietTo => 'До';

  @override
  String get criticalAlwaysAlerts =>
      'Критические оповещения приходят всегда — тихие часы не заглушают чрезвычайную ситуацию.';

  @override
  String get aboutSection => 'О приложении';

  @override
  String get privacyNote =>
      'Видео никогда не покидает бокс. Приложение получает только метаданные.';

  @override
  String get retry => 'Повторить';

  @override
  String get cancel => 'Отмена';

  @override
  String get ok => 'ОК';

  @override
  String get close => 'Закрыть';
}
