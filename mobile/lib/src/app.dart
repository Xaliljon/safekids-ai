import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'application/connection_controller.dart';
import '../l10n/generated/app_localizations.dart';
import 'presentation/cameras_screen.dart';
import 'presentation/dashboard_screen.dart';
import 'presentation/health_screen.dart';
import 'presentation/incident_details_screen.dart';
import 'presentation/notification_center_screen.dart';
import 'presentation/pairing_wizard_screen.dart';
import 'presentation/settings_screen.dart';
import 'presentation/shell.dart';
import 'providers.dart';

/// Created once per app lifetime — rebuilds must never reset navigation.
/// Pairing state changes route via [GoRouter.refreshListenable]/redirect,
/// not by recreating the router.
final routerProvider = Provider<GoRouter>((ref) {
  final connection = ref.watch(connectionControllerProvider.notifier);
  return GoRouter(
    initialLocation:
        connection.state == BoxConnectionState.unpaired ? '/pair' : '/',
    refreshListenable: connection,
    redirect: (context, state) {
      final unpaired = connection.state == BoxConnectionState.unpaired;
      final onPairing = state.matchedLocation == '/pair';
      if (unpaired && !onPairing) {
        return '/pair';
      }
      if (!unpaired && onPairing) {
        return '/';
      }
      return null;
    },
    routes: [
      GoRoute(path: '/pair', builder: (_, __) => const PairingWizardScreen()),
      GoRoute(
        path: '/incident/:id',
        builder: (_, state) =>
            IncidentDetailsScreen(notificationId: state.pathParameters['id']!),
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: '/', builder: (_, __) => const DashboardScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
                path: '/alerts',
                builder: (_, __) => const NotificationCenterScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
                path: '/cameras', builder: (_, __) => const CamerasScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/health', builder: (_, __) => const HealthScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
                path: '/settings', builder: (_, __) => const SettingsScreen()),
          ]),
        ],
      ),
    ],
  );
});

ThemeData _theme(Brightness brightness) => ThemeData(
      colorScheme: ColorScheme.fromSeed(
        seedColor: const Color(0xFF1F6E43),
        brightness: brightness,
      ),
      useMaterial3: true,
    );

class GuardianApp extends ConsumerWidget {
  const GuardianApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsControllerProvider).settings;
    return MaterialApp.router(
      onGenerateTitle: (context) => AppLocalizations.of(context).appTitle,
      debugShowCheckedModeBanner: false,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      themeMode: settings.themeMode,
      locale: settings.locale,
      localizationsDelegates: AppLocalizations.localizationsDelegates,
      supportedLocales: AppLocalizations.supportedLocales,
      routerConfig: ref.watch(routerProvider),
    );
  }
}
