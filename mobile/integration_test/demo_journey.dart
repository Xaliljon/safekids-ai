// Sprint 15 demo journey — drives the real app against a live Guardian Box
// for the sprint video. Not a CI test: needs a running box + health surface.
//
//   flutter test integration_test/demo_journey.dart -d <simulator> \
//     --dart-define=DEMO_HOST=127.0.0.1 --dart-define=DEMO_CODE=<code>

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:safekids_mobile/main.dart' as app;

const demoHost = String.fromEnvironment('DEMO_HOST', defaultValue: '127.0.0.1');
const demoCode = String.fromEnvironment('DEMO_CODE');

Future<void> hold(WidgetTester tester, double seconds) async {
  final end = DateTime.now().add(Duration(milliseconds: (seconds * 1000).round()));
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}

Future<void> settle(WidgetTester tester) async {
  await tester.pumpAndSettle(const Duration(milliseconds: 200));
}

Future<void> tab(WidgetTester tester, IconData icon) async {
  await tester.tap(find.descendant(
    of: find.byType(NavigationBar),
    matching: find.byIcon(icon),
  ));
  await settle(tester);
}

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('sprint 15 demo journey', (tester) async {
    await app.main();
    await settle(tester);
    await hold(tester, 2);

    // ------------------------------------------------ pairing wizard
    if (find.byKey(const Key('pairing-wizard')).evaluate().isNotEmpty) {
      await tester.tap(find.byKey(const Key('manual-entry-button')));
      await settle(tester);
      await tester.enterText(find.byKey(const Key('host-field')), demoHost);
      await hold(tester, 0.8);
      await tester.enterText(find.byKey(const Key('code-field')), demoCode);
      await hold(tester, 0.8);
      await tester.drag(
          find.byKey(const Key('pairing-wizard')), const Offset(0, -350));
      await settle(tester);
      await tester.tap(find.byKey(const Key('pair-button')));
      await settle(tester);
    }

    // ---------------------------------------------------- dashboard
    await hold(tester, 6); // status, cameras, gauges; live alert arrives

    // ------------------------------------------------------- alerts
    await tab(tester, Icons.notifications_outlined);
    await hold(tester, 3);

    // ----------------------------------------------- incident review
    final tiles = find.descendant(
      of: find.byKey(const Key('notification-list')),
      matching: find.byType(ListTile),
    );
    if (tiles.evaluate().isNotEmpty) {
      await tester.tap(tiles.first);
      await settle(tester);
      await hold(tester, 2.5);
      final list = find
          .descendant(
              of: find.byKey(const Key('incident-list')),
              matching: find.byType(Scrollable))
          .first;
      await tester.drag(list, const Offset(0, -450));
      await settle(tester);
      await hold(tester, 2.5);
      await tester.drag(list, const Offset(0, 450));
      await settle(tester);
      if (find.byKey(const Key('confirm-button')).evaluate().isNotEmpty) {
        await tester.tap(find.byKey(const Key('confirm-button')));
        await settle(tester);
        await hold(tester, 1.5);
        await tester.tap(find.byKey(const Key('confirm-dialog-yes')));
        await settle(tester);
        await hold(tester, 2);
      }
    }
    if (find.byIcon(Icons.arrow_back).evaluate().isNotEmpty) {
      await tester.tap(find.byIcon(Icons.arrow_back));
      await settle(tester);
    }

    // ------------------------------------------------------ cameras
    await tab(tester, Icons.videocam_outlined);
    await hold(tester, 1.5);
    if (find.byKey(const Key('camera-classroom-1')).evaluate().isNotEmpty) {
      await tester.tap(find.byKey(const Key('camera-classroom-1')));
      await settle(tester);
      await hold(tester, 2.5);
    }

    // ------------------------------------------------------- health
    await tab(tester, Icons.monitor_heart_outlined);
    await hold(tester, 2);
    final healthScroll = find
        .descendant(
            of: find.byKey(const Key('health-list')),
            matching: find.byType(Scrollable))
        .first;
    await tester.drag(healthScroll, const Offset(0, -400));
    await settle(tester);
    await hold(tester, 2);

    // ------------------------------------- settings: switch to Uzbek
    await tab(tester, Icons.settings_outlined);
    await hold(tester, 1.5);
    await tester.tap(find.byKey(const Key('lang-uz')));
    await settle(tester);
    await hold(tester, 2);

    // ------------------------------------------- dashboard in Uzbek
    await tab(tester, Icons.space_dashboard_outlined);
    await hold(tester, 3.5);
  });
}
