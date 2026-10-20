import 'dart:math' as math;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Plays a short typewriter-machine key strike (and a line-end bell) for the typewriter effect on
/// the welcome screen.
///
/// Uses audioplayers' AudioPool (built for rapid repeated short sounds): each
/// click starts instantly and fast typing overlaps instead of cutting the
/// previous click off. Everything is wrapped in try/catch - a broken audio
/// engine must never crash or freeze the app. If the pool can't load, the
/// system click sound is used instead so there is still feedback.
class OwlKeyClicker {
  final List<AudioPool> _pools = [];
  AudioPool? _bell; // the typewriter "ting" at the end of a line
  int _i = -1;
  final math.Random _rnd = math.Random();
  bool _ready = false;

  /// Read on every tick so the user's existing sound setting is respected
  /// even if it changes mid-splash.
  final bool Function() soundOn;

  OwlKeyClicker({required this.soundOn});

  Future<void> init() async {
    try {
      for (final path in const [
        'sounds/typewriter_k1.wav',
        'sounds/typewriter_k2.wav',
        'sounds/typewriter_k3.wav',
        'sounds/typewriter_k4.wav',
        'sounds/typewriter_k5.wav',
        'sounds/typewriter_k6.wav',
      ]) {
        _pools.add(await AudioPool.create(source: AssetSource(path), maxPlayers: 4));
      }
      _bell = await AudioPool.create(source: AssetSource('sounds/typewriter_bell.wav'), maxPlayers: 2);
      _ready = true;
    } catch (e) {
      debugPrint('OwlKeyClicker init failed: $e');
    }
  }

  /// One key press: click sound + (optionally) a tiny haptic tick.
  void tick({bool haptic = true}) {
    if (haptic) HapticFeedback.selectionClick();
    if (!soundOn()) return;
    try {
      if (_ready && _pools.isNotEmpty) {
        // Six real typewriter strikes, picked at random (never the same one twice in a row) so it sounds like typing.
        var n = _rnd.nextInt(_pools.length);
        if (n == _i && _pools.length > 1) n = (n + 1) % _pools.length;
        _i = n;
        _pools[n].start(volume: 1.0);
      } else {
        SystemSound.play(SystemSoundType.click);
      }
    } catch (_) {}
  }

  /// The typewriter bell: line finished / loading completed.
  void bell({bool haptic = true}) {
    if (haptic) HapticFeedback.mediumImpact();
    if (!soundOn()) return;
    try {
      _bell?.start(volume: 0.9);
    } catch (_) {}
  }

  void dispose() {
    for (final p in _pools) {
      try {
        p.dispose();
      } catch (_) {}
    }
    _pools.clear();
    try {
      _bell?.dispose();
    } catch (_) {}
    _bell = null;
    _ready = false;
  }
}
