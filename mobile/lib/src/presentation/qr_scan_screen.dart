import 'package:flutter/material.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../l10n/generated/app_localizations.dart';

/// Camera QR scanner for pairing. Pops with a [QrPairingPayload] on the
/// first valid Guardian code; anything else shows a gentle hint and keeps
/// scanning. The QR only carries address details — the single-use pairing
/// code on the box remains the actual grant (ADR-0015).
class QrScanScreen extends StatefulWidget {
  const QrScanScreen({super.key});

  @override
  State<QrScanScreen> createState() => _QrScanScreenState();
}

class _QrScanScreenState extends State<QrScanScreen> {
  bool _handled = false;
  bool _showInvalid = false;

  void _onDetect(BuildContext context, BarcodeCapture capture) {
    if (_handled) {
      return;
    }
    for (final barcode in capture.barcodes) {
      final raw = barcode.rawValue;
      if (raw == null) {
        continue;
      }
      final payload = QrPairingPayload.parse(raw);
      if (payload != null) {
        _handled = true;
        Navigator.of(context).pop(payload);
        return;
      }
    }
    if (!_showInvalid) {
      setState(() => _showInvalid = true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(l10n.pairScanQr)),
      body: Column(
        children: [
          Expanded(
            child: MobileScanner(
              onDetect: (capture) => _onDetect(context, capture),
            ),
          ),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              _showInvalid ? l10n.pairQrInvalid : l10n.pairQrHint,
              textAlign: TextAlign.center,
              style: _showInvalid
                  ? TextStyle(color: Theme.of(context).colorScheme.error)
                  : null,
            ),
          ),
        ],
      ),
    );
  }
}
