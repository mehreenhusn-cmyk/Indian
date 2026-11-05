part of 'app_provider.dart';

/// Settings + backup + candles + Binance test calls (backend /api/settings, /api/candles, /api/binance/test-connection).
/// Moved out of app_provider.dart (NEXT-5c). Same code, same names: callers still write provider.updateSettings() etc.
extension AppProviderSettings on AppProvider {
  Future<void> fetchSettings() async {
    try {
      final res = await _getResilient(_u('/api/settings'));
      if (res.statusCode == 200) {
        settings = jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    notifyListeners();
  }

  /// PHASE 2 - instant live-state sync: fires `POST /api/settings` with just
  /// `{"live_trading_enabled": value}` the moment the Settings screen's Live
  /// Trading switch is flipped - does NOT wait for the screen's normal
  /// "Save Settings" button, so the backend's dispatcher (app.py) starts
  /// routing signals to the newly-selected engine (live vs paper) on the
  /// very next signal, not just after a manual save. Returns true if the
  /// backend confirmed the change.
  Future<bool> setLiveTradingEnabledImmediate(bool value) async {
    final server = await updateSettings({'live_trading_enabled': value});
    return server != null && server['live_trading_enabled'] == value;
  }

  /// Saves (merges) the given settings on the backend. Returns the settings
  /// map the SERVER now holds on success, or null on failure - callers can
  /// compare it against what they sent to show a "server confirmed" receipt.
  /// Asks the backend to zip the trade / alert / AI history and send it to the
  /// Telegram chat. Returns (ok, message) - never throws.
  Future<({bool ok, String message})> exportBackup() async {
    try {
      final res = await http
          .post(_u('/api/backup/export'), headers: {'Content-Type': 'application/json'})
          .timeout(const Duration(seconds: 90));
      if (res.statusCode == 200) {
        final m = jsonDecode(res.body) as Map<String, dynamic>;
        final ok = m['ok'] == true;
        return (
          ok: ok,
          message: ok ? 'Backup sent to Telegram (${m['size_kb']} KB)' : '${m['message'] ?? 'Backup fail'}',
        );
      }
      return (ok: false, message: 'Backup fail (${res.statusCode})');
    } catch (e) {
      return (ok: false, message: 'Cannot reach the backend: $e');
    }
  }

  Future<Map<String, dynamic>?> updateSettings(Map<String, dynamic> newSettings) async {
    try {
      final res = await _postResilient(
        _u('/api/settings'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(newSettings),
      );
      if (res.statusCode == 200) {
        settings = jsonDecode(res.body) as Map<String, dynamic>;
        error = null;
        notifyListeners();
        return settings;
      }
      error = 'Failed to save settings (${res.statusCode})';
    } catch (e) {
      error = 'Cannot reach backend: $e';
    }
    notifyListeners();
    return null;
  }

  /// Fetches OHLC candles for one symbol (used by the candle chart sheet
  /// opened from Market Watch / Positions). Returns an empty list on any
  /// failure instead of throwing - the chart widget shows its own
  /// "couldn't load candles" state for that.
  Future<List<dynamic>> fetchCandles(String symbol, {int limit = 600, String? tf}) async {
    try {
      // CONFIGURABLE STRATEGY TIMEFRAME: defaults to whatever the backend
      // has saved (settings['timeframe'], e.g. "5m"/"1h") so the chart
      // always matches the timeframe the strategy is actually scanning on,
      // instead of silently always requesting 5m. Callers can still pass an
      // explicit tf to override (not currently used, but keeps the option).
      final resolvedTf = tf ?? (settings['timeframe'] as String?) ?? '5m';
      final res = await _getResilient(_u('/api/candles/$symbol?limit=$limit&tf=$resolvedTf')).timeout(const Duration(seconds: 12)); // Part 1b: never an endless chart spinner
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final candles = (data['candles'] as List<dynamic>?) ?? [];
        lastCandleError = candles.isEmpty ? data['error']?.toString() : null;
        return candles;
      }
      lastCandleError = 'Backend returned ${res.statusCode}';
    } catch (e) {
      lastCandleError = 'Cannot reach backend: $e';
    }
    return [];
  }

  /// Tests the saved Binance API credentials without placing any order -
  /// called from the Settings screen's "Test Binance Connection" button.
  Future<Map<String, dynamic>> testBinanceConnection() async {
    try {
      final res = await _postResilient(_u('/api/binance/test-connection'));
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
      return {'ok': false, 'error': 'Backend returned ${res.statusCode}'};
    } catch (e) {
      return {'ok': false, 'error': 'Cannot reach backend: $e'};
    }
  }
}
