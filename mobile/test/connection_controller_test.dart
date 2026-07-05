import 'package:flutter_test/flutter_test.dart';
import 'package:safekids_mobile/src/application/connection_controller.dart';
import 'package:safekids_mobile/src/application/notification_repository.dart';

import 'fakes.dart';

ConnectionController makeController(
  FakeDeviceApi api,
  InMemoryCache cache,
  NotificationRepository repository,
) {
  return ConnectionController(
    api: api,
    cache: cache,
    repository: repository,
    reconnectDelay: const Duration(milliseconds: 10),
  );
}

void main() {
  group('pairing', () {
    test('successful pairing stores the trusted box and connects', () async {
      final api = FakeDeviceApi();
      final cache = InMemoryCache();
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      expect(controller.state, BoxConnectionState.unpaired);
      final error = await controller.pair(
        host: '127.0.0.1',
        apiPort: 8787,
        code: '123456',
        deviceName: 'director-phone',
      );
      await pump();
      expect(error, isNull);
      expect(cache.box, isNotNull, reason: 'trusted device stored');
      expect(controller.state, BoxConnectionState.connected);
      controller.dispose();
    });

    test('failed pairing reports the error and stays unpaired', () async {
      final api = FakeDeviceApi()..failPair = true;
      final cache = InMemoryCache();
      final controller =
          makeController(api, cache, NotificationRepository(cache));
      await controller.initialize();
      final error = await controller.pair(
        host: '127.0.0.1',
        apiPort: 8787,
        code: '000000',
        deviceName: 'director-phone',
      );
      expect(error, contains('Pairing failed'));
      expect(controller.state, BoxConnectionState.unpaired);
      controller.dispose();
    });
  });

  group('reconnect and synchronization', () {
    test('restores the trusted box and syncs missed notifications', () async {
      final api = FakeDeviceApi()
        ..syncCursor = 2
        ..missed = [makeMessage(id: 'n-1'), makeMessage(id: 'n-2')];
      final cache = InMemoryCache()..box = testBox;
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      await pump();
      expect(controller.state, BoxConnectionState.connected);
      expect(repository.items, hasLength(2), reason: 'missed are synchronized');
      expect(repository.cursor, 2);
      controller.dispose();
    });

    test('live notifications arrive over the websocket stream', () async {
      final api = FakeDeviceApi();
      final cache = InMemoryCache()..box = testBox;
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      await pump();
      api.live!.add(makeMessage(id: 'n-live'));
      await pump();
      expect(repository.items.single.message.notificationId, 'n-live');
      controller.dispose();
    });

    test('dropped connection goes offline then reconnects and resyncs',
        () async {
      final api = FakeDeviceApi();
      final cache = InMemoryCache()..box = testBox;
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      await pump();
      expect(controller.state, BoxConnectionState.connected);

      // Wi-Fi dies: the box closes the stream; missed things pile up.
      api
        ..syncCursor = 1
        ..missed = [makeMessage(id: 'n-missed')];
      await api.live!.close();
      await pump();
      await Future<void>.delayed(const Duration(milliseconds: 40));
      expect(api.connectCount, greaterThanOrEqualTo(2),
          reason: 'reconnects automatically');
      expect(controller.state, BoxConnectionState.connected);
      expect(
        repository.items.any(
          (item) => item.message.notificationId == 'n-missed',
        ),
        isTrue,
        reason: 'missed notifications are synchronized after reconnect',
      );
      controller.dispose();
    });

    test('sync failure keeps cached items and keeps retrying', () async {
      final api = FakeDeviceApi()..failSync = true;
      final cache = InMemoryCache()..box = testBox;
      await cache.saveNotification(makeMessage(id: 'n-cached'));
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      await pump();
      expect(controller.state, BoxConnectionState.offline);
      expect(repository.items, hasLength(1),
          reason: 'cache serves the UI while offline');
      api.failSync = false;
      await Future<void>.delayed(const Duration(milliseconds: 40));
      expect(controller.state, BoxConnectionState.connected,
          reason: 'reconnects automatically');
      controller.dispose();
    });
  });

  group('director actions', () {
    test('resolve sends the decision and reflects the recorded status',
        () async {
      final api = FakeDeviceApi();
      final cache = InMemoryCache()..box = testBox;
      final repository = NotificationRepository(cache);
      final controller = makeController(api, cache, repository);
      await controller.initialize();
      await pump();
      await repository.addLive(makeMessage(id: 'n-1', incidentId: 'i-1'));
      final error = await controller.resolve('i-1', confirm: true);
      expect(error, isNull);
      expect(api.resolved, ['i-1:confirm']);
      expect(repository.items.single.message.incidentStatus.wire, 'confirmed');
      controller.dispose();
    });
  });
}
