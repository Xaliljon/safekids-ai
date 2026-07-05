import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:guardian_core/guardian_core.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../application/device_api.dart';

/// Device API client over Dio (HTTP) and web_socket_channel (realtime).
class DioDeviceApi implements DeviceApi {
  DioDeviceApi({Dio? dio})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 5),
              receiveTimeout: const Duration(seconds: 10),
            ));

  final Dio _dio;

  @override
  Future<PairedBox> pair({
    required String host,
    required int apiPort,
    required String code,
    required String deviceName,
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      'http://$host:$apiPort/api/v1/pair',
      data: {'code': code, 'device_name': deviceName},
    );
    final body = response.data!;
    return PairedBox(
      host: host,
      apiPort: apiPort,
      wsPort: body['ws_port'] as int,
      token: body['token'] as String,
      boxName: body['box_name'] as String,
    );
  }

  @override
  Future<SyncResult> fetchMissed(PairedBox box, int afterCursor) async {
    final response = await _dio.get<Map<String, dynamic>>(
      box.apiBase.resolve('/api/v1/notifications').toString(),
      queryParameters: {'after': afterCursor},
      options: _authorized(box),
    );
    final body = response.data!;
    return SyncResult(
      cursor: body['cursor'] as int,
      notifications: [
        for (final payload in body['notifications'] as List<dynamic>)
          NotificationMessage.fromJson(payload as Map<String, dynamic>),
      ],
    );
  }

  @override
  Future<IncidentDetails> fetchIncident(
      PairedBox box, String incidentId) async {
    final response = await _dio.get<Map<String, dynamic>>(
      box.apiBase.resolve('/api/v1/incidents/$incidentId').toString(),
      options: _authorized(box),
    );
    return IncidentDetails.fromJson(response.data!);
  }

  @override
  Future<IncidentDetails> resolveIncident(
    PairedBox box,
    String incidentId, {
    required bool confirm,
    String note = '',
  }) async {
    final response = await _dio.post<Map<String, dynamic>>(
      box.apiBase.resolve('/api/v1/incidents/$incidentId/resolve').toString(),
      data: {'decision': confirm ? 'confirm' : 'dismiss', 'note': note},
      options: _authorized(box),
    );
    return IncidentDetails.fromJson(response.data!);
  }

  @override
  Stream<NotificationMessage> connect(PairedBox box) {
    final channel = WebSocketChannel.connect(box.wsUri);
    return channel.stream
        .map((frame) => jsonDecode(frame as String) as Map<String, dynamic>)
        .where((decoded) => decoded['kind'] == 'notification')
        .map((decoded) => NotificationMessage.fromJson(
            decoded['payload'] as Map<String, dynamic>));
  }

  Options _authorized(PairedBox box) =>
      Options(headers: {'Authorization': 'Bearer ${box.token}'});
}
