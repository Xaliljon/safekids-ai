/// The kind of safety event an incident represents (mirrors the edge
/// `CandidateEventType`).
library;

/// What kind of potential safety event this is.
///
/// Parsing here is deliberately **lenient**, unlike the rest of this package
/// (see the library doc): this vocabulary grows as SafeKids gains detectors,
/// and a box may be updated before the phones are. A strict parse would make
/// an older app throw away a newer box's alerts — silence exactly when a
/// child needs attention. An unrecognized type therefore degrades to
/// [IncidentType.unknown], which the UI must render as a neutral label.
///
/// Guessing is the one thing forbidden: an unlabelled alert must never be
/// shown as a fall, because a director acting on the wrong event acts wrongly
/// (docs/04 — AI informs, humans decide).
enum IncidentType {
  potentialFall,

  /// A child sustained outside a declared safe area (ADR-0018).
  zoneExit,

  /// A type this app build does not know, or a payload that predates the
  /// field. The event is real; only its name is unavailable.
  unknown;

  static IncidentType fromWire(Object? value) => switch (value) {
        'potential_fall' => IncidentType.potentialFall,
        'zone_exit' => IncidentType.zoneExit,
        _ => IncidentType.unknown,
      };

  String get wire => switch (this) {
        IncidentType.potentialFall => 'potential_fall',
        IncidentType.zoneExit => 'zone_exit',
        IncidentType.unknown => 'unknown',
      };
}
