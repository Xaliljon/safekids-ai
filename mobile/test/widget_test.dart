import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:safekids_mobile/src/app.dart';
import 'package:safekids_mobile/src/providers.dart';

import 'fakes.dart';

Future<(FakeDeviceApi, InMemoryCache)> pumpApp(
  WidgetTester tester, {
  void Function(FakeDeviceApi api, InMemoryCache cache)? setup,
}) async {
  final api = FakeDeviceApi();
  final cache = InMemoryCache();
  setup?.call(api, cache);
  final container = ProviderContainer(
    overrides: [
      deviceApiProvider.overrideWithValue(api),
      notificationCacheProvider.overrideWithValue(cache),
    ],
  );
  addTearDown(container.dispose);
  await container.read(connectionControllerProvider).initialize();
  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const GuardianApp()),
  );
  await tester.pump();
  return (api, cache);
}

void main() {
  testWidgets('unpaired app starts on the pairing screen and pairs',
      (tester) async {
    await pumpApp(tester);
    expect(find.text('Pair with Guardian Box'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('host-field')), '192.168.1.50');
    await tester.enterText(find.byKey(const Key('code-field')), '123456');
    await tester.tap(find.byKey(const Key('pair-button')));
    await tester.pumpAndSettle();
    expect(find.text('guardian-edge-box'), findsOneWidget,
        reason: 'paired: notification center shows the box name');
    expect(find.byKey(const Key('empty-state')), findsOneWidget);
  });

  testWidgets('pairing failure shows the error and stays put', (tester) async {
    final (api, _) = await pumpApp(tester);
    api.failPair = true;
    await tester.enterText(find.byKey(const Key('host-field')), '192.168.1.50');
    await tester.enterText(find.byKey(const Key('code-field')), '000000');
    await tester.tap(find.byKey(const Key('pair-button')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('pair-error')), findsOneWidget);
    expect(find.text('Pair with Guardian Box'), findsOneWidget);
  });

  testWidgets('notification center lists newest first with unread indicators',
      (tester) async {
    final (api, cache) = await pumpApp(tester);
    cache.box = testBox;
    api
      ..syncCursor = 2
      ..missed = [
        makeMessage(
          id: 'n-old',
          severity: 'medium',
          timestamp: DateTime.utc(2026, 7, 5, 12, 0, 1),
        ),
        makeMessage(
          id: 'n-new',
          timestamp: DateTime.utc(2026, 7, 5, 12, 0, 30),
        ),
      ];
    await tester.tap(find.byKey(const Key('pair-button')));
    await tester.pumpAndSettle();

    final list = find.byKey(const Key('notification-list'));
    expect(list, findsOneWidget);
    final tiles = tester.widgetList<ListTile>(find.byType(ListTile)).toList();
    expect(tiles, hasLength(2));
    final firstTitle = tester.firstWidget<Text>(
      find
          .descendant(
              of: find.byType(ListTile).first, matching: find.byType(Text))
          .first,
    );
    expect(firstTitle.data, contains('CRITICAL'),
        reason: 'newest (critical) first');
    expect(find.byKey(const Key('unread-dot')), findsNWidgets(2));
    expect(find.textContaining('PENDING REVIEW'), findsNWidgets(2));
    expect(find.textContaining('classroom-1'), findsNWidgets(2));
  });

  testWidgets('opening a notification shows details and confirm records it',
      (tester) async {
    final (api, cache) = await pumpApp(tester);
    cache.box = testBox;
    api
      ..syncCursor = 1
      ..missed = [makeMessage(id: 'n-1', incidentId: 'i-1')]
      ..incidentDetails = makeDetails(incidentId: 'i-1');
    await tester.tap(find.byKey(const Key('pair-button')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('notification-n-1')));
    await tester.pumpAndSettle();
    expect(find.text('Incident review'), findsOneWidget);
    expect(find.byKey(const Key('summary')), findsOneWidget);
    expect(find.textContaining('downward_velocity'), findsOneWidget,
        reason: 'timeline shows explainable signals');
    expect(find.textContaining('i-1'), findsWidgets);

    await tester.tap(find.byKey(const Key('confirm-button')));
    await tester.pumpAndSettle();
    expect(api.resolved, ['i-1:confirm']);
    expect(find.textContaining('CONFIRMED'), findsOneWidget,
        reason: 'status reflects the box-recorded decision');
    expect(find.byKey(const Key('unread-dot')), findsNothing,
        reason: 'opened notification is read');
  });

  testWidgets('dismiss works and reviewed incidents lose their buttons',
      (tester) async {
    final (api, cache) = await pumpApp(tester);
    cache.box = testBox;
    api
      ..syncCursor = 1
      ..missed = [makeMessage(id: 'n-1', incidentId: 'i-1')]
      ..incidentDetails = makeDetails(incidentId: 'i-1');
    await tester.tap(find.byKey(const Key('pair-button')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('notification-n-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('dismiss-button')));
    await tester.pumpAndSettle();
    expect(api.resolved, ['i-1:dismiss']);

    await tester.tap(find.byKey(const Key('notification-n-1')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('confirm-button')), findsNothing);
    expect(find.byKey(const Key('reviewed-label')), findsOneWidget);
  });

  testWidgets('offline: cached notifications stay visible with a banner',
      (tester) async {
    final api = FakeDeviceApi()..failSync = true;
    final cache = InMemoryCache()..box = testBox;
    cache.notifications['n-cached'] = makeMessage(id: 'n-cached');
    final container = ProviderContainer(
      overrides: [
        deviceApiProvider.overrideWithValue(api),
        notificationCacheProvider.overrideWithValue(cache),
      ],
    );
    await container.read(connectionControllerProvider).initialize();
    await tester.pumpWidget(
      UncontrolledProviderScope(
          container: container, child: const GuardianApp()),
    );
    await tester.pump(const Duration(milliseconds: 50));
    await tester.pump();
    expect(find.byKey(const Key('offline-banner')), findsOneWidget);
    expect(find.byKey(const Key('notification-n-cached')), findsOneWidget,
        reason: 'cached notifications remain visible offline');
    // Tear down inside the body: the reconnect timer must not outlive the test.
    await tester.pumpWidget(const SizedBox());
    container.dispose();
    await tester.pump();
  });
}
