part of 'app_provider.dart';

/// Part C4a (README_CHOP): fetches for the b3 (Chop Bot) tab. PAPER ONLY, no order code.
/// Same answer rules as the Sniper fetches: the backend map, or {"state": "off"} (404 with the switch text), {"state": "old"} (any other non-200)
/// or {"state": "error"} (the request failed). Never throws. All GETs read only; the only writes are the owner's switch and (C4b) the OK button and the replay start.
extension AppProviderChop on AppProvider {
  /// GET /api/v2/chop = {on, day, today / all {closed, wins, profit_usdt, taken, skipped, rally_missed_n / usdt, loss_avoided_n / usdt, skips_waiting}, open, open_trades[], loop {last, turns, every_s}}.
  Future<Map<String, dynamic>> fetchChop() => _sniperGet('/api/v2/chop');

  /// GET /api/v2/chop_log?limit=N = {decisions[], closed_trades[]}. decisions: symbol, side, action TAKE / SKIP, size, score, rule, why, late, v_net, v_exit, v_label, verdict right / wrong.
  Future<Map<String, dynamic>> fetchChopLog({int limit = 50}) => _sniperGet('/api/v2/chop_log?limit=$limit');

  /// GET /api/v2/chop_report = {rules[], missed_rallies[], learning {...}, alarm_pct}. Used by C4b.
  Future<Map<String, dynamic>> fetchChopReport() => _sniperGet('/api/v2/chop_report');

  /// GET /api/v2/chop_lab?interval=5m|15m&period=today|month|all = {job {running, done, total, error}, result or null}. The replay result of C2.
  Future<Map<String, dynamic>> fetchChopLab(String interval, String period) => _sniperGet('/api/v2/chop_lab?interval=$interval&period=$period');

  /// C4b: the current bot (b1) day table, read only: GET /api/calendar?bot=b1 = {month, today, month_pnl, month_trades, month_wins, days[{date, pnl, trades, wins}]}. Day = 5:30 AM IST boundary. paper_trader is not touched.
  Future<Map<String, dynamic>> fetchChopCurrentBot() => _sniperGet('/api/calendar?bot=b1');

  /// POST /api/v2/chop_switch {"on": bool}: turns b3 ON or OFF (default OFF). Answers {on} or {error / state}. Never throws.
  Future<Map<String, dynamic>> postChopSwitch(bool on) => _chopPost('/api/v2/chop_switch', {'on': on});

  /// POST /api/v2/chop_lab {"interval", "period"}: starts ONE background replay (409 if one runs). Answers {started, note, job}. Never throws.
  Future<Map<String, dynamic>> postChopLab(String interval, String period) => _chopPost('/api/v2/chop_lab', {'interval': interval, 'period': period});

  /// POST /api/v2/chop_apply: the owner's OK for the proposed weights (C4b). Answers {saved, note / changes, rows}. Never throws.
  Future<Map<String, dynamic>> postChopApply() => _chopPost('/api/v2/chop_apply', null);

  Future<Map<String, dynamic>> _chopPost(String path, Map<String, dynamic>? body) async {
    try {
      final res = await _postResilient(_u(path), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body ?? <String, dynamic>{}));
      if (res.statusCode == 404 && res.body.contains('"enabled"')) return {'state': 'off'};
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic>) return data;
      return {'state': 'old'};
    } catch (_) {
      return {'state': 'error'};
    }
  }
}
