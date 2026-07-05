import 'package:dio/dio.dart';
import 'package:guardian_core/guardian_core.dart';

import '../application/box_status_api.dart';

/// Health surface client over Dio (GET :8790/health and /metrics).
class DioBoxStatusApi implements BoxStatusApi {
  DioBoxStatusApi({Dio? dio, DateTime Function()? clock})
      : _dio = dio ??
            Dio(BaseOptions(
              connectTimeout: const Duration(seconds: 4),
              receiveTimeout: const Duration(seconds: 6),
            )),
        _clock = clock ?? DateTime.now;

  static const defaultHealthPort = 8790;

  final Dio _dio;
  final DateTime Function() _clock;

  @override
  Future<BoxHealth> fetchHealth(String host,
      {int port = defaultHealthPort}) async {
    final response = await _dio.get<Map<String, dynamic>>(
      Uri(scheme: 'http', host: host, port: port, path: '/health').toString(),
    );
    return BoxHealth.fromJson(response.data ?? const {}, fetchedAt: _clock());
  }

  @override
  Future<BoxMetrics> fetchMetrics(String host,
      {int port = defaultHealthPort}) async {
    final response = await _dio.get<Map<String, dynamic>>(
      Uri(scheme: 'http', host: host, port: port, path: '/metrics').toString(),
    );
    return BoxMetrics.fromJson(response.data ?? const {});
  }

  @override
  Future<void> restartCamera(PairedBox box, String cameraId) async {
    try {
      await _dio.post<void>(
        box.apiBase.resolve('/api/v1/cameras/$cameraId/restart').toString(),
        options: Options(headers: {'Authorization': 'Bearer ${box.token}'}),
      );
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      if (status == 404 || status == 405 || status == 501) {
        throw const UnsupportedByBoxError('restartCamera');
      }
      rethrow;
    }
  }
}
