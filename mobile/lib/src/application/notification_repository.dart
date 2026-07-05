import 'package:flutter/foundation.dart';
import 'package:guardian_core/guardian_core.dart';

import 'notification_cache.dart';

/// One row of the notification center.
class NotificationItem {
  const NotificationItem({required this.message, required this.read});

  final NotificationMessage message;
  final bool read;
}

/// In-memory state over the offline cache: the single source the UI reads.
///
/// Every mutation persists to the cache first — a crash or disconnect never
/// loses a notification. Incident status only changes from box responses;
/// the app never invents state locally.
class NotificationRepository extends ChangeNotifier {
  NotificationRepository(this._cache);

  final NotificationCache _cache;
  final Map<String, NotificationMessage> _byId = {};
  Set<String> _readIds = {};
  int _cursor = 0;

  int get cursor => _cursor;

  List<NotificationItem> get items {
    final list = _byId.values.toList()
      ..sort((a, b) => b.timestamp.compareTo(a.timestamp)); // newest first
    return [
      for (final message in list)
        NotificationItem(
            message: message, read: _readIds.contains(message.notificationId)),
    ];
  }

  int get unreadCount =>
      _byId.keys.where((id) => !_readIds.contains(id)).length;

  NotificationMessage? byNotificationId(String id) => _byId[id];

  Future<void> initialize() async {
    for (final message in await _cache.loadNotifications()) {
      _byId[message.notificationId] = message;
    }
    _readIds = await _cache.loadReadIds();
    _cursor = await _cache.loadCursor();
    notifyListeners();
  }

  /// A live notification from the WebSocket (advances the cursor by one
  /// outbox line, which is exactly what the box appended).
  Future<void> addLive(NotificationMessage message) async {
    await _cache.saveNotification(message);
    _cursor += 1;
    await _cache.saveCursor(_cursor);
    _byId[message.notificationId] = message;
    notifyListeners();
  }

  /// Catch-up after reconnect: everything missed while offline.
  Future<void> applySync(int cursor, List<NotificationMessage> missed) async {
    for (final message in missed) {
      await _cache.saveNotification(message);
      _byId[message.notificationId] = message;
    }
    _cursor = cursor;
    await _cache.saveCursor(cursor);
    notifyListeners();
  }

  Future<void> markRead(String notificationId) async {
    if (_readIds.contains(notificationId)) {
      return;
    }
    await _cache.markRead(notificationId);
    _readIds = {..._readIds, notificationId};
    notifyListeners();
  }

  /// Reflect a box-recorded resolution across every notification of that
  /// incident (the box is the source of truth).
  Future<void> applyResolution(String incidentId, IncidentStatus status) async {
    var changed = false;
    for (final entry in _byId.entries.toList()) {
      if (entry.value.incidentId == incidentId &&
          entry.value.incidentStatus != status) {
        final updated = entry.value.withIncidentStatus(status);
        _byId[entry.key] = updated;
        await _cache.saveNotification(updated);
        changed = true;
      }
    }
    if (changed) {
      notifyListeners();
    }
  }
}
