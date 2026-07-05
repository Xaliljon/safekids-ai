import 'dart:convert';

import 'package:guardian_core/guardian_core.dart';
import 'package:hive/hive.dart';

import '../application/notification_cache.dart';

/// Hive-backed offline cache (CLAUDE.md local-storage mandate, ADR-0015).
///
/// Stores plain JSON strings — no code generation, no schema migration
/// while the model is young. Boxes: notifications (id -> json), meta
/// (cursor, paired box, read/archived ids, settings, health snapshot).
class HiveNotificationCache implements NotificationCache {
  HiveNotificationCache._(this._notifications, this._meta);

  static const notificationsBoxName = 'notifications';
  static const metaBoxName = 'meta';

  final Box<String> _notifications;
  final Box<String> _meta;

  static Future<HiveNotificationCache> open() async {
    final notifications = await Hive.openBox<String>(notificationsBoxName);
    final meta = await Hive.openBox<String>(metaBoxName);
    return HiveNotificationCache._(notifications, meta);
  }

  @override
  Future<void> saveNotification(NotificationMessage message) =>
      _notifications.put(message.notificationId, jsonEncode(message.toJson()));

  @override
  Future<List<NotificationMessage>> loadNotifications() async => [
        for (final raw in _notifications.values)
          NotificationMessage.fromJson(jsonDecode(raw) as Map<String, dynamic>),
      ];

  @override
  Future<void> saveCursor(int cursor) => _meta.put('cursor', '$cursor');

  @override
  Future<int> loadCursor() async =>
      int.tryParse(_meta.get('cursor') ?? '0') ?? 0;

  @override
  Future<void> savePairedBox(PairedBox box) =>
      _meta.put('paired_box', jsonEncode(box.toJson()));

  @override
  Future<PairedBox?> loadPairedBox() async {
    final raw = _meta.get('paired_box');
    if (raw == null) {
      return null;
    }
    return PairedBox.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  @override
  Future<void> clearPairedBox() => _meta.delete('paired_box');

  @override
  Future<void> markRead(String notificationId) =>
      _addToIdSet('read_ids', notificationId);

  @override
  Future<Set<String>> loadReadIds() async => _loadIdSet('read_ids');

  @override
  Future<void> setArchived(String notificationId, bool archived) async {
    if (archived) {
      await _addToIdSet('archived_ids', notificationId);
    } else {
      final ids = _loadIdSet('archived_ids')..remove(notificationId);
      await _meta.put('archived_ids', jsonEncode(ids.toList()));
    }
  }

  @override
  Future<Set<String>> loadArchivedIds() async => _loadIdSet('archived_ids');

  @override
  Future<void> saveSettings(String json) => _meta.put('settings', json);

  @override
  Future<String?> loadSettings() async => _meta.get('settings');

  @override
  Future<void> saveHealthSnapshot(String json) =>
      _meta.put('health_snapshot', json);

  @override
  Future<String?> loadHealthSnapshot() async => _meta.get('health_snapshot');

  Future<void> _addToIdSet(String key, String id) async {
    final ids = _loadIdSet(key)..add(id);
    await _meta.put(key, jsonEncode(ids.toList()));
  }

  Set<String> _loadIdSet(String key) {
    final raw = _meta.get(key);
    if (raw == null) {
      return <String>{};
    }
    return {for (final id in jsonDecode(raw) as List<dynamic>) id as String};
  }
}
