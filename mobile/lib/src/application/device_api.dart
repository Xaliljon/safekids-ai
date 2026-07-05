import 'package:guardian_core/guardian_core.dart';

/// Result of an offline catch-up sync against the box's durable outbox.
class SyncResult {
  const SyncResult({required this.cursor, required this.notifications});

  final int cursor;
  final List<NotificationMessage> notifications;
}

/// The app's only door to the Guardian Box (ADR-0015).
///
/// The mobile app never talks to the risk or notification engines directly —
/// everything goes through the Device API. Implementations must be
/// side-effect free beyond I/O; state lives in the repository.
abstract class DeviceApi {
  /// Exchange a pairing code for a trusted-device token.
  Future<PairedBox> pair({
    required String host,
    required int apiPort,
    required String code,
    required String deviceName,
  });

  /// Fetch notifications missed while offline (outbox lines after [afterCursor]).
  Future<SyncResult> fetchMissed(PairedBox box, int afterCursor);

  /// Incident details with the event timeline; throws on 404 (not open).
  Future<IncidentDetails> fetchIncident(PairedBox box, String incidentId);

  /// Send the director's decision to the box. The box is the source of
  /// truth — the returned incident reflects the recorded resolution.
  Future<IncidentDetails> resolveIncident(
    PairedBox box,
    String incidentId, {
    required bool confirm,
    String note,
  });

  /// Live notification stream over WebSocket. The stream ends (or errors)
  /// when the connection drops; the caller owns reconnection.
  Stream<NotificationMessage> connect(PairedBox box);
}
