import 'dart:async';

import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/application/device_api.dart';
import 'package:safekids_mobile/src/application/notification_cache.dart';

NotificationMessage makeMessage({
  String id = 'n-1',
  String incidentId = 'i-1',
  String severity = 'critical',
  String status = 'pending_review',
  DateTime? timestamp,
}) {
  return NotificationMessage.fromJson({
    'notification_id': id,
    'incident_id': incidentId,
    'camera_id': 'classroom-1',
    'track_id': 't-1',
    'track_display_id': 7,
    'correlation_id': 'c-1',
    'severity': severity,
    'confidence': 0.91,
    'incident_status': status,
    'timestamp':
        (timestamp ?? DateTime.utc(2026, 7, 5, 12, 0, 19)).toIso8601String(),
    'summary': '2 corroborating potential_fall candidate(s) on track #7',
    'event_count': 2,
  });
}

IncidentDetails makeDetails({
  String incidentId = 'i-1',
  String status = 'pending_review',
}) {
  return IncidentDetails.fromJson({
    'incident_id': incidentId,
    'camera_id': 'classroom-1',
    'track_id': 't-1',
    'track_display_id': 7,
    'severity': 'critical',
    'risk_confidence': 0.91,
    'status': status,
    'opened_at': '2026-07-05T12:00:07+00:00',
    'last_event_at': '2026-07-05T12:00:19+00:00',
    'correlation_id': 'c-1',
    'summary': 'summary',
    'events': [
      {
        'observed_at': '2026-07-05T12:00:07+00:00',
        'confidence': 0.7,
        'signals': [
          {'name': 'downward_velocity', 'score': 0.94, 'detail': '0.57 fh/s'},
        ],
      },
    ],
    'review': null,
  });
}

const testBox = PairedBox(
  host: '127.0.0.1',
  apiPort: 8787,
  wsPort: 8788,
  token: 'test-token',
  boxName: 'guardian-edge-box',
);

class InMemoryCache implements NotificationCache {
  final Map<String, NotificationMessage> notifications = {};
  final Set<String> readIds = {};
  int cursor = 0;
  PairedBox? box;

  @override
  Future<void> saveNotification(NotificationMessage message) async {
    notifications[message.notificationId] = message;
  }

  @override
  Future<List<NotificationMessage>> loadNotifications() async =>
      notifications.values.toList();

  @override
  Future<void> saveCursor(int value) async => cursor = value;

  @override
  Future<int> loadCursor() async => cursor;

  @override
  Future<void> savePairedBox(PairedBox value) async => box = value;

  @override
  Future<PairedBox?> loadPairedBox() async => box;

  @override
  Future<void> markRead(String notificationId) async =>
      readIds.add(notificationId);

  @override
  Future<Set<String>> loadReadIds() async => {...readIds};
}

/// Scriptable device API: the test controls connectivity and streams.
class FakeDeviceApi implements DeviceApi {
  bool failPair = false;
  bool failSync = false;
  int syncCursor = 0;
  List<NotificationMessage> missed = [];
  final List<String> resolved = [];
  IncidentDetails? incidentDetails;
  StreamController<NotificationMessage>? live;
  int connectCount = 0;

  @override
  Future<PairedBox> pair({
    required String host,
    required int apiPort,
    required String code,
    required String deviceName,
  }) async {
    if (failPair) {
      throw Exception('invalid pairing code');
    }
    return testBox;
  }

  @override
  Future<SyncResult> fetchMissed(PairedBox box, int afterCursor) async {
    if (failSync) {
      throw Exception('box unreachable');
    }
    final fresh = missed;
    missed = [];
    return SyncResult(cursor: syncCursor, notifications: fresh);
  }

  @override
  Future<IncidentDetails> fetchIncident(
      PairedBox box, String incidentId) async {
    final details = incidentDetails;
    if (details == null) {
      throw Exception('incident is not open on this box');
    }
    return details;
  }

  @override
  Future<IncidentDetails> resolveIncident(
    PairedBox box,
    String incidentId, {
    required bool confirm,
    String note = '',
  }) async {
    resolved.add('$incidentId:${confirm ? 'confirm' : 'dismiss'}');
    return makeDetails(
      incidentId: incidentId,
      status: confirm ? 'confirmed' : 'dismissed',
    );
  }

  @override
  Stream<NotificationMessage> connect(PairedBox box) {
    connectCount += 1;
    live = StreamController<NotificationMessage>();
    return live!.stream;
  }
}

Future<void> pump() => Future<void>.delayed(const Duration(milliseconds: 20));
