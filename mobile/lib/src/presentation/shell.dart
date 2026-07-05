import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';

/// Bottom-navigation shell around the five main screens. Also the single
/// place a live notification becomes an in-app alert — filtered through
/// the director's settings (sensitivity, quiet hours), with CRITICAL
/// always breaking through.
class AppShell extends ConsumerWidget {
  const AppShell({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final unread = ref.watch(
        notificationRepositoryProvider.select((repo) => repo.unreadCount));

    ref.listen(notificationRepositoryProvider, (_, repository) {
      final live = repository.lastLive;
      if (live == null) {
        return;
      }
      repository.lastLive = null;
      final settings = ref.read(settingsControllerProvider).settings;
      if (!settings.shouldAlert(live.severity, DateTime.now())) {
        return;
      }
      final messenger = ScaffoldMessenger.of(context);
      messenger.hideCurrentSnackBar();
      messenger.showSnackBar(SnackBar(
        key: const Key('live-alert'),
        backgroundColor: severityColor(live.severity),
        duration: const Duration(seconds: 6),
        behavior: SnackBarBehavior.floating,
        content: Text(
          '${l10n.potentialFall} — ${severityLabel(l10n, live.severity)} · '
          '${live.cameraId}',
          style: const TextStyle(color: Colors.white),
        ),
        action: SnackBarAction(
          label: l10n.dashViewAll,
          textColor: Colors.white,
          onPressed: () => context.push('/incident/${live.notificationId}'),
        ),
      ));
    });

    return Scaffold(
      body: shell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        onDestinationSelected: (index) => shell.goBranch(
          index,
          initialLocation: index == shell.currentIndex,
        ),
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.space_dashboard_outlined),
            selectedIcon: const Icon(Icons.space_dashboard),
            label: l10n.navDashboard,
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unread > 0,
              label: Text('$unread'),
              child: const Icon(Icons.notifications_outlined),
            ),
            selectedIcon: Badge(
              isLabelVisible: unread > 0,
              label: Text('$unread'),
              child: const Icon(Icons.notifications),
            ),
            label: l10n.navAlerts,
          ),
          NavigationDestination(
            icon: const Icon(Icons.videocam_outlined),
            selectedIcon: const Icon(Icons.videocam),
            label: l10n.navCameras,
          ),
          NavigationDestination(
            icon: const Icon(Icons.monitor_heart_outlined),
            selectedIcon: const Icon(Icons.monitor_heart),
            label: l10n.navHealth,
          ),
          NavigationDestination(
            icon: const Icon(Icons.settings_outlined),
            selectedIcon: const Icon(Icons.settings),
            label: l10n.navSettings,
          ),
        ],
      ),
    );
  }
}
