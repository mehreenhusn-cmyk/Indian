import 'dart:async';

/// Part 14 (R27): two tiny helpers for a smooth phone. Nothing here talks to the backend. Dart NOT compiled.
///
/// AppActive: ONE flag "the app is on screen". main.dart sets it from the lifecycle. A screen timer made with AppActive.every()
/// does nothing while the phone is locked or the app is in the background (before, the Sniper timers kept calling the backend).
class AppActive {
  AppActive._();
  static bool on = true;

  /// Same as Timer.periodic, but a tick is skipped while the app is in the background.
  static Timer every(Duration d, void Function() fn) => Timer.periodic(d, (_) {
        if (on) fn();
      });
}

/// ScreenCache: the LAST GOOD answer of a screen, kept in memory for the whole run of the app.
/// A tab screen is built again on every tab switch (by design: hidden tabs must not work), and its own LastGood was lost with it,
/// so every switch showed the skeleton and asked the backend again. Now a screen seeds itself from here, shows the old numbers
/// at once and refreshes quietly. Only GOOD answers go in (the screen checks), a failed refresh never wipes it.
class ScreenCache {
  ScreenCache._();
  static final Map<String, Map<String, dynamic>> _data = {};
  static final Map<String, DateTime> _at = {};

  static Map<String, dynamic>? get(String key) => _data[key];
  static DateTime? when(String key) => _at[key];

  /// Stores [v] when it is a real answer: not null, not empty, no error / state flag.
  static bool put(String key, Map<String, dynamic>? v) {
    if (v == null || v.isEmpty || v['error'] != null || v['state'] == 'error' || v['state'] == 'off' || v['state'] == 'old') return false;
    _data[key] = v;
    _at[key] = DateTime.now();
    return true;
  }
}
