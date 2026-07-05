import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hive/hive.dart';
import 'package:safekids_mobile/src/infrastructure/hive_cache.dart';

import 'fakes.dart';

void main() {
  late Directory directory;
  late HiveNotificationCache cache;

  setUp(() async {
    directory = await Directory.systemTemp.createTemp('guardian-hive-test');
    Hive.init(directory.path);
    cache = await HiveNotificationCache.open();
  });

  tearDown(() async {
    await Hive.close();
    await directory.delete(recursive: true);
  });

  test('notifications survive a restart', () async {
    await cache.saveNotification(makeMessage(id: 'n-1'));
    await Hive.close();
    Hive.init(directory.path);
    final reopened = await HiveNotificationCache.open();
    final restored = await reopened.loadNotifications();
    expect(restored.single.notificationId, 'n-1');
    expect(restored.single.summary, contains('track #7'));
  });

  test('cursor, read ids and paired box round-trip', () async {
    await cache.saveCursor(42);
    await cache.markRead('n-1');
    await cache.markRead('n-2');
    await cache.savePairedBox(testBox);
    expect(await cache.loadCursor(), 42);
    expect(await cache.loadReadIds(), {'n-1', 'n-2'});
    final box = await cache.loadPairedBox();
    expect(box!.token, testBox.token);
    expect(box.wsUri.toString(), contains('ws://127.0.0.1:8788/ws'));
  });

  test('empty cache yields safe defaults', () async {
    expect(await cache.loadNotifications(), isEmpty);
    expect(await cache.loadCursor(), 0);
    expect(await cache.loadReadIds(), isEmpty);
    expect(await cache.loadPairedBox(), isNull);
    expect(await cache.loadArchivedIds(), isEmpty);
    expect(await cache.loadSettings(), isNull);
    expect(await cache.loadHealthSnapshot(), isNull);
  });

  test('archived ids round-trip and unarchive removes', () async {
    await cache.setArchived('n-1', true);
    await cache.setArchived('n-2', true);
    await cache.setArchived('n-1', false);
    expect(await cache.loadArchivedIds(), {'n-2'});
  });

  test('settings and health snapshot round-trip', () async {
    await cache.saveSettings('{"theme_mode":"dark"}');
    await cache.saveHealthSnapshot('{"status":"ok"}');
    expect(await cache.loadSettings(), '{"theme_mode":"dark"}');
    expect(await cache.loadHealthSnapshot(), '{"status":"ok"}');
  });

  test('clearPairedBox forgets the trusted box', () async {
    await cache.savePairedBox(testBox);
    await cache.clearPairedBox();
    expect(await cache.loadPairedBox(), isNull);
  });
}
