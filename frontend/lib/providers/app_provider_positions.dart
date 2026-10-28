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
}
