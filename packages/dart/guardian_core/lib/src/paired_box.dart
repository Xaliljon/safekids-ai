/// A trusted Guardian Box the device has paired with.
class PairedBox {
  const PairedBox({
    required this.host,
    required this.apiPort,
    required this.wsPort,
    required this.token,
    required this.boxName,
  });

  final String host;
  final int apiPort;
  final int wsPort;
  final String token;
  final String boxName;

  Uri get apiBase => Uri(scheme: 'http', host: host, port: apiPort);

  Uri get wsUri => Uri(
      scheme: 'ws',
      host: host,
      port: wsPort,
      path: '/ws',
      queryParameters: {'token': token});

  factory PairedBox.fromJson(Map<String, dynamic> json) => PairedBox(
        host: json['host'] as String,
        apiPort: json['api_port'] as int,
        wsPort: json['ws_port'] as int,
        token: json['token'] as String,
        boxName: json['box_name'] as String,
      );

  Map<String, dynamic> toJson() => {
        'host': host,
        'api_port': apiPort,
        'ws_port': wsPort,
        'token': token,
        'box_name': boxName,
      };
}
