/// Wire models for the box's health surface (`:8790/health`, `/metrics`).
///
/// The health payload is produced by the edge ops layer (ADR-0016) and is
/// intentionally loose — component providers evolve — so parsing here is
/// tolerant: missing metrics become null, unknown components still render.
/// The identity fields the UI keys on (status, camera ids) stay strict.
library;

/// Overall/system component status as reported by the box.
enum BoxStatus {
  ok,
  degraded,
  warning,
  error,
  unknown;

  static BoxStatus fromWire(String? wire) => switch (wire) {
        'ok' => BoxStatus.ok,
        'degraded' => BoxStatus.degraded,
        'warning' => BoxStatus.warning,
        'error' => BoxStatus.error,
        _ => BoxStatus.unknown,
      };
}

/// One camera as seen in the health payload (status + measured FPS).
class CameraHealth {
  const CameraHealth({
    required this.cameraId,
    required this.status,
    this.fps,
    this.framesProcessed,
    this.framesDropped,
    this.detectorErrors,
    this.trackerErrors,
  });

  final String cameraId;
  final String status; // healthy | degraded | unhealthy | recovering ...
  final double? fps;
  final int? framesProcessed;
  final int? framesDropped;
  final int? detectorErrors;
  final int? trackerErrors;

  bool get isHealthy => status == 'healthy';
}

/// Host-level metrics (CPU, RAM, disk, temperature, uptime).
class HostMetrics {
  const HostMetrics({
    this.cpuPercent,
    this.memoryPercent,
    this.memoryUsedMb,
    this.diskPercent,
    this.diskFreeGb,
    this.temperatureC,
    this.uptimeSeconds,
  });

  final double? cpuPercent;
  final double? memoryPercent;
  final int? memoryUsedMb;
  final double? diskPercent;
  final double? diskFreeGb;
  final double? temperatureC;
  final double? uptimeSeconds;

  factory HostMetrics.fromJson(Map<String, dynamic> json) => HostMetrics(
        cpuPercent: _asDouble(json['cpu_percent']),
        memoryPercent: _asDouble(json['memory_percent']),
        memoryUsedMb: (json['memory_used_mb'] as num?)?.toInt(),
        diskPercent: _asDouble(json['disk_percent']),
        diskFreeGb: _asDouble(json['disk_free_gb']),
        temperatureC: _asDouble(json['temperature_c']),
        uptimeSeconds: _asDouble(json['uptime_seconds']),
      );

  Map<String, dynamic> toJson() => {
        'cpu_percent': cpuPercent,
        'memory_percent': memoryPercent,
        'memory_used_mb': memoryUsedMb,
        'disk_percent': diskPercent,
        'disk_free_gb': diskFreeGb,
        'temperature_c': temperatureC,
        'uptime_seconds': uptimeSeconds,
      };
}

/// One subsystem entry from `components` (cameras, inference, tracking…).
class SubsystemHealth {
  const SubsystemHealth({
    required this.name,
    required this.status,
    required this.detail,
  });

  final String name;
  final BoxStatus status;

  /// Everything else the provider reported, for detail rendering.
  final Map<String, dynamic> detail;
}

/// The full `/health` snapshot.
class BoxHealth {
  const BoxHealth({
    required this.status,
    required this.version,
    required this.subsystems,
    required this.cameras,
    required this.host,
    required this.warnings,
    required this.fetchedAt,
  });

  final BoxStatus status;
  final String version;
  final List<SubsystemHealth> subsystems;
  final List<CameraHealth> cameras;
  final HostMetrics host;
  final Map<String, String> warnings;

  /// When the app fetched this snapshot (local clock) — drives "last sync".
  final DateTime fetchedAt;

  factory BoxHealth.fromJson(Map<String, dynamic> json,
      {required DateTime fetchedAt}) {
    final components = (json['components'] as Map<String, dynamic>? ?? {});
    final subsystems = <SubsystemHealth>[];
    for (final entry in components.entries) {
      final value = entry.value;
      if (value is Map<String, dynamic>) {
        subsystems.add(SubsystemHealth(
          name: entry.key,
          status: BoxStatus.fromWire(value['status'] as String?),
          detail: value,
        ));
      }
    }
    return BoxHealth(
      status: BoxStatus.fromWire(json['status'] as String?),
      version: json['version'] as String? ?? '',
      subsystems: subsystems,
      cameras: _parseCameras(components),
      host: HostMetrics.fromJson(
          json['host'] as Map<String, dynamic>? ?? const {}),
      warnings: {
        for (final entry
            in (json['warnings'] as Map<String, dynamic>? ?? {}).entries)
          entry.key: entry.value.toString(),
      },
      fetchedAt: fetchedAt,
    );
  }

  /// Cameras come from two providers: `cameras` (status/fps per camera)
  /// and `inference` (per-camera pipeline counters); merge them by id.
  static List<CameraHealth> _parseCameras(Map<String, dynamic> components) {
    final cameraStatus = <String, String>{};
    final cameraFps = <String, double?>{};
    final camerasComponent = components['cameras'];
    if (camerasComponent is Map<String, dynamic>) {
      final byId = camerasComponent['cameras'];
      if (byId is Map<String, dynamic>) {
        for (final entry in byId.entries) {
          cameraStatus[entry.key] = entry.value.toString();
        }
      }
      final fps = camerasComponent['fps'];
      if (fps is Map<String, dynamic>) {
        for (final entry in fps.entries) {
          cameraFps[entry.key] = _asDouble(entry.value);
        }
      }
    }
    final pipeline = <String, Map<String, dynamic>>{};
    final inference = components['inference'];
    if (inference is Map<String, dynamic>) {
      final byId = inference['cameras'];
      if (byId is Map<String, dynamic>) {
        for (final entry in byId.entries) {
          if (entry.value is Map<String, dynamic>) {
            pipeline[entry.key] = entry.value as Map<String, dynamic>;
          }
        }
      }
    }
    final ids = {...cameraStatus.keys, ...pipeline.keys};
    return [
      for (final id in ids)
        CameraHealth(
          cameraId: id,
          status: cameraStatus[id] ?? 'unknown',
          fps: cameraFps[id] ?? _asDouble(pipeline[id]?['fps']),
          framesProcessed: (pipeline[id]?['processed'] as num?)?.toInt(),
          framesDropped: (pipeline[id]?['dropped'] as num?)?.toInt(),
          detectorErrors: (pipeline[id]?['detector_errors'] as num?)?.toInt(),
          trackerErrors: (pipeline[id]?['tracker_errors'] as num?)?.toInt(),
        ),
    ]..sort((a, b) => a.cameraId.compareTo(b.cameraId));
  }
}

/// The latest `/metrics` sample (host metrics + pipeline gauges).
class BoxMetrics {
  const BoxMetrics({
    required this.host,
    this.inferenceFps,
    this.trackingLatencyMs,
    this.notificationMeanDeliveryMs,
  });

  final HostMetrics host;
  final double? inferenceFps;
  final double? trackingLatencyMs;
  final double? notificationMeanDeliveryMs;

  factory BoxMetrics.fromJson(Map<String, dynamic> json) => BoxMetrics(
        host: HostMetrics.fromJson(json),
        inferenceFps: _asDouble(json['inference_fps']),
        trackingLatencyMs: _asDouble(json['tracking_latency_ms']),
        notificationMeanDeliveryMs:
            _asDouble(json['notification_mean_delivery_ms']),
      );
}

double? _asDouble(Object? value) => value is num ? value.toDouble() : null;
