import 'package:guardian_core/guardian_core.dart';
import 'package:test/test.dart';

Map<String, dynamic> wire({String status = 'ready'}) => {
      'evidence_version': 1,
      'evidence_id': 'e-1',
      'evidence_type': 'video_clip',
      'status': status,
      'incident_id': 'i-1',
      'camera_id': 'room-1',
      'track_id': 't-1',
      'detection_id': 'd-1',
      'frame_id': 'f-1',
      'correlation_id': 'c-1',
      'incident_severity': 'high',
      'incident_status': 'pending_review',
      'incident_opened_at': '2026-07-06T12:00:00+00:00',
      'created_at': '2026-07-06T12:00:30+00:00',
      'metadata': {
        'duration_seconds': 30.0,
        'fps': 10.0,
        'width': 768,
        'height': 576,
        'frame_count': 300,
        'pre_seconds': 15.0,
        'post_seconds': 15.0,
      },
      'clips': [
        {
          'variant': 'original',
          'file_name': 'clip.mp4.enc',
          'size_bytes': 1000,
          'sha256': 'aa'
        },
        {
          'variant': 'overlay',
          'file_name': 'clip-overlay.mp4.enc',
          'size_bytes': 1200,
          'sha256': 'bb'
        },
      ],
      'thumbnail_file': 'thumbnail.jpg.enc',
      'error': null,
    };

void main() {
  group('EvidenceRecord', () {
    test('parses the box wire format', () {
      final record = EvidenceRecord.fromJson(wire());
      expect(record.evidenceId, 'e-1');
      expect(record.incidentId, 'i-1');
      expect(record.status, EvidenceStatus.ready);
      expect(record.playable, isTrue);
      expect(record.variants, ['original', 'overlay']);
      expect(record.hasThumbnail, isTrue);
      expect(record.durationSeconds, 30.0);
      expect(record.sizeBytes, 2200);
    });

    test('pending/failed records are not playable', () {
      final pending = EvidenceRecord.fromJson(
          wire(status: 'pending')..['clips'] = <dynamic>[]);
      expect(pending.status, EvidenceStatus.pending);
      expect(pending.playable, isFalse);
      final failed = EvidenceRecord.fromJson(
          wire(status: 'failed')..['clips'] = <dynamic>[]);
      expect(failed.playable, isFalse);
    });

    test('tolerates missing metadata and unknown status', () {
      final raw = wire()
        ..['metadata'] = null
        ..['status'] = 'brand-new-state';
      final record = EvidenceRecord.fromJson(raw);
      expect(record.durationSeconds, isNull);
      expect(record.status, EvidenceStatus.failed, reason: 'safe fallback');
    });
  });
}
