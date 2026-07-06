import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:safekids_mobile/src/application/evidence_cache.dart';
import 'package:safekids_mobile/src/application/evidence_controller.dart';

import 'fakes.dart';
import 'harness.dart';

void main() {
  group('FileEvidenceCache', () {
    late Directory directory;
    late FileEvidenceCache cache;

    setUp(() async {
      directory = await Directory.systemTemp.createTemp('guardian-evidence');
      cache = FileEvidenceCache(directory);
    });

    tearDown(() async {
      if (await directory.exists()) {
        await directory.delete(recursive: true);
      }
    });

    test('put/pathFor round-trip and clear', () async {
      expect(await cache.pathFor('e-1-overlay.mp4'), isNull);
      final path = await cache.put('e-1-overlay.mp4', List.filled(100, 1));
      expect(await cache.pathFor('e-1-overlay.mp4'), path);
      expect(await cache.totalBytes(), 100);
      await cache.clear();
      expect(await cache.pathFor('e-1-overlay.mp4'), isNull);
    });

    test('enforceLimit removes least-recently-used first', () async {
      await cache.put('old.mp4', List.filled(600, 1));
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      await cache.put('new.mp4', List.filled(600, 2));
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      await cache.pathFor('old.mp4'); // touch: old becomes most recent
      await cache.enforceLimit(800);
      expect(await cache.pathFor('old.mp4'), isNotNull,
          reason: 'recently used survives');
      expect(await cache.pathFor('new.mp4'), isNull);
      expect(await cache.totalBytes(), lessThanOrEqualTo(800));
    });

    test('enforceLimit is a no-op under the limit', () async {
      await cache.put('a.mp4', List.filled(100, 1));
      await cache.enforceLimit(1000);
      expect(await cache.pathFor('a.mp4'), isNotNull);
    });
  });

  group('EvidenceController', () {
    EvidenceController controller({
      required FakeDeviceApi api,
      required InMemoryEvidenceCache cache,
      String incidentId = 'i-1',
      bool paired = true,
    }) {
      return EvidenceController(
        api: api,
        cache: cache,
        box: paired ? testBox : null,
        incidentId: incidentId,
        cacheLimitBytes: 1024 * 1024,
      );
    }

    test('no evidence on the box -> none', () async {
      final subject =
          controller(api: FakeDeviceApi(), cache: InMemoryEvidenceCache());
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.none);
    });

    test('pending export -> preparing; failed export -> failed', () async {
      final api = FakeDeviceApi()
        ..evidence = [makeEvidenceRecord(status: 'pending')];
      final subject = controller(api: api, cache: InMemoryEvidenceCache());
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.preparing);

      api.evidence = [makeEvidenceRecord(status: 'failed', variants: [])];
      final failed = controller(api: api, cache: InMemoryEvidenceCache());
      await failed.initialize();
      expect(failed.state, EvidencePlaybackState.failed);
    });

    test('ready -> available -> download with progress -> cached', () async {
      final api = FakeDeviceApi()..evidence = [makeEvidenceRecord()];
      final cache = InMemoryEvidenceCache();
      final subject = controller(api: api, cache: cache);
      final progressSeen = <double>[];
      subject.addListener(() => progressSeen.add(subject.progress));
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.available);
      expect(subject.thumbnail, isNotNull, reason: 'poster frame fetched');
      expect(subject.variant, 'overlay', reason: 'AI view first');

      await subject.download();
      expect(subject.state, EvidencePlaybackState.cached);
      expect(subject.videoPath, isNotNull);
      expect(progressSeen, contains(0.5));
      expect(cache.files.keys, contains('e-1-overlay.mp4'));
    });

    test('already-cached clip short-circuits to cached on init', () async {
      final api = FakeDeviceApi()..evidence = [makeEvidenceRecord()];
      final cache = InMemoryEvidenceCache();
      await cache.put('e-1-overlay.mp4', [1, 2, 3]);
      final subject = controller(api: api, cache: cache);
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.cached);
    });

    test('switchVariant downloads the other view and caches both', () async {
      final api = FakeDeviceApi()..evidence = [makeEvidenceRecord()];
      final cache = InMemoryEvidenceCache();
      final subject = controller(api: api, cache: cache);
      await subject.initialize();
      await subject.download();
      await subject.switchVariant('original');
      expect(subject.state, EvidencePlaybackState.cached);
      expect(api.downloadedVariants, ['overlay', 'original']);
      await subject.switchVariant('overlay'); // back: served from cache
      expect(api.downloadedVariants, hasLength(2), reason: 'no re-download');
      expect(subject.state, EvidencePlaybackState.cached);
    });

    test('failed download returns to available (retryable)', () async {
      final api = FakeDeviceApi()..evidence = [makeEvidenceRecord()];
      final subject = controller(api: api, cache: InMemoryEvidenceCache());
      await subject.initialize();
      api.failEvidence = true;
      await subject.download();
      expect(subject.state, EvidencePlaybackState.available);
    });

    test('box unreachable -> none (list is still reviewable)', () async {
      final api = FakeDeviceApi()..failEvidence = true;
      final subject = controller(api: api, cache: InMemoryEvidenceCache());
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.none);
    });

    test('unpaired -> none', () async {
      final subject = controller(
          api: FakeDeviceApi(), cache: InMemoryEvidenceCache(), paired: false);
      await subject.initialize();
      expect(subject.state, EvidencePlaybackState.none);
    });
  });

  group('evidence in incident details (widget)', () {
    Future<Harness> openIncident(WidgetTester tester,
        {void Function(FakeDeviceApi api)? arrange}) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) {
          cache.box = testBox;
          api
            ..syncCursor = 1
            ..missed = [makeMessage(id: 'n-1')]
            ..incidentDetails = makeDetails();
          arrange?.call(api);
        },
      );
      await tester.pumpAndSettle();
      await goTab(tester, 'Alerts');
      await tester.tap(find.byKey(const Key('notification-n-1')));
      // Bounded pumps: evidence states may show endless spinners, which
      // pumpAndSettle would wait on forever.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump(const Duration(milliseconds: 400));
      return harness;
    }

    appTest('shows download, then the player after downloading',
        (tester) async {
      await openIncident(tester,
          arrange: (api) => api.evidence = [makeEvidenceRecord()]);
      expect(find.byKey(const Key('evidence-available')), findsOneWidget);
      expect(find.byKey(const Key('evidence-thumbnail')), findsOneWidget);
      expect(find.byKey(const Key('evidence-facts')), findsOneWidget);
      await tester.tap(find.byKey(const Key('evidence-download')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.byKey(const Key('evidence-player')), findsOneWidget);
      expect(find.byKey(const Key('evidence-video-overlay')), findsOneWidget);
    });

    appTest('switches between AI analysis and original', (tester) async {
      await openIncident(tester,
          arrange: (api) => api.evidence = [makeEvidenceRecord()]);
      await tester.tap(find.byKey(const Key('evidence-download')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      await tester.tap(find.text('Original'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.byKey(const Key('evidence-video-original')), findsOneWidget);
    });

    appTest('shows preparing while the box exports', (tester) async {
      await openIncident(tester,
          arrange: (api) =>
              api.evidence = [makeEvidenceRecord(status: 'pending')]);
      expect(find.byKey(const Key('evidence-preparing')), findsOneWidget);
    });

    appTest('shows the AI signals section from the timeline', (tester) async {
      await openIncident(tester,
          arrange: (api) => api.evidence = [makeEvidenceRecord()]);
      expect(find.byKey(const Key('ai-signals')), findsOneWidget);
      expect(
          find.text('downward_velocity'), findsWidgets); // signals + timeline
    });

    appTest('no evidence -> honest empty state', (tester) async {
      await openIncident(tester);
      expect(find.byKey(const Key('evidence-none')), findsOneWidget);
    });
  });

  group('settings evidence cache (widget)', () {
    appTest('cache size persists and clear empties the cache', (tester) async {
      final harness = await pumpApp(
        tester,
        setup: (api, statusApi, cache) => cache.box = testBox,
      );
      await tester.pumpAndSettle();
      await harness.evidenceCache.put('stale.mp4', [1, 2, 3]);
      await goTab(tester, 'Settings');
      await scrollTo(tester, find.byKey(const Key('evidence-cache-size')),
          list: const Key('settings-list'));
      await tester.tap(find.text('500 MB'));
      await tester.pumpAndSettle();
      expect(harness.cache.settingsJson, contains('"evidence_cache_mb":500'));
      await scrollTo(tester, find.byKey(const Key('clear-evidence-cache')),
          list: const Key('settings-list'));
      await tester.tap(find.byKey(const Key('clear-evidence-cache')));
      await tester.pumpAndSettle();
      expect(await harness.evidenceCache.totalBytes(), 0);
      await tester.pump(const Duration(seconds: 5)); // let the snackbar expire
    });
  });
}
