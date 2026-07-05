import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:safekids_mobile/src/infrastructure/dio_device_api.dart';

import 'fakes.dart';

/// A miniature in-test Guardian Box speaking the device API protocol.
class FakeBoxServer {
  FakeBoxServer(this.http, this.ws);

  final HttpServer http;
  final HttpServer ws;
  final List<WebSocket> sockets = [];
  final List<String> authHeaders = [];

  static Future<FakeBoxServer> start() async {
    final http = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final ws = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final server = FakeBoxServer(http, ws);
    http.listen(server._handleHttp);
    ws.listen(server._handleWs);
    return server;
  }

  Future<void> _handleHttp(HttpRequest request) async {
    authHeaders.add(request.headers.value('Authorization') ?? '');
    final path = request.uri.path;
    Object body;
    if (path == '/api/v1/pair') {
      body = {
        'token': 'issued-token',
        'box_name': 'guardian-edge-box',
        'ws_port': ws.port,
        'cursor': 0,
      };
    } else if (path == '/api/v1/notifications') {
      final after = int.parse(request.uri.queryParameters['after'] ?? '0');
      body = {
        'cursor': 2,
        'notifications': after >= 2
            ? <Object>[]
            : [
                makeMessage(id: 'n-1').toJson(),
                makeMessage(id: 'n-2').toJson()
              ],
      };
    } else if (path.endsWith('/resolve')) {
      final payload =
          jsonDecode(await utf8.decodeStream(request)) as Map<String, dynamic>;
      body = _detailsJson(
        status: payload['decision'] == 'confirm' ? 'confirmed' : 'dismissed',
      );
    } else if (path.startsWith('/api/v1/incidents/')) {
      body = _detailsJson(status: 'pending_review');
    } else {
      request.response.statusCode = 404;
      body = {'error': 'unknown'};
    }
    request.response.headers.contentType = ContentType.json;
    request.response.write(jsonEncode(body));
    await request.response.close();
  }

  Future<void> _handleWs(HttpRequest request) async {
    final socket = await WebSocketTransformer.upgrade(request);
    sockets.add(socket);
    socket.add(jsonEncode(
        {'kind': 'hello', 'box_name': 'guardian-edge-box', 'cursor': 0}));
  }

  Map<String, dynamic> _detailsJson({required String status}) => {
        'incident_id': 'i-1',
        'camera_id': 'classroom-1',
        'track_id': 't-1',
        'track_display_id': 7,
        'severity': 'critical',
        'risk_confidence': 0.91,
        'status': status,
        'opened_at': '2026-07-05T12:00:07+00:00',
        'last_event_at': '2026-07-05T12:00:19+00:00',
        'correlation_id': 'c-1',
        'summary': 'summary',
        'events': <Object>[],
        'review': null,
      };

  Future<void> close() async {
    for (final socket in sockets) {
      await socket.close();
    }
    await http.close(force: true);
    await ws.close(force: true);
  }
}

void main() {
  late FakeBoxServer server;
  late DioDeviceApi api;
  late PairedBox box;

  setUp(() async {
    server = await FakeBoxServer.start();
    api = DioDeviceApi();
    box = PairedBox(
      host: '127.0.0.1',
      apiPort: server.http.port,
      wsPort: server.ws.port,
      token: 'issued-token',
      boxName: 'guardian-edge-box',
    );
  });

  tearDown(() => server.close());

  test('pair exchanges the code for a trusted box', () async {
    final paired = await api.pair(
      host: '127.0.0.1',
      apiPort: server.http.port,
      code: '123456',
      deviceName: 'director-phone',
    );
    expect(paired.token, 'issued-token');
    expect(paired.wsPort, server.ws.port);
    expect(paired.boxName, 'guardian-edge-box');
  });

  test('fetchMissed sends the bearer token and parses payloads', () async {
    final result = await api.fetchMissed(box, 0);
    expect(result.cursor, 2);
    expect(result.notifications, hasLength(2));
    expect(result.notifications.first.severity, Severity.critical);
    expect(server.authHeaders.last, 'Bearer issued-token');
    final upToDate = await api.fetchMissed(box, 2);
    expect(upToDate.notifications, isEmpty);
  });

  test('fetchIncident and resolveIncident round-trip', () async {
    final details = await api.fetchIncident(box, 'i-1');
    expect(details.status, IncidentStatus.pendingReview);
    final resolved = await api.resolveIncident(box, 'i-1', confirm: true);
    expect(resolved.status, IncidentStatus.confirmed);
    final dismissed = await api.resolveIncident(box, 'i-1', confirm: false);
    expect(dismissed.status, IncidentStatus.dismissed);
  });

  test('connect streams live notification frames and ignores other kinds',
      () async {
    final received = <NotificationMessage>[];
    final subscription = api.connect(box).listen(received.add);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(server.sockets, hasLength(1), reason: 'client connected');
    server.sockets.single.add(jsonEncode({
      'kind': 'notification',
      'payload': makeMessage(id: 'n-live').toJson()
    }));
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(received, hasLength(1), reason: 'hello frame is filtered out');
    expect(received.single.notificationId, 'n-live');
    await subscription.cancel();
  });
}
