import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:guardian_core/guardian_core.dart';

import 'device_api.dart';
import 'evidence_cache.dart';

/// Where one incident's evidence stands, from the app's point of view.
enum EvidencePlaybackState {
  loading, // asking the box
  none, // box reachable, no evidence (older incident / evidence disabled)
  preparing, // box is still exporting (pending/recording)
  failed, // export failed on the box
  available, // ready on the box, not downloaded yet
  downloading,
  cached, // playable from local storage (works offline)
}

/// Loads, downloads and caches the evidence for ONE incident.
///
/// Offline-first: a clip already in the cache is served without touching
/// the box. Downloads report progress; both variants (original / AI
/// analysis) cache independently. No sharing, no export — the only sink
/// is the app's own player (ADR-0017 privacy).
class EvidenceController extends ChangeNotifier {
  EvidenceController({
    required DeviceApi api,
    required EvidenceCache cache,
    required PairedBox? box,
    required String incidentId,
    int cacheLimitBytes = 250 * 1024 * 1024,
  })  : _api = api,
        _cache = cache,
        _box = box,
        _incidentId = incidentId,
        _cacheLimit = cacheLimitBytes;

  final DeviceApi _api;
  final EvidenceCache _cache;
  final PairedBox? _box;
  final String _incidentId;
  final int _cacheLimit;

  EvidencePlaybackState state = EvidencePlaybackState.loading;
  EvidenceRecord? record;
  Uint8List? thumbnail;
  String variant = 'overlay'; // directors start from the AI's view
  String? videoPath;
  double progress = 0.0;
  bool _disposed = false;

  bool get canSwitchVariant => record != null && record!.variants.length > 1;

  Future<void> initialize() async {
    final box = _box;
    if (box == null) {
      _set(EvidencePlaybackState.none);
      return;
    }
    List<EvidenceRecord> records;
    try {
      records = await _api.listEvidence(box);
    } on Exception {
      // Box unreachable: cached video may still exist from an earlier
      // session — evidence remains reviewable offline.
      record = null;
      await _tryCachedFallback();
      return;
    }
    record = records
        .where((candidate) => candidate.incidentId == _incidentId)
        .firstOrNull;
    final found = record;
    if (found == null) {
      _set(EvidencePlaybackState.none);
      return;
    }
    if (found.status == EvidenceStatus.pending ||
        found.status == EvidenceStatus.recording) {
      _set(EvidencePlaybackState.preparing);
      return;
    }
    if (!found.playable) {
      _set(EvidencePlaybackState.failed);
      return;
    }
    if (!found.variants.contains(variant)) {
      variant = found.variants.first;
    }
    await _loadThumbnail(box, found);
    final cached = await _cache.pathFor(
      FileEvidenceCache.videoKey(found.evidenceId, variant),
    );
    if (cached != null) {
      videoPath = cached;
      _set(EvidencePlaybackState.cached);
    } else {
      _set(EvidencePlaybackState.available);
    }
  }

  /// Download the current variant (with progress) and cache it.
  Future<void> download() async {
    final box = _box;
    final found = record;
    if (box == null || found == null) {
      return;
    }
    progress = 0.0;
    _set(EvidencePlaybackState.downloading);
    try {
      final bytes = await _api.downloadEvidenceVideo(
        box,
        found.evidenceId,
        variant,
        onProgress: (received, total) {
          if (total > 0) {
            progress = received / total;
            _notify();
          }
        },
      );
      videoPath = await _cache.put(
        FileEvidenceCache.videoKey(found.evidenceId, variant),
        bytes,
      );
      await _cache.enforceLimit(_cacheLimit);
      _set(EvidencePlaybackState.cached);
    } on Exception {
      _set(EvidencePlaybackState.available); // retryable
    }
  }

  /// Switch between the original view and the AI analysis view.
  Future<void> switchVariant(String next) async {
    if (next == variant || record == null) {
      return;
    }
    variant = next;
    videoPath = null;
    final cached = await _cache.pathFor(
      FileEvidenceCache.videoKey(record!.evidenceId, variant),
    );
    if (cached != null) {
      videoPath = cached;
      _set(EvidencePlaybackState.cached);
    } else {
      _set(EvidencePlaybackState.available);
      await download(); // fetch the other view right away
    }
  }

  Future<void> _tryCachedFallback() async {
    // Without the record we cannot know the evidence id — nothing to do.
    _set(EvidencePlaybackState.none);
  }

  Future<void> _loadThumbnail(PairedBox box, EvidenceRecord found) async {
    if (!found.hasThumbnail || thumbnail != null) {
      return;
    }
    final key = FileEvidenceCache.thumbnailKey(found.evidenceId);
    try {
      final cachedPath = await _cache.pathFor(key);
      if (cachedPath != null) {
        thumbnail = await File(cachedPath).readAsBytes();
        return;
      }
      final bytes = await _api.fetchEvidenceThumbnail(box, found.evidenceId);
      await _cache.put(key, bytes);
      thumbnail = Uint8List.fromList(bytes);
    } on Exception {
      thumbnail = null; // poster is optional; playback still works
    }
  }

  void _set(EvidencePlaybackState next) {
    state = next;
    _notify();
  }

  void _notify() {
    if (!_disposed) {
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
