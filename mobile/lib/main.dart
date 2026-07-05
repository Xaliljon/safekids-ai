import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:hive/hive.dart';
import 'package:path_provider/path_provider.dart';

import 'src/app.dart';
import 'src/infrastructure/hive_cache.dart';
import 'src/providers.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final directory = await getApplicationDocumentsDirectory();
  Hive.init(directory.path);
  final cache = await HiveNotificationCache.open();
  final container = ProviderContainer(
    overrides: [notificationCacheProvider.overrideWithValue(cache)],
  );
  await container.read(settingsControllerProvider).initialize();
  final controller = container.read(connectionControllerProvider);
  await controller.initialize();
  // The status controller restores its cached snapshot and follows the
  // connection (it starts polling as soon as a box is paired).
  await container.read(statusControllerProvider).initialize();
  // Dev bootstrap (demos/tests): auto-pair on first launch when built with
  // --dart-define=GUARDIAN_BOOTSTRAP=host,port,code — never set in release.
  const bootstrap = String.fromEnvironment('GUARDIAN_BOOTSTRAP');
  if (bootstrap.isNotEmpty && controller.box == null) {
    final parts = bootstrap.split(',');
    if (parts.length == 3) {
      await controller.pair(
        host: parts[0],
        apiPort: int.parse(parts[1]),
        code: parts[2],
        deviceName: 'director-phone',
      );
    }
  }
  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const GuardianApp(),
    ),
  );
}
