import 'package:guardian_core/guardian_core.dart';

/// Local persistence the app relies on when the Wi-Fi is gone.
///
/// Notifications, the sync cursor, read/archive state, settings, the last
/// health snapshot and the trusted box all survive restarts — nothing is
/// ever lost to a disconnect (offline-first, ADR-0015).
abstract class NotificationCache {
  Future<void> saveNotification(NotificationMessage message);
  Future<List<NotificationMessage>> loadNotifications();

  Future<void> saveCursor(int cursor);
  Future<int> loadCursor();

  Future<void> savePairedBox(PairedBox box);
  Future<PairedBox?> loadPairedBox();
  Future<void> clearPairedBox();

  Future<void> markRead(String notificationId);
  Future<Set<String>> loadReadIds();

  Future<void> setArchived(String notificationId, bool archived);
  Future<Set<String>> loadArchivedIds();

  Future<void> saveSettings(String json);
  Future<String?> loadSettings();

  Future<void> saveHealthSnapshot(String json);
  Future<String?> loadHealthSnapshot();
}
