import 'incident_type.dart';
import 'severity.dart';

/// One notification payload from the Guardian Box (metadata only —
/// never images, video, or personal data; people appear as track numbers).
class NotificationMessage {
  const NotificationMessage({
    required this.notificationId,
    required this.incidentId,
    required this.incidentType,
    required this.cameraId,
    required this.trackId,
    required this.trackDisplayId,
    required this.correlationId,
    required this.severity,
    required this.confidence,
    required this.incidentStatus,
    required this.timestamp,
    required this.summary,
    required this.eventCount,
  });

  final String notificationId;
  final String incidentId;

  /// What kind of safety event this is. Never assume it — an alert shown
  /// under the wrong name is worse than an alert shown under no name.
  final IncidentType incidentType;

  final String cameraId;
  final String trackId;
  final int trackDisplayId;
  final String correlationId;
  final Severity severity;
  final double confidence;
  final IncidentStatus incidentStatus;
  final DateTime timestamp;
  final String summary;
  final int eventCount;

  factory NotificationMessage.fromJson(Map<String, dynamic> json) {
    return NotificationMessage(
      notificationId: json['notification_id'] as String,
      incidentId: json['incident_id'] as String,
      incidentType: IncidentType.fromWire(json['incident_type']),
      cameraId: json['camera_id'] as String,
      trackId: json['track_id'] as String,
      trackDisplayId: json['track_display_id'] as int,
      correlationId: json['correlation_id'] as String,
      severity: Severity.fromWire(json['severity'] as String),
      confidence: (json['confidence'] as num).toDouble(),
      incidentStatus:
          IncidentStatus.fromWire(json['incident_status'] as String),
      timestamp: DateTime.parse(json['timestamp'] as String),
      summary: json['summary'] as String,
      eventCount: json['event_count'] as int,
    );
  }

  Map<String, dynamic> toJson() => {
        'notification_id': notificationId,
        'incident_id': incidentId,
        'incident_type': incidentType.wire,
        'camera_id': cameraId,
        'track_id': trackId,
        'track_display_id': trackDisplayId,
        'correlation_id': correlationId,
        'severity': severity.wire,
        'confidence': confidence,
        'incident_status': incidentStatus.wire,
        'timestamp': timestamp.toIso8601String(),
        'summary': summary,
        'event_count': eventCount,
      };

  /// A copy with an updated incident status (after a review decision
  /// returned by the box — the app never invents state locally).
  NotificationMessage withIncidentStatus(IncidentStatus status) {
    return NotificationMessage(
      notificationId: notificationId,
      incidentId: incidentId,
      incidentType: incidentType,
      cameraId: cameraId,
      trackId: trackId,
      trackDisplayId: trackDisplayId,
      correlationId: correlationId,
      severity: severity,
      confidence: confidence,
      incidentStatus: status,
      timestamp: timestamp,
      summary: summary,
      eventCount: eventCount,
    );
  }
}
