import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers.dart';

/// Manual pairing: enter the box's LAN address and the code from its
/// display. No accounts, no cloud login (ADR-0015). mDNS discovery is a
/// planned addition; manual entry always remains as the fallback.
class PairingScreen extends ConsumerStatefulWidget {
  const PairingScreen({super.key});

  @override
  ConsumerState<PairingScreen> createState() => _PairingScreenState();
}

class _PairingScreenState extends ConsumerState<PairingScreen> {
  final _host = TextEditingController();
  final _port = TextEditingController(text: '8787');
  final _code = TextEditingController();
  final _name = TextEditingController(text: 'director-phone');
  String? _error;
  bool _busy = false;

  @override
  void dispose() {
    _host.dispose();
    _port.dispose();
    _code.dispose();
    _name.dispose();
    super.dispose();
  }

  Future<void> _pair() async {
    setState(() {
      _busy = true;
      _error = null;
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
    if (error == null) {
      context.go('/');
    } else {
      setState(() {
        _busy = false;
        _error = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Pair with Guardian Box')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Enter the address shown on your Guardian Box and the '
              'pairing code from its display. Everything stays on your '
              'local network.',
            ),
            const SizedBox(height: 16),
            TextField(
              key: const Key('host-field'),
              controller: _host,
              decoration: const InputDecoration(labelText: 'Box address (IP)'),
            ),
            TextField(
              key: const Key('port-field'),
              controller: _port,
              decoration: const InputDecoration(labelText: 'Port'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              key: const Key('code-field'),
              controller: _code,
              decoration: const InputDecoration(labelText: 'Pairing code'),
              keyboardType: TextInputType.number,
            ),
            TextField(
              key: const Key('name-field'),
              controller: _name,
              decoration: const InputDecoration(labelText: 'This device name'),
            ),
            const SizedBox(height: 24),
            FilledButton(
              key: const Key('pair-button'),
              onPressed: _busy ? null : _pair,
              child: Text(_busy ? 'Pairing…' : 'Pair'),
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
        ),
      ),
    );
  }
}
