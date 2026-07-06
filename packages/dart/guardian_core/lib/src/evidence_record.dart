/// Evidence record from the box's Device API (ADR-0017 wire format).
///
/// Metadata only — media (video/thumbnail) is fetched separately through
/// the authenticated evidence endpoints and never leaves the app.
library;

/// Lifecycle of an evidence record on the box.
enum EvidenceStatus {
  pending,
  recording,
  ready,
  failed,
  expired,
  deleted;

  static EvidenceStatus fromWire(String value) =>
      EvidenceStatus.values.asNameMap()[value] ?? EvidenceStatus.failed;
}

/// One evidence record attached to a safety incident.
class EvidenceRecord {
  const EvidenceRecord({
    required this.evidenceId,
    required this.incidentId,
    required this.evidenceType,
    required this.status,
    required this.cameraId,
    required this.correlationId,
    required this.createdAt,
    required this.variants,
    required this.hasThumbnail,
    this.durationSeconds,
    this.fps,
    this.width,
    this.height,
    this.sizeBytes,
    this.error,
  });

  final String evidenceId;
  final String incidentId;
  final String evidenceType; // 'video_clip' today; more types will come
  final EvidenceStatus status;
  final String cameraId;
  final String correlationId;
  final DateTime createdAt;

  /// Available clip variants: 'original' and/or 'overlay'.
  final List<String> variants;
  final bool hasThumbnail;
  final double? durationSeconds;
  final double? fps;
  final int? width;
  final int? height;
  final int? sizeBytes;
  final String? error;

  bool get playable => status == EvidenceStatus.ready && variants.isNotEmpty;

  factory EvidenceRecord.fromJson(Map<String, dynamic> json) {
    final metadata = json['metadata'] as Map<String, dynamic>?;
    final clips =
        (json['clips'] as List<dynamic>? ?? []).cast<Map<String, dynamic>>();
    var totalBytes = 0;
    for (final clip in clips) {
      totalBytes += (clip['size_bytes'] as num?)?.toInt() ?? 0;
    }
    return EvidenceRecord(
      evidenceId: json['evidence_id'] as String,
      incidentId: json['incident_id'] as String,
      evidenceType: json['evidence_type'] as String,
      status: EvidenceStatus.fromWire(json['status'] as String),
      cameraId: json['camera_id'] as String,
      correlationId: json['correlation_id'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      variants: [for (final clip in clips) clip['variant'] as String],
      hasThumbnail: json['thumbnail_file'] != null,
      durationSeconds: (metadata?['duration_seconds'] as num?)?.toDouble(),
      fps: (metadata?['fps'] as num?)?.toDouble(),
      width: (metadata?['width'] as num?)?.toInt(),
      height: (metadata?['height'] as num?)?.toInt(),
      sizeBytes: clips.isEmpty ? null : totalBytes,
      error: json['error'] as String?,
    );
  }

  Map<String, dynamic> toJson() => {
        'evidence_id': evidenceId,
        'incident_id': incidentId,
        'evidence_type': evidenceType,
        'status': status.name,
        'camera_id': cameraId,
        'correlation_id': correlationId,
        'created_at': createdAt.toIso8601String(),
        'clips': [
          for (final variant in variants)
            {
              'variant': variant,
              'file_name': '',
              'size_bytes': 0,
              'sha256': ''
            },
        ],
        'thumbnail_file': hasThumbnail ? 'thumbnail.jpg.enc' : null,
        'metadata': durationSeconds == null
            ? null
            : {
                'duration_seconds': durationSeconds,
                'fps': fps ?? 0,
                'width': width ?? 0,
                'height': height ?? 0,
                'frame_count': 0,
                'pre_seconds': 0,
                'post_seconds': 0,
              },
        'error': error,
      };
}
