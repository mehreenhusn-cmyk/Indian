import 'dart:ui' show FrameTiming;
import 'package:flutter/scheduler.dart';

/// Counts slow screen frames while the app is open, per minute and per tab (kept for 26 hours in memory).
/// It only LOOKS: no extra work on the screen, one small callback per batch of frames.
/// The load report sheet shows it next to the backend numbers, so "is the app hanging or is the backend slow?" has an answer.
class JankMeter {
  JankMeter._();
  static final JankMeter instance = JankMeter._();

  static const List<String> _tabs = ['Dash', 'Market', 'Positions', 'Signals', 'Dual Bot', 'AI', 'More', 'Brain', 'Sniper', 'Study Lab', 'Diagnostics']; // Part 14: screens 8 to 10 now have their own name (before: 'Other')
  static const int _slowMs = 32; // a frame longer than 2 normal frames = you can feel it
  static const int _frozenMs = 700; // longer than this = the screen looks stuck

  bool _on = false;
  String _tab = 'Dash';
  final List<_Bucket> _buckets = [];

  void start() {
    if (_on) return;
    _on = true;
    try {
      SchedulerBinding.instance.addTimingsCallback(_onTimings);
    } catch (_) {}
  }

  void setTab(int index) {
    _tab = (index >= 0 && index < _tabs.length) ? _tabs[index] : 'Other';
  }

  _Bucket _bucket(int minute) {
    if (_buckets.isNotEmpty && _buckets.last.minute == minute) return _buckets.last;
    final b = _Bucket(minute);
    _buckets.add(b);
    final cut = minute - 26 * 60;
    while (_buckets.isNotEmpty && _buckets.first.minute < cut) {
      _buckets.removeAt(0);
    }
    return b;
  }

  void _onTimings(List<FrameTiming> timings) {
    try {
      final minute = DateTime.now().millisecondsSinceEpoch ~/ 60000;
      final b = _bucket(minute);
      for (final t in timings) {
        final ms = t.totalSpan.inMilliseconds;
        b.frames++;
        if (ms >= _slowMs) {
          b.slow++;
          b.byTab[_tab] = (b.byTab[_tab] ?? 0) + 1;
        }
        if (ms >= _frozenMs) b.frozen++;
        if (ms > b.worst) b.worst = ms;
      }
    } catch (_) {}
  }

  /// Numbers for the last [hours] hours.
  Map<String, dynamic> summary(double hours) {
    final nowMin = DateTime.now().millisecondsSinceEpoch ~/ 60000;
    final from = nowMin - (hours * 60).round();
    int frames = 0, slow = 0, frozen = 0, worst = 0;
    final byTab = <String, int>{};
    for (final b in _buckets) {
      if (b.minute < from) continue;
      frames += b.frames;
      slow += b.slow;
      frozen += b.frozen;
      if (b.worst > worst) worst = b.worst;
      b.byTab.forEach((k, v) => byTab[k] = (byTab[k] ?? 0) + v);
    }
    final pct = frames == 0 ? 0.0 : 100.0 * slow / frames;
    String level = 'ok';
    if (pct >= 10 || frozen >= 5) {
      level = 'bad';
    } else if (pct >= 4 || frozen >= 1) {
      level = 'warn';
    }
    String worstTab = '';
    int worstN = 0;
    byTab.forEach((k, v) {
      if (v > worstN) {
        worstN = v;
        worstTab = k;
      }
    });
    final score = (pct * 7).clamp(0, 100).round();
    return {
      'frames': frames,
      'slow': slow,
      'frozen': frozen,
      'worst_ms': worst,
      'slow_pct': pct,
      'level': level,
      'score': score,
      'worst_tab': worstTab,
      'text': frames == 0
          ? 'App screen: no frames recorded yet (the app was just opened).'
          : 'App screen: ${pct.toStringAsFixed(1)}% of $frames frames were slow, $frozen looked frozen, worst frame $worst ms'
              '${worstTab.isEmpty ? '' : ', slowest tab: $worstTab'}.',
    };
  }
}

class _Bucket {
  final int minute;
  int frames = 0;
  int slow = 0;
  int frozen = 0;
  int worst = 0;
  final Map<String, int> byTab = <String, int>{};
  _Bucket(this.minute);
}
