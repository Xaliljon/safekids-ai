import 'package:flutter_test/flutter_test.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/application/notification_repository.dart';

import 'fakes.dart';

void main() {
  group('NotificationRepository', () {
    test('restores state from the offline cache', () async {
      final cache = InMemoryCache();
      await cache.saveNotification(makeMessage(id: 'n-1'));
      await cache.saveCursor(5);
      await cache.markRead('n-1');
      final repository = NotificationRepository(cache);
      await repository.initialize();
      expect(repository.items, hasLength(1));
      expect(repository.items.single.read, isTrue);
      expect(repository.cursor, 5);
      expect(repository.unreadCount, 0);
    });

    test('live notifications persist and advance the cursor', () async {
      final cache = InMemoryCache();
      final repository = NotificationRepository(cache);
      await repository.initialize();
      await repository.addLive(makeMessage(id: 'n-1'));
      expect(repository.cursor, 1);
      expect(cache.notifications, contains('n-1'));
      expect(cache.cursor, 1, reason: 'nothing is lost to a crash');
      expect(repository.unreadCount, 1);
    });

    test('sync merges missed notifications and jumps the cursor', () async {
      final cache = InMemoryCache();
      final repository = NotificationRepository(cache);
      await repository.initialize();
      await repository.applySync(3, [
        makeMessage(id: 'n-1', timestamp: DateTime.utc(2026, 7, 5, 12, 0, 1)),
        makeMessage(id: 'n-2', timestamp: DateTime.utc(2026, 7, 5, 12, 0, 9)),
      ]);
      expect(repository.cursor, 3);
      expect(repository.items, hasLength(2));
      expect(repository.items.first.message.notificationId, 'n-2',
          reason: 'newest first');
    });

    test('duplicate ids never create duplicate rows', () async {
      final repository = NotificationRepository(InMemoryCache());
      await repository.initialize();
      await repository.addLive(makeMessage(id: 'n-1'));
      await repository.applySync(2, [makeMessage(id: 'n-1')]);
      expect(repository.items, hasLength(1));
    });

    test('markRead flips the unread indicator once', () async {
      final repository = NotificationRepository(InMemoryCache());
      await repository.initialize();
      await repository.addLive(makeMessage(id: 'n-1'));
      await repository.markRead('n-1');
      await repository.markRead('n-1');
      expect(repository.items.single.read, isTrue);
      expect(repository.unreadCount, 0);
    });

    test('box-recorded resolutions update every notification of the incident',
        () async {
      final cache = InMemoryCache();
      final repository = NotificationRepository(cache);
      await repository.initialize();
      await repository.addLive(makeMessage(id: 'n-1', incidentId: 'i-1'));
      await repository.addLive(
        makeMessage(
          id: 'n-2',
          incidentId: 'i-1',
          timestamp: DateTime.utc(2026, 7, 5, 12, 0, 25),
        ),
      );
      await repository.applyResolution('i-1', IncidentStatus.confirmed);
      expect(
        repository.items.map((item) => item.message.incidentStatus).toSet(),
        {IncidentStatus.confirmed},
      );
      expect(
        cache.notifications['n-1']!.incidentStatus,
        IncidentStatus.confirmed,
        reason: 'the cache reflects the box-recorded truth',
      );
    });
  });
}
