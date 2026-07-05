import 'package:guardian_core/guardian_core.dart';

/// Read-only client for the box's health surface (`:8790`, ADR-0016).
///
/// Separate from [DeviceApi] on purpose: health is unauthenticated
/// LAN-plaintext monitoring data served by the ops layer, while the device
/// API is the authenticated incident/notification door. The app degrades
/// gracefully when the health port is unreachable (older box, firewall) —
/// alerts keep working without it.
abstract class BoxStatusApi {
  Future<BoxHealth> fetchHealth(String host, {int port});

  Future<BoxMetrics> fetchMetrics(String host, {int port});

  /// Ask the box to restart one camera. Boxes up to v0.2 do not support
  /// this; implementations throw [UnsupportedByBoxError] on 404/405 so the
  /// UI can explain that auto-recovery already handles crashed cameras.
  Future<void> restartCamera(PairedBox box, String cameraId);
}

/// The paired box does not implement the requested operation.
class UnsupportedByBoxError implements Exception {
  const UnsupportedByBoxError(this.operation);

  final String operation;

  @override
  String toString() => 'UnsupportedByBoxError($operation)';
}
