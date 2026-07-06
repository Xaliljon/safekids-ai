import 'dart:io';

/// Offline store for downloaded evidence media (EVIDENCE_UX.md).
///
/// Downloaded clips stay available with no box connection. The cache is
/// size-bounded: when it outgrows the configured limit, least-recently-used
/// files are removed first. Clearing the cache never touches the box —
/// evidence lives there under its own retention policy.
abstract class EvidenceCache {
  /// Absolute path of a cached file, or null when absent.
  Future<String?> pathFor(String key);

  /// Store bytes under [key]; returns the file path.
  Future<String> put(String key, List<int> bytes);

  /// Remove files (oldest access first) until total size <= [maxBytes].
  Future<void> enforceLimit(int maxBytes);

  Future<int> totalBytes();

  Future<void> clear();
}

/// Filesystem implementation under the app documents directory.
class FileEvidenceCache implements EvidenceCache {
  FileEvidenceCache(this._directory);

  final Directory _directory;

  static String videoKey(String evidenceId, String variant) =>
      '$evidenceId-$variant.mp4';

  static String thumbnailKey(String evidenceId) => '$evidenceId.jpg';

  File _file(String key) => File('${_directory.path}/$key');

  @override
  Future<String?> pathFor(String key) async {
    final file = _file(key);
    if (!await file.exists()) {
      return null;
    }
    // Touch for LRU: most recently used survives eviction longest.
    await file.setLastAccessed(DateTime.now());
    return file.path;
  }

  @override
  Future<String> put(String key, List<int> bytes) async {
    await _directory.create(recursive: true);
    final file = _file(key);
    await file.writeAsBytes(bytes, flush: true);
    return file.path;
  }

  @override
  Future<void> enforceLimit(int maxBytes) async {
    if (!await _directory.exists()) {
      return;
    }
    final files = <File>[
      await for (final entry in _directory.list())
        if (entry is File) entry,
    ];
    var total = 0;
    final stats = <(File, FileStat)>[];
    for (final file in files) {
      final stat = await file.stat();
      total += stat.size;
      stats.add((file, stat));
    }
    if (total <= maxBytes) {
      return;
    }
    stats.sort((a, b) => a.$2.accessed.compareTo(b.$2.accessed));
    for (final (file, stat) in stats) {
      if (total <= maxBytes) {
        break;
      }
      try {
        await file.delete();
        total -= stat.size;
      } on FileSystemException {
        // A file disappearing mid-eviction is fine.
      }
    }
  }

  @override
  Future<int> totalBytes() async {
    if (!await _directory.exists()) {
      return 0;
    }
    var total = 0;
    await for (final entry in _directory.list()) {
      if (entry is File) {
        total += (await entry.stat()).size;
      }
    }
    return total;
  }

  @override
  Future<void> clear() async {
    if (await _directory.exists()) {
      await _directory.delete(recursive: true);
    }
  }
}
