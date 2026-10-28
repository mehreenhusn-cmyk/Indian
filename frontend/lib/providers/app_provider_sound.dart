part of 'app_provider.dart';

/// Trade sound alerts (state + detection). Moved out of app_provider.dart (NEXT-5c) as a MIXIN because it owns fields.
/// The five lines below are the only things it needs from AppProvider (they already exist there).
mixin SoundAlerts on ChangeNotifier {
  SharedPreferences get prefs;
  List<dynamic> get positions;
  List<dynamic> get alerts;
  String get statsMode;
  void pushPrefsBackup();

  // ------------------------------------------------------- sound alerts --
  // Trade sounds (assets/sounds/): order_filled.mp3 on ENTRY, Target_hit.mp3
  // on a profit / TP exit, Stoploss_hit.mp3 on a stop-loss exit. The daily
  // target / loss-limit alerts reuse Target_hit / Stoploss_hit. Detection is
  // purely client-side: it diffs the open-positions list between status
  // updates, so no backend change is needed.
  //   * first data after start, a mode switch (PAPER<->LIVE) and every
  //     WebSocket (re)connect snapshot only RE-BASELINE - never play, so
  //     old positions are not re-announced.
  //   * events inside a 1.2s window are merged (one sound per kind).
  //   * exit reason (TP2 hit / Stop loss hit ...) comes from the Alerts feed
  //     entry the backend already writes for that trade.
  final SoundService sound = SoundService();

  // Pref keys kept as-is so an existing on/off choice survives the update.
  static const _kSoundOn = 'voice_enabled';
  static const _kSoundEntry = 'voice_entry';
  static const _kSoundExit = 'voice_exit';
  static const _kSoundFgOnly = 'voice_fg_only';

  bool get soundEnabled => prefs.getBool(_kSoundOn) ?? true;
  bool get soundEntryOn => prefs.getBool(_kSoundEntry) ?? true;
  bool get soundExitOn => prefs.getBool(_kSoundExit) ?? true;
  bool get soundOnlyWhenOpen => prefs.getBool(_kSoundFgOnly) ?? false;

  Future<void> setSoundEnabled(bool v) async {
    await prefs.setBool(_kSoundOn, v);
    pushPrefsBackup();
    if (!v) await sound.stop();
    notifyListeners();
  }

  Future<void> setSoundEntryOn(bool v) async {
    await prefs.setBool(_kSoundEntry, v);
    pushPrefsBackup();
    notifyListeners();
  }

  Future<void> setSoundExitOn(bool v) async {
    await prefs.setBool(_kSoundExit, v);
    pushPrefsBackup();
    notifyListeners();
  }

  Future<void> setSoundOnlyWhenOpen(bool v) async {
    await prefs.setBool(_kSoundFgOnly, v);
    pushPrefsBackup();
    notifyListeners();
  }

  /// One of the three test buttons in Settings - ignores the master toggle
  /// on purpose so the person can check volume before turning alerts on.
  Future<void> testSound(TradeSound s) => sound.play(s);

  bool _appForeground = true;
  void setAppForeground(bool fg) => _appForeground = fg;

  Map<String, Map<String, dynamic>> _soundKnown = {};
  bool _soundBaselined = false;
  String? _soundMode;
  double _soundLastAlertTs = 0;
  bool _soundEntryPending = false;
  final List<Map<String, dynamic>> _soundExitBuf = [];
  Timer? _soundFlush;

  bool get _soundMayPlay => soundEnabled && (!soundOnlyWhenOpen || _appForeground);

  void _soundOnStatus({required bool snapshot}) {
    try {
      final current = <String, Map<String, dynamic>>{};
      for (final e in positions) {
        if (e is Map) {
          final m = e.cast<String, dynamic>();
          current['${m['id']}'] = m;
        }
      }
      final mode = statsMode;
      final firstData = !_soundBaselined || _soundMode != mode;

      // Daily target / loss-limit alerts (type 'target' / 'loss').
      double maxTs = _soundLastAlertTs;
      final fresh = <Map>[];
      for (final a in alerts) {
        if (a is Map) {
          final ts = (a['ts'] as num?)?.toDouble() ?? 0;
          if (ts > maxTs) maxTs = ts;
          final type = a['type'];
          if (ts > _soundLastAlertTs && (type == 'loss' || type == 'target')) fresh.add(a);
        }
      }
      final alertBaseline = !_soundBaselined;
      _soundLastAlertTs = maxTs;

      if (firstData || snapshot) {
        _soundKnown = current;
        _soundBaselined = true;
        _soundMode = mode;
        return; // never play on baseline / reconnect snapshot
      }

      if (!alertBaseline && fresh.isNotEmpty && _soundMayPlay) {
        sound.play(fresh.first['type'] == 'loss' ? TradeSound.stopLossHit : TradeSound.targetHit);
      }

      for (final id in current.keys) {
        if (!_soundKnown.containsKey(id)) _soundEntryPending = true;
      }
      for (final id in _soundKnown.keys) {
        if (!current.containsKey(id)) _soundExitBuf.add(_soundKnown[id]!);
      }
      _soundKnown = current;
      if ((_soundEntryPending || _soundExitBuf.isNotEmpty) && _soundFlush == null) {
        _soundFlush = Timer(const Duration(milliseconds: 1200), _soundFlushNow);
      }
    } catch (e) {
      debugPrint('sound detect failed: $e');
    }
  }

  void _soundFlushNow() {
    _soundFlush = null;
    final entered = _soundEntryPending;
    final exits = List<Map<String, dynamic>>.from(_soundExitBuf);
    _soundEntryPending = false;
    _soundExitBuf.clear();
    if (!_soundMayPlay) return;
    try {
      if (entered && soundEntryOn) sound.play(TradeSound.orderFilled);
      if (exits.isNotEmpty && soundExitOn) {
        var anySl = false;
        var anyTp = false;
        for (final p in exits) {
          if (_isStopLossExit(_closeInfo(p))) {
            anySl = true;
          } else {
            anyTp = true;
          }
        }
        if (anyTp) sound.play(TradeSound.targetHit);
        if (anySl) sound.play(TradeSound.stopLossHit);
      }
    } catch (e) {
      debugPrint('sound play failed: $e');
    }
  }

  /// Stop-loss sound for SL / trailing-SL exits, and for any other exit that
  /// ended in a loss (manual close, reversed). TP hits and profitable exits
  /// get the target sound.
  bool _isStopLossExit(_CloseInfo info) {
    final r = (info.reason ?? '').toLowerCase();
    if (r.contains('stop loss') || r.contains('sl hit')) return true;
    if (r.startsWith('tp') || r.contains('target')) return false;
    return info.pnl < 0;
  }

  /// P&L + reason for a position that just disappeared: prefers the Alerts
  /// feed entry for that trade id (exact final P&L + reason label), falls
  /// back to the last P&L seen on the open position.
  _CloseInfo _closeInfo(Map<String, dynamic> lastPos) {
    double pnl = (lastPos['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
    String? reason;
    final id = '${lastPos['id']}';
    for (final a in alerts) {
      if (a is! Map) continue;
      final d = a['d'];
      if (d is Map && '${d['trade_id']}' == id && d['reason'] != null) {
        final n = d['pnl'];
        if (n is num) pnl = n.toDouble();
        final label = d['reason_label'];
        if (label is String && label.isNotEmpty) reason = label;
        break;
      }
    }
    return _CloseInfo(pnl, reason);
  }
}
