import 'incident_type.dart';
import 'severity.dart';

/// One explainable signal contributing to a candidate event's confidence.
class EventSignal {
  const EventSignal(
      {required this.name, required this.score, required this.detail});

  final String name;
  final double score;
  final String detail;

  factory EventSignal.fromJson(Map<String, dynamic> json) => EventSignal(
        name: json['name'] as String,
        score: (json['score'] as num).toDouble(),
        detail: json['detail'] as String,
      );
}

/// One timeline entry: a candidate event that evidenced the incident.
class IncidentEvent {
  const IncidentEvent({
    required this.observedAt,
    required this.confidence,
    required this.signals,
  });

  final DateTime observedAt;
  final double confidence;
  final List<EventSignal> signals;

  factory IncidentEvent.fromJson(Map<String, dynamic> json) => IncidentEvent(
        observedAt: DateTime.parse(json['observed_at'] as String),
        confidence: (json['confidence'] as num).toDouble(),
        signals: [
          for (final signal in json['signals'] as List<dynamic>)
            EventSignal.fromJson(signal as Map<String, dynamic>),
        ],
      );
}

/// Full incident details from the box, including the event timeline.
class IncidentDetails {
  const IncidentDetails({
    required this.incidentId,
    required this.incidentType,
    required this.cameraId,
    required this.trackId,
    required this.trackDisplayId,
    required this.severity,
    required this.riskConfidence,
    required this.status,
    required this.openedAt,
    required this.lastEventAt,
    required this.correlationId,
    required this.summary,
    required this.events,
    this.reviewer,
  });

  final String incidentId;

  /// What kind of safety event this is.
  final IncidentType incidentType;

  final String cameraId;
  final String trackId;
  final int trackDisplayId;
  final Severity severity;
  final double riskConfidence;
  final IncidentStatus status;
  final DateTime openedAt;
  final DateTime lastEventAt;
  final String correlationId;
  final String summary;
  final List<IncidentEvent> events;
  final String? reviewer;

  factory IncidentDetails.fromJson(Map<String, dynamic> json) =>
      IncidentDetails(
        incidentId: json['incident_id'] as String,
        // This endpoint spells it 'type'; notification payloads spell it
        // 'incident_type' because their 'type' already names the message
        // kind. Same vocabulary, two keys — do not unify one side only.
        incidentType: IncidentType.fromWire(json['type']),
        cameraId: json['camera_id'] as String,
        trackId: json['track_id'] as String,
        trackDisplayId: json['track_display_id'] as int,
        severity: Severity.fromWire(json['severity'] as String),
        riskConfidence: (json['risk_confidence'] as num).toDouble(),
        status: IncidentStatus.fromWire(json['status'] as String),
        openedAt: DateTime.parse(json['opened_at'] as String),
        lastEventAt: DateTime.parse(json['last_event_at'] as String),
        correlationId: json['correlation_id'] as String,
        summary: json['summary'] as String,
        events: [
          for (final event in (json['events'] as List<dynamic>? ?? []))
            IncidentEvent.fromJson(event as Map<String, dynamic>),
        ],
        reviewer:
            (json['review'] as Map<String, dynamic>?)?['reviewer'] as String?,
      );
}
