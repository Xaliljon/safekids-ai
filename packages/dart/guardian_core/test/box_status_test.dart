import 'package:guardian_core/guardian_core.dart';
import 'package:test/test.dart';

Map<String, dynamic> healthWire() => {
      'status': 'ok',
      'version': '0.2.0',
      'components': {
        'cameras': {
          'status': 'ok',
          'cameras': {'room-1': 'healthy', 'room-2': 'unhealthy'},
          'fps': {'room-1': 6.1, 'room-2': 0},
        },
        'inference': {
          'status': 'ok',
          'cameras': {
            'room-1': {
              'fps': 6.1,
              'processed': 100,
              'dropped': 2,
              'detector_errors': 0,
              'tracker_errors': 1,
            },
          },
        },
        'tracking': {'status': 'ok', 'last_latency_ms': 0.3},
      },
      'host': {
        'cpu_percent': 25.5,
        'memory_percent': 40.0,
        'memory_used_mb': 3200,
        'disk_percent': 18.0,
        'disk_free_gb': 200.0,
        'temperature_c': null,
        'uptime_seconds': 3600.0,
      },
      'warnings': {'vision': 'keeps failing'},
    };

void main() {
  group('BoxHealth', () {
    final fetched = DateTime.utc(2026, 7, 6, 12, 0);

    test('parses status, subsystems, host and warnings', () {
      final health = BoxHealth.fromJson(healthWire(), fetchedAt: fetched);
      expect(health.status, BoxStatus.ok);
      expect(health.version, '0.2.0');
      expect(health.subsystems.map((s) => s.name),
          containsAll(['cameras', 'inference', 'tracking']));
      expect(health.host.cpuPercent, 25.5);
      expect(health.host.temperatureC, isNull);
      expect(health.warnings, {'vision': 'keeps failing'});
      expect(health.fetchedAt, fetched);
    });

    test('merges camera status with pipeline counters by id', () {
      final health = BoxHealth.fromJson(healthWire(), fetchedAt: fetched);
      expect(health.cameras, hasLength(2));
      final room1 = health.cameras.singleWhere((c) => c.cameraId == 'room-1');
      expect(room1.isHealthy, isTrue);
      expect(room1.fps, 6.1);
      expect(room1.framesProcessed, 100);
      expect(room1.trackerErrors, 1);
      final room2 = health.cameras.singleWhere((c) => c.cameraId == 'room-2');
      expect(room2.isHealthy, isFalse);
      expect(room2.framesProcessed, isNull,
          reason: 'no pipeline counters reported for a dead camera');
    });

    test('tolerates missing and unknown fields', () {
      final health = BoxHealth.fromJson({}, fetchedAt: fetched);
      expect(health.status, BoxStatus.unknown);
      expect(health.cameras, isEmpty);
      expect(health.subsystems, isEmpty);
      expect(health.host.cpuPercent, isNull);

      expect(BoxStatus.fromWire('weird'), BoxStatus.unknown);
    });

    test('round-trips host metrics through json', () {
      final host =
          HostMetrics.fromJson(healthWire()['host'] as Map<String, dynamic>);
      final restored = HostMetrics.fromJson(host.toJson());
      expect(restored.memoryUsedMb, 3200);
      expect(restored.diskFreeGb, 200.0);
    });
  });

  group('BoxMetrics', () {
    test('parses gauges next to host metrics', () {
      final metrics = BoxMetrics.fromJson({
        'cpu_percent': 20.0,
        'inference_fps': 12.5,
        'tracking_latency_ms': 0.4,
        'notification_mean_delivery_ms': 15.0,
      });
      expect(metrics.host.cpuPercent, 20.0);
      expect(metrics.inferenceFps, 12.5);
      expect(metrics.trackingLatencyMs, 0.4);
      expect(metrics.notificationMeanDeliveryMs, 15.0);
    });
  });
}
