import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:safekids_mobile/src/app.dart';
import 'package:safekids_mobile/src/presentation/evidence_player.dart';
import 'package:safekids_mobile/src/providers.dart';

import 'fakes.dart';

/// Everything a widget test needs to drive the app with fakes.
class Harness {
  Harness(
      this.api, this.statusApi, this.cache, this.evidenceCache, this.container);

  final FakeDeviceApi api;
  final FakeBoxStatusApi statusApi;
  final InMemoryCache cache;
  final InMemoryEvidenceCache evidenceCache;
  final ProviderContainer container;
}

Harness? _current;

/// Unmount the app and dispose controllers so no reconnect/poll/snackbar
/// timer outlives the test (flutter_test forbids pending timers).
Future<void> closeApp(WidgetTester tester) async {
  final harness = _current;
  _current = null;
  if (harness == null) {
    return;
  }
  await tester.pumpWidget(const SizedBox()); // cancels UI-owned timers
  harness.container.dispose(); // cancels controller-owned timers
  await tester.pump();
}

/// [testWidgets] wrapper that always closes the app, even on failure.
void appTest(
  String description,
  Future<void> Function(WidgetTester tester) body,
) {
  testWidgets(description, (tester) async {
    try {
      await body(tester);
    } finally {
      await closeApp(tester);
    }
  });
}

/// Pump the full app (router, l10n, theming) over scriptable fakes.
/// The default surface is a tall phone so whole screens are hittable;
/// golden tests pass their own fixed [surface].
Future<Harness> pumpApp(
  WidgetTester tester, {
  void Function(
          FakeDeviceApi api, FakeBoxStatusApi statusApi, InMemoryCache cache)?
      setup,
  Size surface = const Size(420, 1600),
}) async {
  await tester.binding.setSurfaceSize(surface);
  addTearDown(() => tester.binding.setSurfaceSize(null));
  final api = FakeDeviceApi();
  final statusApi = FakeBoxStatusApi();
  final cache = InMemoryCache();
  final evidenceCache = InMemoryEvidenceCache();
  setup?.call(api, statusApi, cache);
  final container = ProviderContainer(
    overrides: [
      deviceApiProvider.overrideWithValue(api),
      boxStatusApiProvider.overrideWithValue(statusApi),
      notificationCacheProvider.overrideWithValue(cache),
      evidenceCacheProvider.overrideWithValue(evidenceCache),
      // Widget tests have no platform video codecs: stub the player.
      evidencePlayerBuilderProvider.overrideWithValue(
        (path, key) => SizedBox(
          key: key,
          height: 120,
          child: Center(child: Text('player:$path')),
        ),
      ),
      // No periodic timer in widget tests; polls happen via refresh().
      statusPollIntervalProvider.overrideWithValue(Duration.zero),
    ],
  );
  await container.read(settingsControllerProvider).initialize();
  await container.read(connectionControllerProvider).initialize();
  await container.read(statusControllerProvider).initialize();
  await tester.pumpWidget(
    UncontrolledProviderScope(container: container, child: const GuardianApp()),
  );
  await tester.pump();
  final harness = Harness(api, statusApi, cache, evidenceCache, container);
  _current = harness;
  return harness;
}

/// Pair via the manual-entry form (the wizard's fallback path).
Future<void> pairManually(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('manual-entry-button')));
  await tester.pumpAndSettle();
  await tester.enterText(find.byKey(const Key('host-field')), '192.168.1.50');
  await tester.enterText(find.byKey(const Key('code-field')), '123456');
  await tester.tap(find.byKey(const Key('pair-button')));
  await tester.pumpAndSettle();
}

/// Switch bottom-navigation tab by localized label.
Future<void> goTab(WidgetTester tester, String label) async {
  await tester.tap(find.descendant(
    of: find.byType(NavigationBar),
    matching: find.text(label),
  ));
  await tester.pumpAndSettle();
}

/// Scroll a keyed list until the target is built and visible.
Future<void> scrollTo(
  WidgetTester tester,
  Finder target, {
  required Key list,
}) async {
  await tester.scrollUntilVisible(
    target,
    200,
    // .first: text fields nest their own Scrollable inside the list.
    scrollable: find
        .descendant(of: find.byKey(list), matching: find.byType(Scrollable))
        .first,
  );
  await tester.pumpAndSettle();
}
