import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'application/box_status_api.dart';
import 'application/connection_controller.dart';
import 'application/device_api.dart';
import 'application/evidence_cache.dart';
import 'application/evidence_controller.dart';
import 'application/notification_cache.dart';
import 'application/notification_repository.dart';
import 'application/settings_controller.dart';
import 'application/status_controller.dart';
import 'infrastructure/dio_box_status_api.dart';
import 'infrastructure/dio_device_api.dart';

/// Composition root (Riverpod). Tests override [deviceApiProvider],
/// [boxStatusApiProvider] and [notificationCacheProvider] with fakes;
/// production wiring lives in main().
final deviceApiProvider = Provider<DeviceApi>((ref) => DioDeviceApi());

final boxStatusApiProvider = Provider<BoxStatusApi>((ref) => DioBoxStatusApi());

final notificationCacheProvider = Provider<NotificationCache>(
  (ref) => throw UnimplementedError('overridden in main()/tests'),
);

final notificationRepositoryProvider =
    ChangeNotifierProvider<NotificationRepository>(
  (ref) => NotificationRepository(ref.watch(notificationCacheProvider)),
);

final settingsControllerProvider = ChangeNotifierProvider<SettingsController>(
  (ref) => SettingsController(ref.watch(notificationCacheProvider)),
);

final connectionControllerProvider =
    ChangeNotifierProvider<ConnectionController>(
  (ref) => ConnectionController(
    api: ref.watch(deviceApiProvider),
    cache: ref.watch(notificationCacheProvider),
    // .notifier: hold the repository without rebuilding this controller on
    // every repository change (a rebuilt controller would forget the box).
    repository: ref.watch(notificationRepositoryProvider.notifier),
  ),
);

/// Offline evidence media store; production wiring lives in main().
final evidenceCacheProvider = Provider<EvidenceCache>(
  (ref) => throw UnimplementedError('overridden in main()/tests'),
);

/// One evidence controller per incident (auto-disposed with the screen).
final evidenceControllerProvider = ChangeNotifierProvider.autoDispose
    .family<EvidenceController, String>((ref, incidentId) {
  final settings = ref.read(settingsControllerProvider).settings;
  final controller = EvidenceController(
    api: ref.watch(deviceApiProvider),
    cache: ref.watch(evidenceCacheProvider),
    box: ref.read(connectionControllerProvider).box,
    incidentId: incidentId,
    cacheLimitBytes: settings.evidenceCacheMb * 1024 * 1024,
  );
  controller.initialize();
  return controller;
});

/// Health poll cadence. Tests override with [Duration.zero] to disable the
/// periodic timer (flutter_test forbids timers outliving the tree).
final statusPollIntervalProvider =
    Provider<Duration>((ref) => const Duration(seconds: 10));

/// Follows the connection: polls the paired box's health surface while a
/// box is paired, stops when unpaired. The controller keeps the last
/// snapshot for offline rendering.
final statusControllerProvider = ChangeNotifierProvider<StatusController>(
  (ref) {
    final controller = StatusController(
      api: ref.watch(boxStatusApiProvider),
      cache: ref.watch(notificationCacheProvider),
      pollInterval: ref.watch(statusPollIntervalProvider),
    );
    void follow() {
      final box = ref.read(connectionControllerProvider).box;
      if (box != null) {
        controller.start(box.host);
      } else {
        controller.stop();
      }
    }

    ref.listen(connectionControllerProvider, (_, __) => follow());
    follow();
    return controller;
  },
);
