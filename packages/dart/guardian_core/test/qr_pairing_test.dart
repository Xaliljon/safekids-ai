import 'package:guardian_core/guardian_core.dart';
import 'package:test/test.dart';

void main() {
  group('QrPairingPayload.parse', () {
    test('parses a full payload', () {
      final payload = QrPairingPayload.parse(
          'guardian://pair?host=192.168.1.20&port=8787&code=482913&name=Room%20Box');
      expect(payload, isNotNull);
      expect(payload!.host, '192.168.1.20');
      expect(payload.apiPort, 8787);
      expect(payload.code, '482913');
      expect(payload.boxName, 'Room Box');
    });

    test('defaults the port and tolerates whitespace', () {
      final payload =
          QrPairingPayload.parse('  guardian://pair?host=10.0.0.5&code=1  ');
      expect(payload!.apiPort, 8787);
    });

    test('rejects everything that is not a Guardian pairing QR', () {
      const invalid = [
        'https://example.com/pair?host=x&code=1', // wrong scheme
        'guardian://other?host=x&code=1', // wrong authority
        'guardian://pair?code=1', // missing host
        'guardian://pair?host=x', // missing code
        'guardian://pair?host=x&code=1&port=99999', // invalid port
        'guardian://pair?host=x&code=1&port=abc',
        'complete garbage',
        '',
      ];
      for (final raw in invalid) {
        expect(QrPairingPayload.parse(raw), isNull, reason: raw);
      }
    });
  });
}
