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
  await container.read(connectionControllerProvider).initialize();
  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const GuardianApp(),
    ),
  );
}
