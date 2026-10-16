import 'dart:async';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';

/// The three trade sounds shipped in assets/sounds/.
enum TradeSound {
  orderFilled('sounds/order_filled.mp3'),
  targetHit('sounds/Target_hit.mp3'),
  stopLossHit('sounds/Stoploss_hit.mp3');

  final String asset; // relative to assets/ (AssetSource adds the prefix)
  const TradeSound(this.asset);
}

/// Plays trade sounds ONE AT A TIME (two events close together never overlap).
///
/// Every call is wrapped in try/catch: a missing/broken audio engine must
/// never crash or freeze the trading app - sound just stays silent.
class SoundService {
  final AudioPlayer _player = AudioPlayer();
  final List<TradeSound> _queue = [];
  bool _draining = false;

  /// Queue one sound. Keeps at most 4 waiting so a burst of events can't
  /// build a long backlog of stale sounds.
  Future<void> play(TradeSound s) async {
    if (_queue.length >= 4) _queue.removeAt(0);
    _queue.add(s);
    if (_draining) return;
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        final next = _queue.removeAt(0);
        try {
          await _player.stop();
          await _player.play(AssetSource(next.asset), volume: 1.0);
          // Wait for it to finish (cap at 8s so a stuck player can't block the queue).
          await _player.onPlayerComplete.first.timeout(const Duration(seconds: 8));
        } on TimeoutException {
          // fall through to the next sound
        } catch (e) {
          debugPrint('SoundService play failed: $e');
        }
      }
    } finally {
      _draining = false;
    }
  }

  Future<void> stop() async {
    _queue.clear();
    try {
      await _player.stop();
    } catch (_) {}
  }
}
