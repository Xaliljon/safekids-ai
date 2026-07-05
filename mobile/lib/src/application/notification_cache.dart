import 'package:guardian_core/guardian_core.dart';

/// Local persistence the app relies on when the Wi-Fi is gone.
///
/// Notifications, the sync cursor, read state, and the trusted box all
/// survive restarts — nothing is ever lost to a disconnect (offline-first).
abstract class NotificationCache {
  Future<void> saveNotification(NotificationMessage message);
  Future<List<NotificationMessage>> loadNotifications();

  Future<void> saveCursor(int cursor);
  Future<int> loadCursor();

  Future<void> savePairedBox(PairedBox box);
  Future<PairedBox?> loadPairedBox();

  Future<void> markRead(String notificationId);
  Future<Set<String>> loadReadIds();
}
