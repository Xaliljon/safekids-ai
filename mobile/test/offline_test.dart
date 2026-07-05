import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';
import 'harness.dart';

/// Offline-first: a phone that lost the box (Wi-Fi outage, box reboot)
/// must keep every screen usable from the cache and say so honestly.
void main() {
  Future<Harness> pumpOffline(WidgetTester tester) async {
    // First run online to fill the caches...
    final warmCache = InMemoryCache()..box = testBox;
    final warm = await pumpApp(
      tester,
      setup: (api, statusApi, cache) {
        cache.box = testBox;
        api
          ..syncCursor = 2
          ..missed = [
            makeMessage(id: 'n-1'),
            makeMessage(id: 'n-2', incidentId: 'i-2', severity: 'high'),
          ];
      },
    );
    await tester.pumpAndSettle();
    // ...then restart the app with every network call failing.
    warmCache.notifications.addAll(warm.cache.notifications);
    warmCache.readIds.addAll(warm.cache.readIds);
    warmCache.cursor = warm.cache.cursor;
    warmCache.healthJson = warm.cache.healthJson;
    await tester.pumpWidget(const SizedBox());
    warm.container.dispose();
    final harness = await pumpApp(
      tester,
      setup: (api, statusApi, cache) {
        cache
          ..box = warmCache.box
          ..cursor = warmCache.cursor
          ..healthJson = warmCache.healthJson;
        cache.notifications.addAll(warmCache.notifications);
        cache.readIds.addAll(warmCache.readIds);
        api.failSync = true;
        statusApi.failHealth = true;
      },
    );
    await tester.pumpAndSettle();
    return harness;
  }

  appTest('dashboard renders the cached snapshot with offline banner',
      (tester) async {
    await pumpOffline(tester);
    expect(find.byKey(const Key('dashboard-list')), findsOneWidget);
    expect(find.byKey(const Key('offline-banner')), findsOneWidget);
    expect(find.byKey(const Key('system-status')), findsOneWidget,
        reason: 'cached health still renders');
    expect(find.text('All systems normal'), findsOneWidget);
  });

  appTest('alerts list works fully offline from the cache', (tester) async {
    await pumpOffline(tester);
    await goTab(tester, 'Alerts');
    expect(find.byKey(const Key('offline-banner')), findsOneWidget);
    expect(find.byKey(const Key('notification-n-1')), findsOneWidget);
    expect(find.byKey(const Key('notification-n-2')), findsOneWidget);
    // Archive/read state changes persist locally while offline.
    await tester.tap(find.byKey(const Key('archive-n-2')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('notification-n-2')), findsNothing);
  });

  appTest('health screen shows the stale snapshot and its origin',
      (tester) async {
    await pumpOffline(tester);
    await goTab(tester, 'Health');
    expect(find.byKey(const Key('health-list')), findsOneWidget);
    expect(find.textContaining('last known'), findsOneWidget);
    expect(find.byKey(const Key('subsystem-cameras')), findsOneWidget);
  });

  appTest('cameras screen renders cached camera list offline', (tester) async {
    await pumpOffline(tester);
    await goTab(tester, 'Cameras');
    expect(find.byKey(const Key('camera-classroom-1')), findsOneWidget);
    expect(find.textContaining('last known'), findsOneWidget);
  });
}
