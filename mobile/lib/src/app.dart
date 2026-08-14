import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'application/connection_controller.dart';
import '../l10n/generated/app_localizations.dart';
import 'presentation/cameras_screen.dart';
import 'presentation/dashboard_screen.dart';
import 'presentation/design.dart';
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

/// Material's theme, driven entirely by the design system (see design.dart).
///
/// Material components are re-pointed at the comp's palette rather than a
/// seed colour: the comp's warm paper and single orange action are a
/// deliberate scheme, and a generated tonal palette would quietly overrule
/// it. [SkColors] rides along as a theme extension for everything Material
/// has no slot for — the four severity tones especially.
ThemeData _theme(Brightness brightness) {
  final sk = brightness == Brightness.dark ? SkColors.dark : SkColors.light;
  final base = ThemeData(brightness: brightness, useMaterial3: true);
  return base.copyWith(
    extensions: [sk],
    scaffoldBackgroundColor: sk.surface,
    dividerColor: sk.divider,
    colorScheme: ColorScheme(
      brightness: brightness,
      primary: sk.accent,
      onPrimary: sk.onAccent,
      secondary: sk.accent,
      onSecondary: sk.onAccent,
      error: sk.danger,
      onError: sk.onAccent,
      surface: sk.surface,
      onSurface: sk.textPrimary,
      surfaceContainerHighest: sk.card,
      outline: sk.border,
      outlineVariant: sk.divider,
    ),
    textTheme: base.textTheme.apply(
      bodyColor: sk.textPrimary,
      displayColor: sk.textPrimary,
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: sk.surface,
      surfaceTintColor: Colors.transparent,
      foregroundColor: sk.textPrimary,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: SkType.pushTitle.copyWith(color: sk.textPrimary),
    ),
    cardTheme: CardThemeData(
      color: sk.card,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(SkRadius.card),
        side: BorderSide(color: sk.border),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: sk.textPrimary,
      contentTextStyle: SkType.detail.copyWith(color: sk.surface),
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(SkRadius.control),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: sk.card,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(SkRadius.card),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: sk.accent,
        foregroundColor: sk.onAccent,
        textStyle: SkType.rowTitle,
        padding: const EdgeInsets.symmetric(vertical: 13),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(SkRadius.control),
        ),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: sk.textPrimary,
        backgroundColor: sk.card,
        textStyle: SkType.rowTitle,
        padding: const EdgeInsets.symmetric(vertical: 13),
        side: BorderSide(color: sk.borderStrong),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(SkRadius.control),
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: sk.accent,
        textStyle: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600),
        // The comp's "View all" is text on the section line, not a button
        // sitting above it: no padding, no minimum tap box of its own.
        padding: const EdgeInsets.symmetric(horizontal: 4),
        minimumSize: Size.zero,
        tapTargetSize: MaterialTapTargetSize.shrinkWrap,
        visualDensity: VisualDensity.compact,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: sk.fill,
      hintStyle: TextStyle(fontSize: 13.5, color: sk.textFaint),
      // Tight vertical padding puts a floating label on top of whatever
      // field sits above — the pairing form stacks four of them.
      contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 16),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(SkRadius.control),
        borderSide: BorderSide(color: sk.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(SkRadius.control),
        borderSide: BorderSide(color: sk.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(SkRadius.control),
        borderSide: BorderSide(color: sk.accent),
      ),
    ),
    // A progress track must never inherit its colour. Material defaults the
    // linear track to a surface container, which this scheme paints white —
    // white track on a white card, so a 47% AI signal drew exactly like a
    // 100% one. Confidence has to be visible to be reviewed (docs/04).
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: sk.accent,
      linearTrackColor: sk.track,
      circularTrackColor: sk.track,
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: sk.card,
      surfaceTintColor: Colors.transparent,
      indicatorColor: Colors.transparent,
      elevation: 0,
      height: 62,
      labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
      labelTextStyle: WidgetStateProperty.resolveWith(
        (states) => SkType.navLabel.copyWith(
          color: states.contains(WidgetState.selected)
              ? sk.textPrimary
              : sk.textFaint,
        ),
      ),
      iconTheme: WidgetStateProperty.resolveWith(
        (states) => IconThemeData(
          size: 21,
          color: states.contains(WidgetState.selected)
              ? sk.textPrimary
              : sk.textFaint,
        ),
      ),
    ),
  );
}

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
