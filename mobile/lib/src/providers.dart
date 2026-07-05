import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'application/connection_controller.dart';
import 'application/device_api.dart';
import 'application/notification_cache.dart';
import 'application/notification_repository.dart';
import 'infrastructure/dio_device_api.dart';

/// Composition root (Riverpod). Tests override [deviceApiProvider] and
/// [notificationCacheProvider] with fakes; production wiring lives in main().
final deviceApiProvider = Provider<DeviceApi>((ref) => DioDeviceApi());

final notificationCacheProvider = Provider<NotificationCache>(
  (ref) => throw UnimplementedError('overridden in main()/tests'),
);

final notificationRepositoryProvider =
    ChangeNotifierProvider<NotificationRepository>(
  (ref) => NotificationRepository(ref.watch(notificationCacheProvider)),
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
