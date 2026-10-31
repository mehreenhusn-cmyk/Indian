part of 'app_provider.dart';

/// Position actions: close one / all, panic, TP target, SL moves (backend /api/close*, /api/panic*, /api/move_sl*).
/// Moved out of app_provider.dart (NEXT-5b). Same code, same names: callers still write provider.closePosition() etc.
/// An extension in a part file sees every private member of AppProvider (same library).
extension AppProviderPositions on AppProvider {
  /// Closes one position. `tradeId` is the PAPER int trade_id or the LIVE
  /// symbol (String) - see position_card.dart's tradeId comment; either
  /// way it's just interpolated into the URL and compared with `==`, so no
  /// cast is needed here. Returns a result map the caller can show a real
  /// message from: {"ok": bool, "forced": bool, "error": String?}.
  /// "forced": true means the live price feed was dead for this symbol and
  /// the backend force-closed it at the last-known price instead of
  /// leaving it stuck open forever (see paper_trader.close_position_manual).
  Future<Map<String, dynamic>> closePosition(Object tradeId) async {
    // Optimistic UI: remove the card from the list immediately instead of
    // waiting for the close request + the fetchStatus() round-trip after
    // it - the position visibly disappears the instant the user confirms,
    // matching a real exchange app's feel. Rolled back (position re-added)
    // if the request itself fails OR the backend reports ok:false (a
    // silent-failure case, like a symbol with no fallback price at all).
    final backup = List<dynamic>.from(positions);
    positions = positions.where((p) => p['id'] != tradeId).toList();
    notifyListeners();
    try {
      final res = await _postResilient(_u('/api/close/$tradeId'));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (data['ok'] != true) {
        positions = backup;
        error = data['error']?.toString() ?? 'Close failed';
        notifyListeners();
        await fetchStatus();
        return data;
      }
      HapticFeedback.mediumImpact();
      await fetchStatus();
      return data;
    } catch (e) {
      // Rollback - the optimistic removal above turned out to be wrong.
      positions = backup;
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return {"ok": false, "forced": false, "error": error};
    }
  }

  /// Flatten All. Returns {"closed_count", "failed_count", "details": [...]}
  /// (or null if the request itself failed) so the caller (positions_screen)
  /// can show a message that actually matches what happened, instead of
  /// always claiming success.
  Future<Map<String, dynamic>?> closeAll() async {
    // Optimistic UI: clear the whole list immediately (same reasoning as
    // closePosition above); rolled back to whatever fetchStatus() finds if
    // the backend reports any failures, so a stuck/dead-feed position that
    // couldn't even force-close reappears instead of silently vanishing.
    final backup = List<dynamic>.from(positions);
    positions = [];
    notifyListeners();
    try {
      final res = await _postResilient(_u('/api/close_all?$botQuery'));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      HapticFeedback.heavyImpact();
      await fetchStatus();
      if ((data['failed_count'] as num?)?.toInt() != 0) {
        // Some positions didn't close - fetchStatus() above already
        // refreshed `positions` from the server's real state, so nothing
        // further to restore here; backup only needed on total failure.
      }
      return data;
    } catch (e) {
      positions = backup;
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return null;
    }
  }

  /// EMERGENCY PANIC KILL SWITCH (POST /api/flatten). Unlike closeAll()
  /// above (paper positions only), this closes every REAL exchange
  /// position too when live trading is on, then disables live_trading so
  /// no further auto-entries can open on either engine - see api_server.py's
  /// /api/flatten docstring for the exact ordering/safety reasoning.
  /// Returns the same {"ok", "live_closed_count", "live_failed_count",
  /// "paper_closed_count", "paper_failed_count", ...} shape the backend
  /// sends (or null if the request itself failed), so the caller can show
  /// a result that actually matches what happened.
  Future<Map<String, dynamic>?> panicFlatten() async {
    // Optimistic UI: clear positions immediately, same reasoning as
    // closeAll() - rolled back to the real state via fetchStatus() below.
    final backup = List<dynamic>.from(positions);
    positions = [];
    notifyListeners();
    try {
      final res = await _postResilient(_u('/api/flatten'));
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      HapticFeedback.heavyImpact();
      // The backend just force-disabled live_trading_enabled as part of
      // the panic action - refresh local settings so the Settings screen
      // and the LIVE/PAPER badge never show a stale ON state.
      await fetchSettings();
      await fetchStatus();
      return data;
    } catch (e) {
      positions = backup;
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return null;
    }
  }


  /// ones WOULD close for mode='profit'/'loss' plus their total P&L -
  /// doesn't close anything. Used to show a confirmation dialog before
  /// Close All Profit/Loss actually runs. Returns null if the request
  /// itself failed (backend unreachable etc.).
  Future<Map<String, dynamic>?> previewCloseAll(String mode) async {
    try {
      final res = await _getResilient(_u('/api/preview_close_all?mode=$mode&$botQuery'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        if (data['ok'] == true) return data;
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  /// NEW (Part 20): the SAFE close preview. /api/v2/preview_close picks exactly what the real button would close, in the SAME
  /// mode (LIVE = the exchange positions, PAPER = the paper snapshot). mode: profit | loss | all | flatten. Closes nothing.
  /// Returns null when the backend does not have it (older backend / not mounted / any non-200): the caller then uses the old
  /// previewCloseAll() exactly as before. Otherwise the backend's own answer map ({"ok": true, "mode": "live"|"paper", "count",
  /// "total_pnl_usdt", "positions", "parts", ...} or {"ok": false, "error": "..."}), or {"ok": false, "unreachable": true} when
  /// the request itself failed (so the caller does not wait for a second timeout).
  Future<Map<String, dynamic>?> previewClose(String mode) async {
    try {
      final res = await _getResilient(_u('/api/v2/preview_close?mode=$mode&$botQuery'));
      if (res.statusCode != 200) return null;
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic> && data.containsKey('ok')) return data;
      return null;
    } catch (_) {
      return {'ok': false, 'unreachable': true};
    }
  }

  /// Closes every open position currently in profit at a fresh live price.
  /// Returns the number closed on success, or null if the request itself
  /// failed (backend unreachable etc.) - so the caller can show a
  /// SnackBar either way instead of the button silently doing nothing.
  Future<int?> closeAllProfit() async {
    try {
      final res = await _postResilient(_u('/api/close_all_profit?$botQuery'));
      HapticFeedback.mediumImpact();
      await fetchStatus();
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return (data['closed'] as num?)?.toInt() ?? 0;
      }
      return null;
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return null;
    }
  }

  /// Closes every open position currently in loss at a fresh live price.
  /// Same null-on-failure/count-on-success contract as closeAllProfit().
  Future<int?> closeAllLoss() async {
    try {
      final res = await _postResilient(_u('/api/close_all_loss?$botQuery'));
      HapticFeedback.mediumImpact();
      await fetchStatus();
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return (data['closed'] as num?)?.toInt() ?? 0;
      }
      return null;
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return null;
    }
  }

  /// Tapping a TP1-4 box that price hasn't reached yet - sets that level
  /// as the new full-close target. Pass level=null to clear back to the
  /// default target (TP4).
  Future<void> setTargetTp(Object tradeId, int? level) async {
    try {
      await _postResilient(
        _u('/api/set_target_tp/$tradeId'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'level': level}),
      );
      HapticFeedback.selectionClick();
      await fetchStatus();
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
    }
  }

  /// Tapping a TP1-4 box that price has ALREADY passed - trails the SL up
  /// to that level instead of closing the trade. Returns false (no-op) if
  /// the backend refused because it would loosen the SL.
  Future<bool> trailSlToLevel(Object tradeId, int level) async {
    try {
      final res = await _postResilient(
        _u('/api/trail_sl/$tradeId'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'level': level}),
      );
      await fetchStatus();
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final ok = data['ok'] == true;
        if (ok) HapticFeedback.selectionClick();
        return ok;
      }
      return false;
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return false;
    }
  }

  /// "Move Stop Loss to Break-Even (Entry)" quick pill on a position card.
  /// Returns false (no-op) if the SL is already at or past entry.
  Future<bool> moveSlToBreakeven(Object tradeId) async {
    try {
      final res = await _postResilient(_u('/api/move_sl_breakeven/$tradeId'));
      await fetchStatus();
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final ok = data['ok'] == true;
        if (ok) HapticFeedback.mediumImpact();
        return ok;
      }
      return false;
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return false;
    }
  }

  /// NEW (Part 62): the read-only fees + tax report (/api/v2/fees_tax, made by backend/v2_reports.py). Changes nothing.
  /// Returns the backend's report map, or {"state": "off"} (404: the V2 API switch file is not there), {"state": "old"} (any other
  /// non-200, e.g. older backend) or {"state": "error"} when the request itself failed. Never throws.
  Future<Map<String, dynamic>> fetchFeesTax() async {
    try {
      final res = await _getResilient(_u('/api/v2/fees_tax'));
      if (res.statusCode == 404) return {'state': 'off'};
      if (res.statusCode != 200) return {'state': 'old', 'code': res.statusCode};
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic>) return data;
      return {'state': 'old'};
    } catch (_) {
      return {'state': 'error'};
    }
  }

  /// Part 42 (Ledger screen): the read-only Knowledge Ledger list. Returns the backend map, or {"state": "off"} (404), {"state": "old"}
  /// (any other non-200, e.g. an older backend) or {"state": "error"} (request failed). Never throws.
  Future<Map<String, dynamic>> fetchLedger() => _ledgerGet('/api/v2/ledger');

  /// One finding: all versions, diffs and the trace chain of [version] (null = newest). Same answer shape rules as fetchLedger.
  Future<Map<String, dynamic>> fetchLedgerOne(String findingId, {int? version}) =>
      _ledgerGet('/api/v2/ledger/${Uri.encodeComponent(findingId)}${version == null ? '' : '?version=$version'}');

  /// Part 37 (Data Explorer screen): the read-only summary (what happened / tested / learned / unknown). Same answer rules as fetchLedger.
  Future<Map<String, dynamic>> fetchSummary() => _ledgerGet('/api/v2/summary');

  /// Part 34 (Radar screen): the three read-only Radar answers for the newest 7 cohort days, in one map {radar, outcomes, moves}. If the
  /// first one cannot be read, that answer (with its state off / old / error) is returned as it is. Never throws.
  Future<Map<String, dynamic>> fetchRadar() async {
    final r = await Future.wait([_ledgerGet('/api/v2/radar?days=7'), _ledgerGet('/api/v2/radar_outcomes?days=7'), _ledgerGet('/api/v2/radar_moves?days=7')]);
    if (r[0]['days'] is! List) return r[0];
    return {'radar': r[0], 'outcomes': r[1], 'moves': r[2]};
  }

  /// Part 46 (Setup Finder screen): the two read-only Setup answers for the last [days] days (1 to 7), in one map {setups, forward}. If the
  /// forward answer cannot be read, that answer (with its state off / old / error) is returned as it is. Never throws.
  Future<Map<String, dynamic>> fetchSetups(int days) async {
    final r = await Future.wait([_ledgerGet('/api/v2/setups?days=$days'), _ledgerGet('/api/v2/setups_forward?days=$days')]);
    if (r[1]['types'] is! List) return r[1];
    return {'setups': r[0], 'forward': r[1]};
  }

  /// Part 49 (Pre-pump screen): the two read-only answers of the PUMP / DUMP watch in one map {watch, early}: today's watch lists (Part 48, old cases from the last 7
  /// days) and the early-sign numbers of those old days (Part 47). If the watch answer cannot be read, that answer (with its state off / old / error) is returned as it is. Never throws.
  Future<Map<String, dynamic>> fetchPrepump() async {
    final r = await Future.wait([_ledgerGet('/api/v2/prepump_watch?days=7'), _ledgerGet('/api/v2/prepump?days=7')]);
    if (r[0]['today'] is! Map) return r[0];
    return {'watch': r[0], 'early': r[1]};
  }

  /// Part 61 (Stop-wick screen): the three read-only Stop-wick answers for the last [days] days (1 to 7), in one map {marks, forward, reentry}.
  /// If the marks answer cannot be read, that answer (with its state off / old / error) is returned as it is. Never throws.
  Future<Map<String, dynamic>> fetchWickStudy(int days) async {
    final r = await Future.wait([_ledgerGet('/api/v2/wickstudy?days=$days'), _ledgerGet('/api/v2/wickstudy_forward?days=$days'), _ledgerGet('/api/v2/wickstudy_reentry?days=$days')]);
    if (r[0]['types'] is! List) return r[0];
    return {'marks': r[0], 'forward': r[1], 'reentry': r[2]};
  }

  /// Part 57 (Scalp Lab screen): the two read-only Scalp Lab answers in one map {report, large}: the ledger (Part 54) and the big-trade replay with real vs hypothetical side by side (Part 56).
  /// [days] 0 = all trades, else 1 to 365. Each answer keeps its own state (off / old / error) so one failing answer never hides the other. Never throws.
  Future<Map<String, dynamic>> fetchScalpLab(int days) async {
    final big = days > 0 ? '/api/v2/scalp_large5?days=$days' : '/api/v2/scalp_large5';
    final r = await Future.wait([_ledgerGet('/api/v2/scalp_report'), _ledgerGet(big)]);
    return {'report': r[0], 'large': r[1]};
  }

  /// Part 75 (Screenshot Check screen): the read-only Part 74 answer for ONE coin and ONE time ([at] = UTC text like 2026-10-31 14:30, empty = newest candle). Same answer rules as fetchLedger
  /// (state off / old / error; a bad coin or time comes back as state old with code 400). Never throws.
  Future<Map<String, dynamic>> fetchScreenCheck(String symbol, String interval, String at) =>
      _ledgerGet('/api/v2/screen_check?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}&at=${Uri.encodeQueryComponent(at)}');

  /// Part 77 (Brain chat screen): ONE question to the read-only Part 76 route. The answer is Claude's wording of backend facts (state ok / no_key / quota / bad_key / rate / offline ...) or state off / old / error. Never throws.
  /// One send only (the helper never repeats a slow GET), so one question = one Claude call; the answer can take up to about 40 s.
  Future<Map<String, dynamic>> fetchBrainChat(String q) => _ledgerGet('/api/v2/brain_chat?q=${Uri.encodeQueryComponent(q)}');

  /// Part 81 (Results screen): the read-only Part 80 route. Which groups of closed trades make or lose money, net of fee; no setting, no order.
  Future<Map<String, dynamic>> fetchResults() => _ledgerGet('/api/v2/results');

  /// Part 86b (Brain Today screen): read-only Part 86a routes. Today = report lines + newest answer per coin; chart = the CURRENT chart of one coin in plain sentences.
  Future<Map<String, dynamic>> fetchBrainToday() => _ledgerGet('/api/v2/brain_today?source=PAPER');

  Future<Map<String, dynamic>> fetchBrainChart(String symbol, String interval) =>
      _ledgerGet('/api/v2/brain_chart?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  /// Part 87 (Signal Detail + Active Paper Trade): read-only Part 87 routes.
  Future<Map<String, dynamic>> fetchBrainSignal(String symbol, String interval) =>
      _ledgerGet('/api/v2/brain_signal?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  Future<Map<String, dynamic>> fetchBrainTrade(String symbol, String interval) =>
      _ledgerGet('/api/v2/brain_trade?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  Future<Map<String, dynamic>> _ledgerGet(String path) async {
    try {
      final res = await _getResilient(_u(path));
      if (res.statusCode == 404 && res.body.contains('"enabled"')) return {'state': 'off'};
      if (res.statusCode != 200) return {'state': 'old', 'code': res.statusCode};
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic>) return data;
      return {'state': 'old'};
    } catch (_) {
      return {'state': 'error'};
    }
  }
}
