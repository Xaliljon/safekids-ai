/// Incident severity and status vocabularies (mirror the edge domain).
library;

enum Severity {
  low,
  medium,
  high,
  critical;

  static Severity fromWire(String value) => switch (value) {
        'low' => Severity.low,
        'medium' => Severity.medium,
        'high' => Severity.high,
        'critical' => Severity.critical,
        _ => throw FormatException('unknown severity: $value'),
      };

  String get wire => name;

  /// Ordering rank; higher is more severe.
  int get rank => index;
}

enum IncidentStatus {
  pendingReview,
  confirmed,
  dismissed;

  static IncidentStatus fromWire(String value) => switch (value) {
        'pending_review' => IncidentStatus.pendingReview,
        'confirmed' => IncidentStatus.confirmed,
        'dismissed' => IncidentStatus.dismissed,
        _ => throw FormatException('unknown incident status: $value'),
      };

  String get wire => switch (this) {
        IncidentStatus.pendingReview => 'pending_review',
        IncidentStatus.confirmed => 'confirmed',
        IncidentStatus.dismissed => 'dismissed',
      };
}
