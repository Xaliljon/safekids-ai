import 'dart:async';

import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/application/box_status_api.dart';
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
  final Set<String> archivedIds = {};
  String? settingsJson;
  String? healthJson;
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

  @override
  Future<void> clearPairedBox() async => box = null;

  @override
  Future<void> setArchived(String notificationId, bool archived) async =>
      archived
          ? archivedIds.add(notificationId)
          : archivedIds.remove(notificationId);

  @override
  Future<Set<String>> loadArchivedIds() async => {...archivedIds};

  @override
  Future<void> saveSettings(String json) async => settingsJson = json;

  @override
  Future<String?> loadSettings() async => settingsJson;

  @override
  Future<void> saveHealthSnapshot(String json) async => healthJson = json;

  @override
  Future<String?> loadHealthSnapshot() async => healthJson;
}

/// A realistic `/health` payload (mirrors the Sprint 14 ops wire format).
Map<String, dynamic> makeHealthJson({
  String status = 'ok',
  String cameraStatus = 'healthy',
  double? cpu = 27.5,
  Map<String, String> warnings = const {},
}) {
  return {
    'status': status,
    'version': '0.2.0',
    'components': {
      'cameras': {
        'status': status == 'ok' ? 'ok' : status,
        'cameras': {'classroom-1': cameraStatus},
        'fps': {'classroom-1': 6.0},
      },
      'inference': {
        'status': 'ok',
        'cameras': {
          'classroom-1': {
            'fps': 6.0,
            'processed': 1200,
            'dropped': 3,
            'detector_errors': 0,
            'tracker_errors': 0,
          },
        },
      },
      'tracking': {'status': 'ok', 'last_latency_ms': 0.4},
      'risk': {'status': 'ok', 'open_incidents': 0},
      'notifications': {'status': 'ok', 'delivered': 12, 'queue': 0},
    },
    'host': {
      'cpu_percent': cpu,
      'memory_percent': 41.0,
      'memory_used_mb': 3277,
      'disk_percent': 18.2,
      'disk_free_gb': 210.5,
      'temperature_c': 52.0,
      'uptime_seconds': 90061.0,
    },
    'warnings': warnings,
  };
}

/// Scriptable health-surface API for dashboard/cameras/health screens.
class FakeBoxStatusApi implements BoxStatusApi {
  FakeBoxStatusApi({DateTime Function()? clock})
      : clock = clock ?? DateTime.now;

  final DateTime Function() clock;
  Map<String, dynamic> healthJson = makeHealthJson();
  bool failHealth = false;
  bool failMetrics = false;
  Object restartBehavior = const UnsupportedByBoxError('restartCamera');
  final List<String> restarted = [];

  @override
  Future<BoxHealth> fetchHealth(String host, {int port = 8790}) async {
    if (failHealth) {
      throw Exception('box unreachable');
    }
    return BoxHealth.fromJson(healthJson, fetchedAt: clock());
  }

  @override
  Future<BoxMetrics> fetchMetrics(String host, {int port = 8790}) async {
    if (failMetrics) {
      throw Exception('metrics unreachable');
    }
    return BoxMetrics.fromJson({
      ...healthJson['host'] as Map<String, dynamic>,
      'inference_fps': 6.0,
      'tracking_latency_ms': 0.4,
      'notification_mean_delivery_ms': 12.0,
    });
  }

  @override
  Future<void> restartCamera(PairedBox box, String cameraId) async {
    restarted.add(cameraId);
    final behavior = restartBehavior;
    if (behavior is Exception) {
      throw behavior;
    }
  }
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
