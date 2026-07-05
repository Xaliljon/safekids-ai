import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:guardian_core/guardian_core.dart';

import 'box_status_api.dart';
import 'notification_cache.dart';

/// Owns the box health/metrics picture the Dashboard, Cameras and Health
/// screens render. Polls `:8790` while running; the last good snapshot is
/// cached so every screen still renders offline (with its age visible).
class StatusController extends ChangeNotifier {
  StatusController({
    required BoxStatusApi api,
    required NotificationCache cache,
    Duration pollInterval = const Duration(seconds: 10),
    DateTime Function()? clock,
  })  : _api = api,
        _cache = cache,
        _pollInterval = pollInterval,
        _clock = clock ?? DateTime.now;

  final BoxStatusApi _api;
  final NotificationCache _cache;
  final Duration _pollInterval;
  final DateTime Function() _clock;

  BoxHealth? _health;
  BoxMetrics? _metrics;
  bool _live = false;
  bool _disposed = false;
  Timer? _timer;
  String? _host;

  /// Last known health snapshot (live or cached); null before first fetch.
  BoxHealth? get health => _health;

  /// Latest metrics sample; only available while the box is reachable.
  BoxMetrics? get metrics => _metrics;

  /// True when the last poll succeeded (the snapshot is current).
  bool get live => _live;

  /// When the current snapshot was fetched — "last sync" on the dashboard.
  DateTime? get lastSync => _health?.fetchedAt;

  /// Restore the cached snapshot so offline launches render immediately.
  Future<void> initialize() async {
    final raw = await _cache.loadHealthSnapshot();
    if (raw != null) {
      try {
        final decoded = jsonDecode(raw) as Map<String, dynamic>;
        _health = BoxHealth.fromJson(
          decoded['health'] as Map<String, dynamic>,
          fetchedAt: DateTime.parse(decoded['fetched_at'] as String),
        );
      } on Object {
        // A corrupt snapshot is not worth crashing over; refetch will heal.
      }
    }
    _notify();
  }

  /// Start polling the given box host (call again on re-pair). Calling
  /// repeatedly with the same host is a no-op — connection-state churn
  /// must not reset the poll cadence. A non-positive interval disables
  /// the periodic timer (tests poll explicitly via [refresh]).
  void start(String host) {
    final alreadyPolling =
        _host == host && (_timer != null || _pollInterval <= Duration.zero);
    if (alreadyPolling) {
      return;
    }
    _host = host;
    _timer?.cancel();
    if (_pollInterval > Duration.zero) {
      _timer = Timer.periodic(_pollInterval, (_) => refresh());
    }
    unawaited(refresh());
  }

  void stop() {
    _timer?.cancel();
    _timer = null;
  }

  /// One poll: health + metrics. Failures flip [live] to false but keep
  /// the last snapshot — never blank a screen because Wi-Fi blinked.
  Future<void> refresh() async {
    final host = _host;
    if (host == null || _disposed) {
      return;
    }
    try {
      final health = await _api.fetchHealth(host);
      BoxMetrics? metrics;
      try {
        metrics = await _api.fetchMetrics(host);
      } on Exception {
        metrics = null; // health without metrics is still a good poll
      }
      if (_disposed) {
        return;
      }
      _health = health;
      _metrics = metrics;
      _live = true;
      await _cache.saveHealthSnapshot(jsonEncode({
        'fetched_at': health.fetchedAt.toIso8601String(),
        'health': _healthToCacheJson(health),
      }));
    } on Exception {
      _live = false;
    }
    _notify();
  }

  /// Restart one camera on the box; returns null on success or a category
  /// the UI can translate ('unsupported' | 'failed').
  Future<String?> restartCamera(PairedBox box, String cameraId) async {
    try {
      await _api.restartCamera(box, cameraId);
      unawaited(refresh());
      return null;
    } on UnsupportedByBoxError {
      return 'unsupported';
    } on Exception {
      return 'failed';
    }
  }

  /// Age of the snapshot, for "last sync" rendering.
  Duration? snapshotAge() {
    final sync = lastSync;
    return sync == null ? null : _clock().difference(sync);
  }

  void _notify() {
    if (!_disposed) {
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}

/// Re-encode a BoxHealth back into its wire shape for the offline cache.
Map<String, dynamic> _healthToCacheJson(BoxHealth health) => {
      'status': health.status.name,
      'version': health.version,
      'components': {
        for (final subsystem in health.subsystems)
          subsystem.name: subsystem.detail,
      },
      'host': health.host.toJson(),
      'warnings': health.warnings,
    };
