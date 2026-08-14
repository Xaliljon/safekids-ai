import 'package:guardian_core/guardian_core.dart';
import 'package:test/test.dart';

Map<String, dynamic> samplePayload({String severity = 'critical'}) => {
      'notification_id': 'n-1',
      'incident_id': 'i-1',
      'camera_id': 'classroom-1',
      'track_id': 't-1',
      'track_display_id': 7,
      'correlation_id': 'c-1',
      'type': 'safety_incident',
      'incident_type': 'potential_fall',
      'severity': severity,
      'confidence': 0.91,
      'incident_status': 'pending_review',
      'timestamp': '2026-07-05T12:00:19+00:00',
      'created_at': '2026-07-05T12:00:19+00:00',
      'summary': '2 corroborating potential_fall candidate(s) on track #7',
      'event_count': 2,
      'priority': 'immediate',
    };

void main() {
  test('package declares a version', () {
    expect(guardianCoreVersion, isNotEmpty);
  });

  group('NotificationMessage', () {
    test('parses the device API payload strictly', () {
      final message = NotificationMessage.fromJson(samplePayload());
      expect(message.severity, Severity.critical);
      expect(message.incidentStatus, IncidentStatus.pendingReview);
      expect(message.confidence, closeTo(0.91, 1e-9));
      expect(message.trackDisplayId, 7);
      expect(message.timestamp.isUtc, isTrue);
    });

    test('round-trips through json for the local cache', () {
      final message = NotificationMessage.fromJson(samplePayload());
      final restored = NotificationMessage.fromJson(message.toJson());
      expect(restored.notificationId, message.notificationId);
      expect(restored.severity, message.severity);
      expect(restored.summary, message.summary);
    });

    test('carries the kind of event, never assumes it', () {
      final message = NotificationMessage.fromJson(samplePayload());
      expect(message.incidentType, IncidentType.potentialFall);
      expect(
        NotificationMessage.fromJson(message.toJson()).incidentType,
        IncidentType.potentialFall,
        reason: 'the cached copy must not lose what kind of event it was',
      );
    });

    test('a payload without an event kind degrades, it does not guess', () {
      // A box older than this field, or a cache entry written before it.
      final payload = samplePayload()..remove('incident_type');
      expect(
        NotificationMessage.fromJson(payload).incidentType,
        IncidentType.unknown,
        reason: 'silence about the type is not evidence of a fall',
      );
    });

    test('unknown severity fails loudly, never silently', () {
      expect(
        () => NotificationMessage.fromJson(
            samplePayload(severity: 'apocalyptic')),
        throwsFormatException,
      );
    });

    test('withIncidentStatus replaces only the status', () {
      final message = NotificationMessage.fromJson(samplePayload());
      final confirmed = message.withIncidentStatus(IncidentStatus.confirmed);
      expect(confirmed.incidentStatus, IncidentStatus.confirmed);
      expect(confirmed.notificationId, message.notificationId);
      expect(confirmed.severity, message.severity);
    });
  });

  group('IncidentDetails', () {
    test('parses details with an event timeline', () {
      final details = IncidentDetails.fromJson({
        'incident_id': 'i-1',
        'type': 'potential_fall',
        'camera_id': 'classroom-1',
        'track_id': 't-1',
        'track_display_id': 7,
        'severity': 'medium',
        'risk_confidence': 0.7,
        'status': 'pending_review',
        'opened_at': '2026-07-05T12:00:07+00:00',
        'last_event_at': '2026-07-05T12:00:19+00:00',
        'correlation_id': 'c-1',
        'summary': 'summary',
        'events': [
          {
            'observed_at': '2026-07-05T12:00:07+00:00',
            'confidence': 0.7,
            'signals': [
              {
                'name': 'downward_velocity',
                'score': 0.94,
                'detail': '0.57 fh/s'
              },
            ],
          },
        ],
        'review': null,
      });
      expect(details.incidentType, IncidentType.potentialFall);
      expect(details.events, hasLength(1));
      expect(details.events.first.signals.first.name, 'downward_velocity');
      expect(details.reviewer, isNull);
    });
  });

  group('IncidentType', () {
    test('parses the vocabulary the edge domain publishes', () {
      expect(
          IncidentType.fromWire('potential_fall'), IncidentType.potentialFall);
      expect(IncidentType.potentialFall.wire, 'potential_fall');
    });

    test('an unknown or missing type never becomes a known one', () {
      // Deliberately lenient (see IncidentType): a box updated ahead of the
      // phones must not have its alerts thrown away — but it must not have
      // them mislabelled either.
      for (final wire in <Object?>[
        'zone_exit',
        'continuous_cry',
        '',
        null,
        7
      ]) {
        expect(IncidentType.fromWire(wire), IncidentType.unknown,
            reason: 'unrecognized wire value: $wire');
      }
    });
  });

  group('PairedBox', () {
    test('builds api and ws uris and round-trips json', () {
      const box = PairedBox(
        host: '192.168.1.50',
        apiPort: 8787,
        wsPort: 8788,
        token: 'secret-token',
        boxName: 'guardian-edge-box',
      );
      expect(box.apiBase.toString(), 'http://192.168.1.50:8787');
      expect(
          box.wsUri.toString(), 'ws://192.168.1.50:8788/ws?token=secret-token');
      final restored = PairedBox.fromJson(box.toJson());
      expect(restored.token, box.token);
      expect(restored.boxName, box.boxName);
    });
  });
}
