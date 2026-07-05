import 'package:flutter/material.dart' show ThemeMode;
import 'package:flutter_test/flutter_test.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/application/settings_controller.dart';
import 'package:safekids_mobile/src/application/status_controller.dart';

import 'fakes.dart';

void main() {
  group('AppSettings', () {
    test('quiet hours handle overnight ranges', () {
      const settings = AppSettings(
        quietHoursEnabled: true,
        quietStartMinutes: 22 * 60,
        quietEndMinutes: 7 * 60,
      );
      expect(settings.isQuietAt(DateTime(2026, 7, 6, 23, 30)), isTrue);
      expect(settings.isQuietAt(DateTime(2026, 7, 6, 3, 0)), isTrue);
      expect(settings.isQuietAt(DateTime(2026, 7, 6, 12, 0)), isFalse);
    });

    test('quiet hours handle same-day ranges', () {
      const settings = AppSettings(
        quietHoursEnabled: true,
        quietStartMinutes: 13 * 60,
        quietEndMinutes: 15 * 60,
      );
      expect(settings.isQuietAt(DateTime(2026, 7, 6, 14, 0)), isTrue);
      expect(settings.isQuietAt(DateTime(2026, 7, 6, 16, 0)), isFalse);
    });

    test('critical always alerts — quiet hours and switches never mute it', () {
      const settings = AppSettings(
        notificationsEnabled: false,
        quietHoursEnabled: true,
        quietStartMinutes: 0,
        quietEndMinutes: 24 * 60,
        minAlertSeverity: Severity.critical,
      );
      expect(
          settings.shouldAlert(Severity.critical, DateTime(2026, 7, 6, 2, 0)),
          isTrue);
      expect(settings.shouldAlert(Severity.high, DateTime(2026, 7, 6, 2, 0)),
          isFalse);
    });

    test('sensitivity is a minimum severity', () {
      const settings = AppSettings(minAlertSeverity: Severity.high);
      final noon = DateTime(2026, 7, 6, 12, 0);
      expect(settings.shouldAlert(Severity.medium, noon), isFalse);
      expect(settings.shouldAlert(Severity.high, noon), isTrue);
    });

    test('round-trips through json, tolerating garbage', () {
      const settings = AppSettings(
        themeMode: ThemeMode.dark,
        localeCode: 'uz',
        minAlertSeverity: Severity.low,
        quietHoursEnabled: true,
      );
      final restored = AppSettings.fromJson(settings.toJson());
      expect(restored.themeMode, ThemeMode.dark);
      expect(restored.localeCode, 'uz');
      expect(restored.minAlertSeverity, Severity.low);
      expect(restored.quietHoursEnabled, isTrue);

      final defaulted = AppSettings.fromJson(
          const {'theme_mode': 'purple', 'min_alert_severity': 'apocalyptic'});
      expect(defaulted.themeMode, ThemeMode.system);
      expect(defaulted.minAlertSeverity, Severity.medium);
    });
  });

  group('SettingsController', () {
    test('persists on update and restores on initialize', () async {
      final cache = InMemoryCache();
      final controller = SettingsController(cache);
      await controller.initialize();
      await controller
          .update(controller.settings.copyWith(localeCode: () => 'ru'));
      expect(cache.settingsJson, contains('"locale":"ru"'));

      final second = SettingsController(cache);
      await second.initialize();
      expect(second.settings.localeCode, 'ru');
    });

    test('corrupt settings reset to defaults instead of crashing', () async {
      final cache = InMemoryCache()..settingsJson = '{not json';
      final controller = SettingsController(cache);
      await controller.initialize();
      expect(controller.settings.themeMode, ThemeMode.system);
    });
  });

  group('StatusController', () {
    test('successful refresh caches the snapshot for offline use', () async {
      final cache = InMemoryCache();
      final api = FakeBoxStatusApi();
      final controller = StatusController(api: api, cache: cache);
      controller.start('192.168.1.50');
      await controller.refresh();
      expect(controller.live, isTrue);
      expect(controller.health!.status, BoxStatus.ok);
      expect(controller.health!.cameras.single.cameraId, 'classroom-1');
      expect(controller.metrics!.inferenceFps, 6.0);
      expect(cache.healthJson, isNotNull);
      controller.dispose();
    });

    test('failed refresh keeps the last snapshot and flips live off', () async {
      final cache = InMemoryCache();
      final api = FakeBoxStatusApi();
      final controller = StatusController(api: api, cache: cache);
      controller.start('192.168.1.50');
      await controller.refresh();
      api.failHealth = true;
      await controller.refresh();
      expect(controller.live, isFalse);
      expect(controller.health, isNotNull, reason: 'never blank the screen');
      controller.dispose();
    });

    test('initialize restores the cached snapshot before any poll', () async {
      final cache = InMemoryCache();
      final api = FakeBoxStatusApi();
      final first = StatusController(api: api, cache: cache);
      first.start('192.168.1.50');
      await first.refresh();
      first.dispose();

      final offlineApi = FakeBoxStatusApi()..failHealth = true;
      final second = StatusController(api: offlineApi, cache: cache);
      await second.initialize();
      expect(second.health, isNotNull);
      expect(second.health!.cameras.single.cameraId, 'classroom-1');
      expect(second.live, isFalse);
      second.dispose();
    });

    test('restartCamera maps unsupported and failure outcomes', () async {
      final api = FakeBoxStatusApi();
      final controller = StatusController(api: api, cache: InMemoryCache());
      expect(await controller.restartCamera(testBox, 'classroom-1'),
          'unsupported');
      api.restartBehavior = Exception('boom');
      expect(await controller.restartCamera(testBox, 'classroom-1'), 'failed');
      api.restartBehavior = 'ok';
      expect(await controller.restartCamera(testBox, 'classroom-1'), isNull);
      expect(api.restarted, hasLength(3));
      controller.dispose();
    });
  });
}
