import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:guardian_core/guardian_core.dart';

import '../application/connection_controller.dart';
import '../application/notification_repository.dart';
import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'format.dart';
import 'widgets.dart';

const _pageSize = 50;

/// The notification center: shelves (unread/read/archived), search,
/// severity + camera filters, date-grouped, paginated. All of it works
/// offline against the cache — the list never depends on the box.
class NotificationCenterScreen extends ConsumerStatefulWidget {
  const NotificationCenterScreen({super.key});

  @override
  ConsumerState<NotificationCenterScreen> createState() =>
      _NotificationCenterScreenState();
}

class _NotificationCenterScreenState
    extends ConsumerState<NotificationCenterScreen> {
  AlertFilter _filter = const AlertFilter();
  int _visible = _pageSize;
  final _search = TextEditingController();

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  void _update(AlertFilter next) {
    setState(() {
      _filter = next;
      _visible = _pageSize; // a new query restarts pagination
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final repository = ref.watch(notificationRepositoryProvider);
    final connection = ref.watch(connectionControllerProvider);
    final total = repository.count(_filter);
    final items = repository.page(_filter, limit: _visible);
    final cameras = repository.cameraIds;

    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.alertsTitle),
        actions: [
          IconButton(
            key: const Key('mark-all-read'),
            tooltip: l10n.markAllRead,
            icon: const Icon(Icons.mark_email_read_outlined),
            onPressed: () =>
                ref.read(notificationRepositoryProvider).markAllRead(),
          ),
        ],
      ),
      body: Column(
        children: [
          if (connection.state == BoxConnectionState.offline)
            const OfflineBanner(),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: TextField(
              key: const Key('alerts-search'),
              controller: _search,
              onChanged: (value) => _update(_filter.copyWith(query: value)),
              decoration: InputDecoration(
                hintText: l10n.alertsSearchHint,
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () {
                          _search.clear();
                          _update(_filter.copyWith(query: ''));
                        },
                      ),
                isDense: true,
                border:
                    OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
              ),
            ),
          ),
          SizedBox(
            height: 48,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              children: [
                for (final severity in Severity.values.reversed)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: FilterChip(
                      key: Key('severity-filter-${severity.wire}'),
                      label: Text(severityLabel(l10n, severity)),
                      selected: _filter.severities.contains(severity),
                      checkmarkColor: Colors.white,
                      selectedColor: severityColor(severity),
                      labelStyle: TextStyle(
                        color: _filter.severities.contains(severity)
                            ? Colors.white
                            : null,
                      ),
                      onSelected: (selected) {
                        final next = {..._filter.severities};
                        selected ? next.add(severity) : next.remove(severity);
                        _update(_filter.copyWith(severities: next));
                      },
                    ),
                  ),
                if (cameras.length > 1)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 4),
                    child: _CameraFilterChip(
                      cameras: cameras,
                      selected: _filter.cameraId,
                      onChanged: (cameraId) =>
                          _update(_filter.copyWith(cameraId: () => cameraId)),
                    ),
                  ),
              ],
            ),
          ),
          SegmentedButton<AlertsTab>(
            key: const Key('alerts-tabs'),
            segments: [
              ButtonSegment(
                value: AlertsTab.unread,
                label: Text(l10n.tabUnread),
              ),
              ButtonSegment(value: AlertsTab.read, label: Text(l10n.tabRead)),
              ButtonSegment(
                value: AlertsTab.archived,
                label: Text(l10n.tabArchived),
              ),
            ],
            selected: {_filter.tab},
            onSelectionChanged: (selection) =>
                _update(_filter.copyWith(tab: selection.first)),
          ),
          const SizedBox(height: 4),
          Expanded(
            child: items.isEmpty
                ? Center(
                    key: const Key('empty-state'),
                    child: Text(
                      _filter.query.isEmpty && _filter.severities.isEmpty
                          ? l10n.alertsEmpty
                          : l10n.alertsNoMatches,
                    ),
                  )
                : _GroupedList(
                    items: items,
                    hasMore: total > items.length,
                    onLoadMore: () => setState(() => _visible += _pageSize),
                  ),
          ),
        ],
      ),
    );
  }
}

class _CameraFilterChip extends StatelessWidget {
  const _CameraFilterChip({
    required this.cameras,
    required this.selected,
    required this.onChanged,
  });

  final List<String> cameras;
  final String? selected;
  final ValueChanged<String?> onChanged;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return PopupMenuButton<String>(
      key: const Key('camera-filter'),
      initialValue: selected ?? '',
      onSelected: (value) => onChanged(value.isEmpty ? null : value),
      itemBuilder: (context) => [
        PopupMenuItem(value: '', child: Text(l10n.allCameras)),
        for (final camera in cameras)
          PopupMenuItem(value: camera, child: Text(camera)),
      ],
      child: Chip(
        avatar: const Icon(Icons.videocam_outlined, size: 18),
        label: Text(selected ?? l10n.allCameras),
      ),
    );
  }
}

/// Lazy list with date group headers and a load-more row (pagination).
class _GroupedList extends StatelessWidget {
  const _GroupedList({
    required this.items,
    required this.hasMore,
    required this.onLoadMore,
  });

  final List<NotificationItem> items;
  final bool hasMore;
  final VoidCallback onLoadMore;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final now = DateTime.now();
    final rows = <Widget>[];
    String? lastHeader;
    for (final item in items) {
      final header = dateHeader(l10n, item.message.timestamp, now);
      if (header != lastHeader) {
        rows.add(SectionHeader(header));
        lastHeader = header;
      }
      rows.add(_NotificationTile(item: item));
    }
    if (hasMore) {
      rows.add(Padding(
        padding: const EdgeInsets.all(12),
        child: OutlinedButton(
          key: const Key('load-more'),
          onPressed: onLoadMore,
          child: Text(l10n.loadMore),
        ),
      ));
    }
    return ListView.builder(
      key: const Key('notification-list'),
      itemCount: rows.length,
      itemBuilder: (context, index) => rows[index],
    );
  }
}

class _NotificationTile extends ConsumerWidget {
  const _NotificationTile({required this.item});

  final NotificationItem item;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    final message = item.message;
    final color = severityColor(message.severity);
    final weight = item.read ? FontWeight.normal : FontWeight.bold;
    final archived = item.archived;
    return ListTile(
      key: Key('notification-${message.notificationId}'),
      leading: CircleAvatar(
        backgroundColor: color,
        radius: 10,
        child: item.read
            ? null
            : const Icon(Icons.circle, size: 8, color: Colors.white),
      ),
      title: Text(
        '${l10n.potentialFall} — ${severityLabel(l10n, message.severity)} '
        '${(message.confidence * 100).round()}%',
        style: TextStyle(fontWeight: weight),
      ),
      subtitle: Text(
        '${message.cameraId} · ${formatTime(message.timestamp)} · '
        '${incidentStatusLabel(l10n, message.incidentStatus)}',
        style: TextStyle(fontWeight: weight),
      ),
      trailing: IconButton(
        key: Key('archive-${message.notificationId}'),
        tooltip: archived ? l10n.unarchive : l10n.archive,
        icon: Icon(
          archived ? Icons.unarchive_outlined : Icons.archive_outlined,
          size: 20,
        ),
        onPressed: () => ref
            .read(notificationRepositoryProvider)
            .setArchived(message.notificationId, !archived),
      ),
      onTap: () {
        ref
            .read(notificationRepositoryProvider)
            .markRead(message.notificationId);
        context.push('/incident/${message.notificationId}');
      },
    );
  }
}
