import 'package:flutter_test/flutter_test.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/application/notification_repository.dart';

import 'fakes.dart';

Future<NotificationRepository> seeded(InMemoryCache cache) async {
  final repository = NotificationRepository(cache);
  await repository.initialize();
  await repository.applySync(4, [
    makeMessage(
        id: 'n-a',
        incidentId: 'i-a',
        severity: 'critical',
        timestamp: DateTime.utc(2026, 7, 6, 9, 0, 0)),
    makeMessage(
        id: 'n-b',
        incidentId: 'i-b',
        severity: 'medium',
        timestamp: DateTime.utc(2026, 7, 6, 8, 0, 0)),
    makeMessage(
        id: 'n-c',
        incidentId: 'i-a',
        severity: 'high',
        timestamp: DateTime.utc(2026, 7, 5, 9, 0, 0)),
  ]);
  return repository;
}

void main() {
  group('AlertFilter shelves', () {
    test('unread/read/archived are disjoint', () async {
      final cache = InMemoryCache();
      final repository = await seeded(cache);
      await repository.markRead('n-a');
      await repository.setArchived('n-b', true);

      List<String> ids(AlertsTab tab) => repository
          .page(AlertFilter(tab: tab))
          .map((item) => item.message.notificationId)
          .toList();

      expect(ids(AlertsTab.unread), ['n-c']);
      expect(ids(AlertsTab.read), ['n-a']);
      expect(ids(AlertsTab.archived), ['n-b']);
    });

    test('archived read notifications stay on the archived shelf', () async {
      final repository = await seeded(InMemoryCache());
      await repository.markRead('n-a');
      await repository.setArchived('n-a', true);
      expect(
          repository.page(const AlertFilter(tab: AlertsTab.read)),
          isNot(contains(predicate<NotificationItem>(
              (item) => item.message.notificationId == 'n-a'))));
      expect(
          repository
              .page(const AlertFilter(tab: AlertsTab.archived))
              .single
              .message
              .notificationId,
          'n-a');
    });

    test('unarchive returns the notification to its shelf', () async {
      final cache = InMemoryCache();
      final repository = await seeded(cache);
      await repository.setArchived('n-b', true);
      await repository.setArchived('n-b', false);
      expect(cache.archivedIds, isEmpty);
      expect(
          repository
              .page(const AlertFilter(tab: AlertsTab.unread))
              .map((item) => item.message.notificationId),
          contains('n-b'));
    });
  });

  group('search and filters', () {
    test('query matches summary, camera and track number', () async {
      final repository = await seeded(InMemoryCache());
      expect(repository.count(const AlertFilter(query: 'classroom-1')), 3);
      expect(repository.count(const AlertFilter(query: 'track #7')), 3);
      expect(repository.count(const AlertFilter(query: 'TRACK #7')), 3,
          reason: 'case-insensitive');
      expect(repository.count(const AlertFilter(query: 'nothing-here')), 0);
    });

    test('severity filter is a union of selected severities', () async {
      final repository = await seeded(InMemoryCache());
      expect(
          repository.count(const AlertFilter(severities: {Severity.critical})),
          1);
      expect(
          repository.count(const AlertFilter(
              severities: {Severity.critical, Severity.high})),
          2);
      expect(repository.count(const AlertFilter()), 3,
          reason: 'empty set means all severities');
    });

    test('camera filter narrows to one camera', () async {
      final repository = await seeded(InMemoryCache());
      expect(repository.count(const AlertFilter(cameraId: 'classroom-1')), 3);
      expect(
          repository.count(const AlertFilter(cameraId: 'no-such-camera')), 0);
    });
  });

  group('pagination', () {
    test('page respects offset and limit, newest first', () async {
      final repository = NotificationRepository(InMemoryCache());
      await repository.initialize();
      await repository.applySync(30, [
        for (var i = 0; i < 30; i++)
          makeMessage(
              id: 'n-$i',
              incidentId: 'i-$i',
              timestamp: DateTime.utc(2026, 7, 6, 8, 0, i)),
      ]);
      final first = repository.page(const AlertFilter(), limit: 10);
      expect(first, hasLength(10));
      expect(first.first.message.notificationId, 'n-29', reason: 'newest');
      final second =
          repository.page(const AlertFilter(), offset: 10, limit: 10);
      expect(second.first.message.notificationId, 'n-19');
      expect(repository.count(const AlertFilter()), 30);
    });
  });

  group('incident helpers', () {
    test('byIncidentId returns that incident chronologically', () async {
      final repository = await seeded(InMemoryCache());
      final history = repository.byIncidentId('i-a');
      expect(history.map((message) => message.notificationId), ['n-c', 'n-a']);
    });

    test('cameraIds lists distinct cameras sorted', () async {
      final repository = await seeded(InMemoryCache());
      expect(repository.cameraIds, ['classroom-1']);
    });
  });
}
