import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../../l10n/generated/app_localizations.dart';

/// Builds the actual video surface for a cached evidence file. Tests
/// override this provider with a stub — widget tests have no platform
/// video codecs.
final evidencePlayerBuilderProvider =
    Provider<Widget Function(String path, Key key)>(
  (ref) => (path, key) => EvidenceVideoPlayer(key: key, path: path),
);

/// Local-file video player: play / pause / replay / fullscreen. No editing,
/// no sharing, no export — reviewing is the only supported action
/// (ADR-0017 privacy).
class EvidenceVideoPlayer extends StatefulWidget {
  const EvidenceVideoPlayer(
      {super.key, required this.path, this.fullscreen = false});

  final String path;
  final bool fullscreen;

  @override
  State<EvidenceVideoPlayer> createState() => _EvidenceVideoPlayerState();
}

class _EvidenceVideoPlayerState extends State<EvidenceVideoPlayer> {
  late final VideoPlayerController _controller;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.file(File(widget.path))
      ..initialize().then((_) {
        if (mounted) {
          setState(() => _ready = true);
          _controller.play();
        }
      });
    _controller.addListener(_onTick);
  }

  void _onTick() {
    if (mounted) {
      setState(() {});
    }
  }

  @override
  void dispose() {
    _controller.removeListener(_onTick);
    _controller.dispose();
    super.dispose();
  }

  Future<void> _openFullscreen() async {
    await Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => Scaffold(
          backgroundColor: Colors.black,
          appBar: AppBar(
              backgroundColor: Colors.black, foregroundColor: Colors.white),
          body: Center(
            child: EvidenceVideoPlayer(path: widget.path, fullscreen: true),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    if (!_ready) {
      return const AspectRatio(
        aspectRatio: 16 / 9,
        child: Center(child: CircularProgressIndicator()),
      );
    }
    final value = _controller.value;
    final position = value.position;
    final duration = value.duration;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        AspectRatio(
          aspectRatio: value.aspectRatio == 0 ? 16 / 9 : value.aspectRatio,
          child: GestureDetector(
            onTap: () =>
                value.isPlaying ? _controller.pause() : _controller.play(),
            child: VideoPlayer(_controller),
          ),
        ),
        VideoProgressIndicator(_controller, allowScrubbing: true),
        Row(
          children: [
            IconButton(
              key: const Key('player-play-pause'),
              icon: Icon(value.isPlaying ? Icons.pause : Icons.play_arrow),
              tooltip: value.isPlaying ? l10n.playerPause : l10n.playerPlay,
              onPressed: () =>
                  value.isPlaying ? _controller.pause() : _controller.play(),
            ),
            IconButton(
              key: const Key('player-replay'),
              icon: const Icon(Icons.replay),
              tooltip: l10n.playerReplay,
              onPressed: () async {
                await _controller.seekTo(Duration.zero);
                await _controller.play();
              },
            ),
            Expanded(
              child: Text(
                '${_fmt(position)} / ${_fmt(duration)}',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
            if (!widget.fullscreen)
              IconButton(
                key: const Key('player-fullscreen'),
                icon: const Icon(Icons.fullscreen),
                tooltip: l10n.playerFullscreen,
                onPressed: _openFullscreen,
              ),
          ],
        ),
      ],
    );
  }

  static String _fmt(Duration duration) {
    String pad(int value) => value.toString().padLeft(2, '0');
    return '${pad(duration.inMinutes)}:${pad(duration.inSeconds % 60)}';
  }
}
