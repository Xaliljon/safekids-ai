import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fakes.dart';
import 'harness.dart';

/// Golden tests: the four core screens, fixed phone viewport, light theme.
/// Regenerate intentionally with: flutter test --update-goldens test/golden_test.dart
void main() {
  Future<void> pumpGolden(
    WidgetTester tester, {
    required Future<void> Function(WidgetTester) navigate,
    required String golden,
  }) async {
    await pumpApp(
      tester,
      surface: const Size(390, 844),
      setup: (api, statusApi, cache) {
        cache.box = testBox;
        api
          ..incidentDetails = makeDetails()
          ..syncCursor = 2
          ..missed = [
            makeMessage(
                id: 'n-1',
                severity: 'critical',
                timestamp: DateTime.utc(2026, 7, 6, 9, 0, 0)),
            makeMessage(
                id: 'n-2',
                incidentId: 'i-2',
                severity: 'medium',
                timestamp: DateTime.utc(2026, 7, 6, 8, 30, 0)),
          ];
      },
    );
    await tester.pumpAndSettle();
    await navigate(tester);
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/$golden.png'),
    );
  }

  appTest('dashboard golden', (tester) async {
    await pumpGolden(tester, navigate: (_) async {}, golden: 'dashboard');
  });

  appTest('notification center golden', (tester) async {
    await pumpGolden(
      tester,
      navigate: (tester) => goTab(tester, 'Alerts'),
      golden: 'notification_center',
    );
  });

  appTest('health screen golden', (tester) async {
    await pumpGolden(
      tester,
      navigate: (tester) => goTab(tester, 'Health'),
      golden: 'health',
    );
  });

  appTest('incident details golden', (tester) async {
    await pumpGolden(
      tester,
      navigate: (tester) async {
        await goTab(tester, 'Alerts');
        await tester.tap(find.byKey(const Key('notification-n-1')));
        await tester.pumpAndSettle();
      },
      golden: 'incident_details',
    );
  });
}
