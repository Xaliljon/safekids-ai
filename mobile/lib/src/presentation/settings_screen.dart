import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:guardian_core/guardian_core.dart';

import '../application/settings_controller.dart';
import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';
import 'widgets.dart';

/// Device-local preferences: theme, language, alerting. Nothing here
/// changes the box's detection behavior — presentation only.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final controller = ref.watch(settingsControllerProvider);
    final settings = controller.settings;
    final connection = ref.watch(connectionControllerProvider);

    Future<void> update(AppSettings next) =>
        ref.read(settingsControllerProvider).update(next);

    return Scaffold(
      appBar: AppBar(title: Text(l10n.settingsTitle)),
      body: ListView(
        key: const Key('settings-list'),
        children: [
          // -------------------------------------------------------- theme
          SectionHeader(l10n.themeSection),
          PanelCard(
            child: SegmentedButton<ThemeMode>(
              key: const Key('theme-selector'),
              segments: [
                ButtonSegment(
                  value: ThemeMode.system,
                  label: Text(l10n.themeSystem),
                  icon: const Icon(Icons.brightness_auto),
                ),
                ButtonSegment(
                  value: ThemeMode.light,
                  label: Text(l10n.themeLight),
                  icon: const Icon(Icons.light_mode),
                ),
                ButtonSegment(
                  value: ThemeMode.dark,
                  label: Text(l10n.themeDark),
                  icon: const Icon(Icons.dark_mode),
                ),
              ],
              selected: {settings.themeMode},
              onSelectionChanged: (selection) =>
                  update(settings.copyWith(themeMode: selection.first)),
            ),
          ),
          // ----------------------------------------------------- language
          SectionHeader(l10n.languageSection),
          PanelCard(
            child: RadioGroup<String>(
              groupValue: settings.localeCode ?? '',
              onChanged: (code) => update(settings.copyWith(
                  localeCode: () =>
                      (code == null || code.isEmpty) ? null : code)),
              child: Column(
                children: [
                  RadioListTile<String>(
                    key: const Key('lang-system'),
                    value: '',
                    title: Text(l10n.langSystem),
                    contentPadding: EdgeInsets.zero,
                  ),
                  for (final (code, label) in [
                    ('uz', "O'zbekcha"),
                    ('ru', 'Русский'),
                    ('en', 'English'),
                  ])
                    RadioListTile<String>(
                      key: Key('lang-$code'),
                      value: code,
                      title: Text(label),
                      contentPadding: EdgeInsets.zero,
                    ),
                ],
              ),
            ),
          ),
          // ------------------------------------------------ notifications
          SectionHeader(l10n.notifSection),
          PanelCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SwitchListTile(
                  key: const Key('notif-enabled'),
                  value: settings.notificationsEnabled,
                  title: Text(l10n.notifEnabled),
                  subtitle: Text(l10n.notifEnabledHint),
                  contentPadding: EdgeInsets.zero,
                  onChanged: (value) =>
                      update(settings.copyWith(notificationsEnabled: value)),
                ),
                const Divider(),
                Text(l10n.sensitivityLabel,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(l10n.sensitivityHint,
                    style: Theme.of(context).textTheme.bodySmall),
                Slider(
                  key: const Key('sensitivity-slider'),
                  value: settings.minAlertSeverity.rank.toDouble(),
                  min: 0,
                  max: (Severity.values.length - 1).toDouble(),
                  divisions: Severity.values.length - 1,
                  label: severityLabel(l10n, settings.minAlertSeverity),
                  onChanged: settings.notificationsEnabled
                      ? (value) => update(settings.copyWith(
                          minAlertSeverity: Severity.values[value.round()]))
                      : null,
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    for (final severity in Severity.values)
                      Text(
                        severityLabel(l10n, severity),
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: severity == settings.minAlertSeverity
                              ? FontWeight.bold
                              : FontWeight.normal,
                          color: severityColor(severity),
                        ),
                      ),
                  ],
                ),
                const Divider(),
                SwitchListTile(
                  key: const Key('quiet-hours'),
                  value: settings.quietHoursEnabled,
                  title: Text(l10n.quietHoursLabel),
                  subtitle: Text(l10n.quietHoursHint),
                  contentPadding: EdgeInsets.zero,
                  onChanged: (value) =>
                      update(settings.copyWith(quietHoursEnabled: value)),
                ),
                if (settings.quietHoursEnabled)
                  Row(
                    children: [
                      Expanded(
                        child: _TimeField(
                          key: const Key('quiet-from'),
                          label: l10n.quietFrom,
                          minutes: settings.quietStartMinutes,
                          onChanged: (minutes) => update(
                              settings.copyWith(quietStartMinutes: minutes)),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: _TimeField(
                          key: const Key('quiet-to'),
                          label: l10n.quietTo,
                          minutes: settings.quietEndMinutes,
                          onChanged: (minutes) => update(
                              settings.copyWith(quietEndMinutes: minutes)),
                        ),
                      ),
                    ],
                  ),
                const SizedBox(height: 8),
                Text(
                  l10n.criticalAlwaysAlerts,
                  key: const Key('critical-note'),
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: Theme.of(context).colorScheme.outline),
                ),
              ],
            ),
          ),
          // --------------------------------------------------------- about
          SectionHeader(l10n.aboutSection),
          PanelCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (connection.box != null) ...[
                  KeyValueRow(
                    l10n.trustedBoxLabel,
                    '${connection.box!.boxName} (${connection.box!.host})',
                    valueKey: const Key('settings-box'),
                  ),
                  const SizedBox(height: 4),
                ],
                Text(
                  l10n.privacyNote,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _TimeField extends StatelessWidget {
  const _TimeField({
    super.key,
    required this.label,
    required this.minutes,
    required this.onChanged,
  });

  final String label;
  final int minutes;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      icon: const Icon(Icons.schedule, size: 18),
      label: Text('$label: ${formatMinutesOfDay(minutes)}'),
      onPressed: () async {
        final picked = await showTimePicker(
          context: context,
          initialTime: TimeOfDay(hour: minutes ~/ 60, minute: minutes % 60),
        );
        if (picked != null) {
          onChanged(picked.hour * 60 + picked.minute);
        }
      },
    );
  }
}
