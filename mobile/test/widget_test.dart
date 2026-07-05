import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/providers.dart';

import 'fakes.dart';
import 'harness.dart';

void main() {
  group('pairing wizard', () {
    appTest('unpaired app starts on the wizard and pairs manually',
        (tester) async {
      await pumpApp(tester);
      expect(find.byKey(const Key('pairing-wizard')), findsOneWidget);
      expect(find.byKey(const Key('scan-qr-button')), findsOneWidget);
      await pairManually(tester);
      expect(find.byKey(const Key('dashboard-list')), findsOneWidget,
          reason: 'paired: the app lands on the dashboard');
    });

    appTest('pairing failure shows the error and stays put', (tester) async {
      final harness = await pumpApp(tester);
      harness.api.failPair = true;
      await pairManually(tester);
      expect(find.byKey(const Key('pair-error')), findsOneWidget);
      expect(find.byKey(const Key('pairing-wizard')), findsOneWidget);
    });
  });

  group('dashboard', () {
    appTest('renders system status, cameras, and last sync', (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('system-status')), findsOneWidget);
      expect(find.text('All systems normal'), findsOneWidget);
      expect(find.byKey(const Key('cameras-online')), findsOneWidget);
      expect(find.text('1 of 1 online'), findsOneWidget);
      expect(find.byKey(const Key('last-sync')), findsOneWidget);
      expect(find.byKey(const Key('dashboard-no-incidents')), findsOneWidget);
    });

    appTest('shows recent incidents and opens details', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 1
            ..missed = [makeMessage(id: 'n-1')];
        },
      );
      harness.api.incidentDetails = makeDetails();
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('dashboard-no-incidents')), findsNothing);
      await tester.tap(find.textContaining('Potential fall').first);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('incident-list')), findsOneWidget);
    });

    appTest('degraded box shows warning status and warnings', (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          statusApi.healthJson = makeHealthJson(
            status: 'warning',
            warnings: {'vision-pipeline': 'keeps failing; still retrying'},
          );
        },
      );
      await tester.pumpAndSettle();
      expect(find.text('Needs attention'), findsOneWidget);
      expect(find.textContaining('vision-pipeline'), findsOneWidget);
    });
  });

  group('notification center', () {
    Future<Harness> pumpWithAlerts(WidgetTester tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 3
            ..missed = [
              makeMessage(
                  id: 'n-critical',
                  severity: 'critical',
                  timestamp: DateTime.utc(2026, 7, 6, 9, 0, 0)),
              makeMessage(
                  id: 'n-medium',
                  incidentId: 'i-2',
                  severity: 'medium',
                  timestamp: DateTime.utc(2026, 7, 6, 8, 0, 0)),
              makeMessage(
                  id: 'n-old',
                  incidentId: 'i-3',
                  severity: 'high',
                  timestamp: DateTime.utc(2026, 7, 1, 12, 0, 0)),
            ];
        },
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      return harness;
    }

    appTest('groups by date and shows unread on the unread tab',
        (tester) async {
      await pumpWithAlerts(tester);
      expect(find.byKey(const Key('notification-list')), findsOneWidget);
      expect(find.byKey(const Key('notification-n-critical')), findsOneWidget);
      expect(find.byKey(const Key('notification-n-old')), findsOneWidget);
      expect(find.text('2026-07-01'), findsOneWidget,
          reason: 'older alerts get a date header');
    });

    appTest('search filters the list', (tester) async {
      await pumpWithAlerts(tester);
      await tester.enterText(
          find.byKey(const Key('alerts-search')), 'track #7');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('notification-n-critical')), findsOneWidget);
      await tester.enterText(
          find.byKey(const Key('alerts-search')), 'no-such-thing');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('empty-state')), findsOneWidget);
      expect(
          find.text('Nothing matches your search or filters.'), findsOneWidget);
    });

    appTest('severity filter narrows the list', (tester) async {
      await pumpWithAlerts(tester);
      await tester.tap(find.byKey(const Key('severity-filter-critical')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('notification-n-critical')), findsOneWidget);
      expect(find.byKey(const Key('notification-n-medium')), findsNothing);
    });

    appTest('read/archived shelves work end to end', (tester) async {
      final harness = await pumpWithAlerts(tester);
      // Archive one from the unread shelf.
      await tester.tap(find.byKey(const Key('archive-n-medium')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('notification-n-medium')), findsNothing);
      // It appears on the archived shelf.
      await tester.tap(find.text('Archived'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('notification-n-medium')), findsOneWidget);
      expect(harness.cache.archivedIds, contains('n-medium'));
      // Mark-all-read moves the rest to the read shelf.
      await tester.tap(find.byKey(const Key('mark-all-read')));
      await tester.tap(find.text('Read'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('notification-n-critical')), findsOneWidget);
    });

    appTest('pagination shows load-more past the page size', (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 60
            ..missed = [
              for (var i = 0; i < 60; i++)
                makeMessage(
                    id: 'n-$i',
                    incidentId: 'i-$i',
                    timestamp: DateTime.utc(2026, 7, 6, 8, 0, i)),
            ];
        },
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      final loadMore = find.byKey(const Key('load-more'));
      await tester.scrollUntilVisible(loadMore, 400,
          scrollable: find.descendant(
              of: find.byKey(const Key('notification-list')),
              matching: find.byType(Scrollable)));
      expect(loadMore, findsOneWidget);
      await tester.tap(loadMore);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('load-more')), findsNothing,
          reason: 'all 60 fit after loading the second page');
    });
  });

  group('incident details', () {
    appTest('renders timeline, signals, evidence and track history',
        (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 1
            ..missed = [makeMessage(id: 'n-1')];
        },
      );
      harness.api.incidentDetails = makeDetails();
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      await tester.tap(find.byKey(const Key('notification-n-1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('review-status-chip')), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('evidence-note')),
          list: const Key('incident-list'));
      expect(find.byKey(const Key('evidence-note')), findsOneWidget);
      await scrollTo(tester, find.textContaining('downward_velocity'),
          list: const Key('incident-list'));
      expect(find.textContaining('downward_velocity'), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('history-n-1')),
          list: const Key('incident-list'));
      expect(find.byKey(const Key('history-n-1')), findsOneWidget);
    });

    appTest('confirm asks, records on the box, and reflects locally',
        (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 1
            ..missed = [makeMessage(id: 'n-1')];
        },
      );
      harness.api.incidentDetails = makeDetails();
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      await tester.tap(find.byKey(const Key('notification-n-1')));
      await tester.pumpAndSettle();
      await scrollTo(tester, find.byKey(const Key('confirm-button')),
          list: const Key('incident-list'));
      await tester.tap(find.byKey(const Key('confirm-button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('confirm-dialog-yes')));
      await tester.pumpAndSettle();
      expect(harness.api.resolved, ['i-1:confirm']);
      final repository = harness.container.read(notificationRepositoryProvider);
      expect(repository.byNotificationId('n-1')!.incidentStatus,
          IncidentStatus.confirmed);
    });

    appTest('offline box falls back to cached notification data',
        (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          cache.notifications['n-1'] = makeMessage(id: 'n-1');
          api.failSync = true;
          statusApi.failHealth = true;
          // no incidentDetails: fetch fails -> cached fallback
        },
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      await tester.tap(find.byKey(const Key('notification-n-1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('summary')), findsOneWidget,
          reason: 'essentials render from the cache');
      await scrollTo(tester, find.byKey(const Key('timeline-unavailable')),
          list: const Key('incident-list'));
      expect(find.byKey(const Key('timeline-unavailable')), findsOneWidget);
    });
  });

  group('cameras', () {
    appTest('lists cameras and explains unsupported restart', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Cameras');
      expect(find.byKey(const Key('camera-classroom-1')), findsOneWidget);
      await tester.tap(find.byKey(const Key('camera-classroom-1')));
      await tester.pumpAndSettle();
      expect(find.text('Frames processed'), findsOneWidget);
      await tester.tap(find.byKey(const Key('restart-classroom-1')));
      await tester.pumpAndSettle();
      expect(harness.statusApi.restarted, ['classroom-1']);
      expect(find.textContaining('automatic recovery'), findsOneWidget);
    });
  });

  group('health screen', () {
    appTest('shows subsystems and host metrics', (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Health');
      expect(find.byKey(const Key('subsystem-cameras')), findsOneWidget);
      expect(find.byKey(const Key('subsystem-notifications')), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('temperature')),
          list: const Key('health-list'));
      expect(find.text('52.0°C'), findsOneWidget);
      await scrollTo(tester, find.byKey(const Key('box-address')),
          list: const Key('health-list'));
      expect(find.byKey(const Key('box-address')), findsOneWidget);
    });
  });

  group('settings', () {
    appTest('theme change applies and persists', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Settings');
      await tester.tap(find.text('Dark'));
      await tester.pumpAndSettle();
      final app = tester.widget<MaterialApp>(find.byType(MaterialApp));
      expect(app.themeMode, ThemeMode.dark);
      expect(harness.cache.settingsJson, contains('"theme_mode":"dark"'));
    });

    appTest('language switch relocalizes the UI', (tester) async {
      await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Settings');
      await scrollTo(tester, find.byKey(const Key('lang-uz')),
          list: const Key('settings-list'));
      await tester.tap(find.byKey(const Key('lang-uz')));
      await tester.pumpAndSettle();
      expect(find.text('Sozlamalar'), findsWidgets,
          reason: 'the settings title is now Uzbek');
      await scrollTo(tester, find.byKey(const Key('lang-ru')),
          list: const Key('settings-list'));
      await tester.tap(find.byKey(const Key('lang-ru')));
      await tester.pumpAndSettle();
      expect(find.text('Настройки'), findsWidgets);
    });

    appTest('quiet hours toggle persists', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Settings');
      await tester.scrollUntilVisible(find.byKey(const Key('quiet-hours')), 300,
          scrollable: find.descendant(
              of: find.byKey(const Key('settings-list')),
              matching: find.byType(Scrollable)));
      await tester.tap(find.byKey(const Key('quiet-hours')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('quiet-from')), findsOneWidget);
      expect(
          harness.cache.settingsJson, contains('"quiet_hours_enabled":true'));
    });
  });

  group('live alerts', () {
    appTest('live critical notification raises the in-app alert',
        (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      harness.api.live!.add(makeMessage(id: 'n-live', severity: 'critical'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const Key('live-alert')), findsOneWidget);
      await tester.pumpAndSettle(const Duration(seconds: 7));
    });

    appTest('low severity below sensitivity stays quiet', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      harness.api.live!.add(makeMessage(id: 'n-low', severity: 'low'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byKey(const Key('live-alert')), findsNothing,
          reason: 'default sensitivity is medium');
      final repository = harness.container.read(notificationRepositoryProvider);
      expect(repository.byNotificationId('n-low'), isNotNull,
          reason: 'the alert is still stored, just not shouted');
    });
  });
}
