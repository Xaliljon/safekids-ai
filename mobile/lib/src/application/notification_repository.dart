import 'package:flutter/foundation.dart';
import 'package:guardian_core/guardian_core.dart';

import 'notification_cache.dart';

/// One row of the notification center.
class NotificationItem {
  const NotificationItem({
    required this.message,
    required this.read,
    required this.archived,
  });

  final NotificationMessage message;
  final bool read;
  final bool archived;
}

/// Which shelf of the notification center is showing.
enum AlertsTab { unread, read, archived }

/// The director's current query over the notification list.
@immutable
class AlertFilter {
  const AlertFilter({
    this.tab = AlertsTab.unread,
    this.query = '',
    this.severities = const {},
    this.cameraId,
  });

  final AlertsTab tab;
  final String query;

  /// Empty set = all severities.
  final Set<Severity> severities;

  /// null = all cameras.
  final String? cameraId;

  AlertFilter copyWith({
    AlertsTab? tab,
    String? query,
    Set<Severity>? severities,
    String? Function()? cameraId,
  }) =>
      AlertFilter(
        tab: tab ?? this.tab,
        query: query ?? this.query,
        severities: severities ?? this.severities,
        cameraId: cameraId == null ? this.cameraId : cameraId(),
      );

  bool matches(NotificationItem item) {
    final onTab = switch (tab) {
      AlertsTab.unread => !item.read && !item.archived,
      AlertsTab.read => item.read && !item.archived,
      AlertsTab.archived => item.archived,
    };
    if (!onTab) {
      return false;
    }
    if (severities.isNotEmpty && !severities.contains(item.message.severity)) {
      return false;
    }
    if (cameraId != null && item.message.cameraId != cameraId) {
      return false;
    }
    if (query.isNotEmpty) {
      final haystack = '${item.message.summary} ${item.message.cameraId} '
              'track #${item.message.trackDisplayId} '
              '${item.message.severity.wire}'
          .toLowerCase();
      if (!haystack.contains(query.toLowerCase())) {
        return false;
      }
    }
    return true;
  }
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
  Set<String> _archivedIds = {};
  int _cursor = 0;

  /// Set when a live notification arrives; the UI decides how loudly to
  /// surface it, based on settings (sensitivity/quiet hours). Cleared by
  /// the UI after showing.
  NotificationMessage? lastLive;

  int get cursor => _cursor;

  List<NotificationItem> get items {
    final list = _byId.values.toList()
      ..sort((a, b) => b.timestamp.compareTo(a.timestamp)); // newest first
    return [
      for (final message in list)
        NotificationItem(
          message: message,
          read: _readIds.contains(message.notificationId),
          archived: _archivedIds.contains(message.notificationId),
        ),
    ];
  }

  /// One page of the filtered list (pagination for long pilot histories).
  List<NotificationItem> page(AlertFilter filter,
      {int offset = 0, int limit = 50}) {
    return items.where(filter.matches).skip(offset).take(limit).toList();
  }

  /// Total matches for a filter (drives "load more" visibility and badges).
  int count(AlertFilter filter) => items.where(filter.matches).length;

  int get unreadCount => count(const AlertFilter(tab: AlertsTab.unread));

  /// Camera ids present in the history — the filter chips' vocabulary.
  List<String> get cameraIds {
    final ids = {for (final message in _byId.values) message.cameraId}.toList()
      ..sort();
    return ids;
  }

  NotificationMessage? byNotificationId(String id) => _byId[id];

  /// All notifications of one incident, oldest first (track history view).
  List<NotificationMessage> byIncidentId(String incidentId) {
    final list = _byId.values
        .where((message) => message.incidentId == incidentId)
        .toList()
      ..sort((a, b) => a.timestamp.compareTo(b.timestamp));
    return list;
  }

  Future<void> initialize() async {
    for (final message in await _cache.loadNotifications()) {
      _byId[message.notificationId] = message;
    }
    _readIds = await _cache.loadReadIds();
    _archivedIds = await _cache.loadArchivedIds();
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
    lastLive = message;
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

  Future<void> markAllRead() async {
    for (final id in _byId.keys) {
      if (!_readIds.contains(id)) {
        await _cache.markRead(id);
        _readIds = {..._readIds, id};
      }
    }
    notifyListeners();
  }

  Future<void> setArchived(String notificationId, bool archived) async {
    await _cache.setArchived(notificationId, archived);
    _archivedIds = archived
        ? {..._archivedIds, notificationId}
        : ({..._archivedIds}..remove(notificationId));
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
