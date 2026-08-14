import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:guardian_core/guardian_core.dart';

import '../../l10n/generated/app_localizations.dart';
import '../providers.dart';
import 'qr_scan_screen.dart';
import 'widgets.dart';

/// Pairing wizard: QR scan or manual entry, then the code from the box.
/// Trust stays local, explicit and human-granted (ADR-0015) — the QR only
/// pre-fills the address; the single-use code on the box is the grant.
/// When already paired, this screen shows the trusted-devices view.
class PairingWizardScreen extends ConsumerStatefulWidget {
  const PairingWizardScreen({super.key});

  @override
  ConsumerState<PairingWizardScreen> createState() =>
      _PairingWizardScreenState();
}

class _PairingWizardScreenState extends ConsumerState<PairingWizardScreen> {
  final _host = TextEditingController();
  final _port = TextEditingController(text: '8787');
  final _code = TextEditingController();
  final _name = TextEditingController(text: 'director-phone');
  String? _error;
  String? _info;
  bool _busy = false;
  bool _manualOpen = false;

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    _code.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _scanQr() async {
    final l10n = AppLocalizations.of(context);
    final payload = await Navigator.of(context).push<QrPairingPayload>(
      MaterialPageRoute(builder: (_) => const QrScanScreen()),
    );
    if (payload == null || !mounted) {
      return;
    }
    setState(() {
      _host.text = payload.host;
      _port.text = '${payload.apiPort}';
      _code.text = payload.code;
      _manualOpen = true;
      _info = l10n.pairQrFilled;
      _error = null;
    });
  }

  Future<void> _pair() async {
    setState(() {
      _busy = true;
      _error = null;
      _info = null;
    });
    final error = await ref.read(connectionControllerProvider).pair(
          host: _host.text.trim(),
          apiPort: int.tryParse(_port.text.trim()) ?? 8787,
          code: _code.text.trim(),
          deviceName: _name.text.trim(),
        );
    if (!mounted) {
      return;
    }
    if (error != null) {
      // The router's redirect leaves /pair automatically on success.
      setState(() {
        _busy = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final connection = ref.watch(connectionControllerProvider);
    final box = connection.box;

    return Scaffold(
      appBar: AppBar(title: Text(l10n.pairTitle)),
      body: ListView(
        key: const Key('pairing-wizard'),
        padding: const EdgeInsets.all(16),
        children: [
          if (box != null) ...[
            SectionHeader(l10n.trustedDevicesTitle),
            _TrustedDevices(box: box, deviceName: _name.text),
          ] else ...[
            Text(l10n.pairIntro),
            const SizedBox(height: 20),
            FilledButton.icon(
              key: const Key('scan-qr-button'),
              onPressed: _busy ? null : _scanQr,
              icon: const Icon(Icons.qr_code_scanner),
              label: Text(l10n.pairScanQr),
            ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              key: const Key('manual-entry-button'),
              onPressed: _busy
                  ? null
                  : () => setState(() => _manualOpen = !_manualOpen),
              icon: const Icon(Icons.keyboard),
              label: Text(l10n.pairManualEntry),
            ),
            if (_manualOpen) ...[
              const SizedBox(height: 16),
              TextField(
                key: const Key('host-field'),
                controller: _host,
                decoration: InputDecoration(labelText: l10n.pairHostLabel),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('port-field'),
                controller: _port,
                decoration: InputDecoration(labelText: l10n.pairPortLabel),
                keyboardType: TextInputType.number,
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('code-field'),
                controller: _code,
                decoration: InputDecoration(labelText: l10n.pairCodeLabel),
                keyboardType: TextInputType.number,
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('name-field'),
                controller: _name,
                decoration:
                    InputDecoration(labelText: l10n.pairDeviceNameLabel),
              ),
              const SizedBox(height: 20),
              FilledButton(
                key: const Key('pair-button'),
                onPressed: _busy ? null : _pair,
                child: Text(_busy ? l10n.pairBusy : l10n.pairButton),
              ),
            ],
            if (_info != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(
                  _info!,
                  key: const Key('pair-info'),
                  style:
                      TextStyle(color: Theme.of(context).colorScheme.primary),
                ),
              ),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.only(top: 16),
                child: Text(
                  _error!,
                  key: const Key('pair-error'),
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

/// The trust picture: this device and its paired box, with local revoke.
class _TrustedDevices extends ConsumerWidget {
  const _TrustedDevices({required this.box, required this.deviceName});

  final PairedBox box;
  final String deviceName;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l10n = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: ListTile(
            leading: const Icon(Icons.phone_iphone),
            title: Text(l10n.trustedThisDevice),
            subtitle: Text(deviceName),
            trailing: const Icon(Icons.verified_user, color: Colors.green),
          ),
        ),
        Card(
          child: ListTile(
            key: const Key('trusted-box'),
            leading: const Icon(Icons.developer_board),
            title: Text(box.boxName),
            subtitle: Text('${box.host}:${box.apiPort}'),
            trailing: const Icon(Icons.verified_user, color: Colors.green),
          ),
        ),
        const SizedBox(height: 16),
        OutlinedButton.icon(
          key: const Key('forget-box-button'),
          style: OutlinedButton.styleFrom(
            foregroundColor: Theme.of(context).colorScheme.error,
          ),
          icon: const Icon(Icons.link_off),
          label: Text(l10n.forgetBox),
          onPressed: () async {
            final sure = await showDialog<bool>(
              context: context,
              builder: (context) => AlertDialog(
                title: Text(l10n.forgetBox),
                content: Text(l10n.forgetBoxQuestion),
                actions: [
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(false),
                    child: Text(l10n.cancel),
                  ),
                  FilledButton(
                    key: const Key('forget-confirm'),
                    onPressed: () => Navigator.of(context).pop(true),
                    child: Text(l10n.ok),
                  ),
                ],
              ),
            );
            if (sure == true) {
              await ref.read(connectionControllerProvider).unpair();
            }
          },
        ),
      ],
    );
  }
}
