import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:guardian_core/guardian_core.dart';

import 'device_api.dart';
import 'notification_cache.dart';
import 'notification_repository.dart';

enum BoxConnectionState { unpaired, connecting, connected, offline }

/// Owns the connection lifecycle: pair -> sync missed -> listen live ->
/// on any failure, back off and reconnect forever (the box owns the truth;
/// the phone's job is to keep catching up).
class ConnectionController extends ChangeNotifier {
  ConnectionController({
    required DeviceApi api,
    required NotificationCache cache,
    required NotificationRepository repository,
    Duration reconnectDelay = const Duration(seconds: 3),
  })  : _api = api,
        _cache = cache,
        _repository = repository,
        _reconnectDelay = reconnectDelay;

  final DeviceApi _api;
  final NotificationCache _cache;
  final NotificationRepository _repository;
  final Duration _reconnectDelay;

  BoxConnectionState _state = BoxConnectionState.unpaired;
  PairedBox? _box;
  bool _disposed = false;
  bool _looping = false;
  Timer? _retryTimer;

  BoxConnectionState get state => _state;
  PairedBox? get box => _box;

  /// Restore the trusted box from cache and start reconnecting.
  Future<void> initialize() async {
    await _repository.initialize();
    _box = await _cache.loadPairedBox();
    if (_box != null) {
      _setState(BoxConnectionState.connecting);
      unawaited(_runLoop());
    } else {
      _setState(BoxConnectionState.unpaired);
    }
  }

  /// Manual pairing (host + code). Returns an error message or null.
  Future<String?> pair({
    required String host,
    required int apiPort,
    required String code,
    required String deviceName,
  }) async {
    try {
      final box = await _api.pair(
        host: host,
        apiPort: apiPort,
        code: code,
        deviceName: deviceName,
      );
      await _cache.savePairedBox(box);
      _box = box;
      _setState(BoxConnectionState.connecting);
      unawaited(_runLoop());
      return null;
    } on Exception catch (error) {
      return 'Pairing failed: $error';
    }
  }

  /// Forget the trusted box: clears local trust and returns to unpaired.
  /// (Box-side revocation is deleting the device from trusted_devices.json.)
  Future<void> unpair() async {
    await _cache.clearPairedBox();
    _box = null;
    _retryTimer?.cancel();
    _setState(BoxConnectionState.unpaired);
  }

  /// Incident details from the box; null when it is no longer open there.
  Future<IncidentDetails?> fetchIncident(String incidentId) async {
    final box = _box;
    if (box == null) {
      return null;
    }
    try {
      return await _api.fetchIncident(box, incidentId);
    } on Exception {
      return null;
    }
  }

  /// Send the director's decision; the repository reflects the recorded
  /// result. Returns an error message or null.
  Future<String?> resolve(String incidentId,
      {required bool confirm, String note = ''}) async {
    final box = _box;
    if (box == null) {
      return 'Not paired with a Guardian Box';
    }
    try {
      final resolved = await _api.resolveIncident(box, incidentId,
          confirm: confirm, note: note);
      await _repository.applyResolution(resolved.incidentId, resolved.status);
      return null;
    } on Exception catch (error) {
      return 'Could not record the decision: $error';
    }
  }

  Future<void> _runLoop() async {
    if (_looping) {
      return;
    }
    _looping = true;
    try {
      while (!_disposed && _box != null) {
        final box = _box!;
        try {
          _setState(BoxConnectionState.connecting);
          final missed = await _api.fetchMissed(box, _repository.cursor);
          await _repository.applySync(missed.cursor, missed.notifications);
          _setState(BoxConnectionState.connected);
          await for (final message in _api.connect(box)) {
            await _repository.addLive(message);
          }
          // Stream ended: the box closed the connection.
          _setState(BoxConnectionState.offline);
        } on Exception {
          _setState(BoxConnectionState.offline);
        }
        if (_disposed) {
          return;
        }
        await _interruptibleDelay();
      }
    } finally {
      _looping = false;
    }
  }

  /// A delay that dispose() can cancel — no timer may outlive the app.
  Future<void> _interruptibleDelay() {
    final completer = Completer<void>();
    _retryTimer = Timer(_reconnectDelay, () {
      if (!completer.isCompleted) {
        completer.complete();
      }
    });
    return completer.future;
  }

  void _setState(BoxConnectionState next) {
    if (_disposed || _state == next) {
      return;
    }
    _state = next;
    notifyListeners();
  }

  @override
  void dispose() {
    if (_disposed) {
      return;
    }
    _disposed = true;
    _retryTimer?.cancel();
    super.dispose();
  }
}
