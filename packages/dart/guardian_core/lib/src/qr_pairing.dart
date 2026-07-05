/// The QR pairing payload: everything manual pairing asks for, in one scan.
///
/// Format (printed by the box's install report / pilot poster):
///
///     guardian://pair?host=192.168.1.20&port=8787&code=482913&name=Room%20Box
///
/// Parsing is strict — a QR that is not a valid Guardian pairing payload
/// returns null and the wizard falls back to manual entry. The code itself
/// stays single-use and human-granted on the box side (ADR-0015); the QR
/// only saves typing, it grants nothing by itself.
class QrPairingPayload {
  const QrPairingPayload({
    required this.host,
    required this.apiPort,
    required this.code,
    this.boxName,
  });

  final String host;
  final int apiPort;
  final String code;
  final String? boxName;

  static const scheme = 'guardian';

  static QrPairingPayload? parse(String raw) {
    final uri = Uri.tryParse(raw.trim());
    if (uri == null || uri.scheme != scheme || uri.host != 'pair') {
      return null;
    }
    final host = uri.queryParameters['host'];
    final code = uri.queryParameters['code'];
    if (host == null || host.isEmpty || code == null || code.isEmpty) {
      return null;
    }
    final port = int.tryParse(uri.queryParameters['port'] ?? '8787');
    if (port == null || port < 1 || port > 65535) {
      return null;
    }
    return QrPairingPayload(
      host: host,
      apiPort: port,
      code: code,
      boxName: uri.queryParameters['name'],
    );
  }
}
