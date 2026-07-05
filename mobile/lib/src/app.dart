import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'application/connection_controller.dart';
import 'presentation/incident_details_screen.dart';
import 'presentation/notification_center_screen.dart';
import 'presentation/pairing_screen.dart';
import 'providers.dart';

/// Created once per app lifetime — rebuilds must never reset navigation.
final routerProvider = Provider<GoRouter>((ref) {
  final paired = ref.read(connectionControllerProvider).state !=
      BoxConnectionState.unpaired;
  return GoRouter(
    initialLocation: paired ? '/' : '/pair',
    routes: [
      GoRoute(path: '/', builder: (_, __) => const NotificationCenterScreen()),
      GoRoute(path: '/pair', builder: (_, __) => const PairingScreen()),
      GoRoute(
        path: '/incident/:id',
        builder: (_, state) =>
            IncidentDetailsScreen(notificationId: state.pathParameters['id']!),
      ),
    ],
  );
});

class GuardianApp extends ConsumerWidget {
  const GuardianApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MaterialApp.router(
      title: 'Guardian SafeKids',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1F6E43)),
        useMaterial3: true,
      ),
      routerConfig: ref.watch(routerProvider),
    );
  }
}

/// Shared severity color scale (calm green never appears on alerts).
Color severityColor(String severityName) => switch (severityName) {
      'low' => Colors.blueGrey,
      'medium' => Colors.orange,
      'high' => Colors.deepOrange,
      'critical' => Colors.red.shade700,
      _ => Colors.grey,
    };
