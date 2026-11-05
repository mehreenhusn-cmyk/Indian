part of 'app_provider.dart';

/// Round 24 (OwlSniper, read-only): the three GET routes of the Sniper, as plain fetches for the screens of Rounds 25 to 28.
/// Round 30 adds ONE write call, postSniperEnter (paper only). Same answer rules as the Brain fetches: the backend map, or {"state": "off"} (404 with the switch text), {"state": "old"} (any other non-200, e.g. an older backend)
/// or {"state": "error"} (the request failed). Never throws. Nothing here sends an order: the routes only read.
/// fetchSniper() itself stays in app_provider_brain.dart (Part S6) and now also carries compare, executor and barrier_rule.
extension AppProviderSniper on AppProvider {
  /// Live scan with retries: fresh order cards with their triple-barrier lines (profit, stop, time). The backend caches it for 25 seconds.
  Future<Map<String, dynamic>> fetchSniperLive() => _sniperGet('/api/v2/sniper_live');

  /// Part 5 (LEARN, paper only): GET /api/v2/sniper_learn = {learn: {enabled, floor, size_usdt, open, progress {n, target, wins, losses, net_usdt, text}, kill, ...}, last_turn: {auto, opened, cards, why}, turns}.
  Future<Map<String, dynamic>> fetchSniperLearn() => _sniperGet('/api/v2/sniper_learn');

  /// R26b: GET /api/v2/sniper_gates = {gates[8] PASS / FAIL / WAIT, explore {state, text}, real {state, text}, reason, cards, mistakes {trades, counts, blocked[], journal[], rule}}. Read only.
  Future<Map<String, dynamic>> fetchSniperGates() => _sniperGet('/api/v2/sniper_gates');

  /// R29a: GET /api/v2/sniper_trades = {open[], closed[]} the Sniper trade record: signal, reason, basis[], entry, take_profit, stop_loss, expected_usdt, risk_usdt, rr, max_hold_sec, typical_hold_sec, and for closed ones pnl_usdt, held_sec, exit_reason, lesson. Read only.
  Future<Map<String, dynamic>> fetchSniperTrades() => _sniperGet('/api/v2/sniper_trades');

  /// R28b: GET /api/v2/sniper_days = {today, week, days[7]}: Sniper paper results for today and the last 7 days (day starts 5:30 AM IST), BTC never counted. block = {n, wins, losses, win_pct, net, avg, best, worst, profit, loss, lanes, coins_top, coins_worst, exits, tags} (n = 0 has a text only). Read only.
  Future<Map<String, dynamic>> fetchSniperDays() => _sniperGet('/api/v2/sniper_days');

  /// R30: GET /api/v2/sniper_ctx = {state, session, ctx {btc_1, btc_3, btc_12, btc_trend, hour}, age_sec, btc_counts_in_pnl: false}. BTC move + session the Sniper learns from. Read only.
  Future<Map<String, dynamic>> fetchSniperCtx() => _sniperGet('/api/v2/sniper_ctx');

  /// Part 16 (R33b): GET /api/v2/sniper_watch = {state OK / NO_DATA / ERROR, saved_at, scanned, stale, fav_n, armed_n, near_n, rows[{rank, symbol, source FAV / MOVER / BOTH, state ARMED / NEAR / WATCH, armed, side, age, move_15m_pct, move_1h_pct, regime, mode, mode_learned, price, entry_price, stop_loss, take_profit, stop_pct, rr, reason}]}. Read only.
  Future<Map<String, dynamic>> fetchSniperWatch() => _sniperGet('/api/v2/sniper_watch');

  /// Part 17a: GET /api/v2/sniper_eva = {state OK / NOT_ENOUGH_DATA, text, min_n, n_expected, n_compared, n_waiting, lanes {EXPLORE / LEARN / REAL: {state NOT_ENOUGH_DATA / ON_TRACK / BELOW_EXPECTED / ABOVE_EXPECTED, n, text, lines[]}}}. Expected (Risk Box at entry) vs real paper result. Read only.
  Future<Map<String, dynamic>> fetchSniperEva() => _sniperGet('/api/v2/sniper_eva');

  /// Part 17a: GET /api/v2/sniper_opp = {state OK / NO_TRADES, text, counts, rows[{id, symbol, trade_id, decision STAY / TAKE_PROFIT / ROTATE / KEEP, text}]}. One rough line per open Sniper paper trade. Read only.
  Future<Map<String, dynamic>> fetchSniperOpp() => _sniperGet('/api/v2/sniper_opp');

  /// Part 17c: GET /api/v2/grad_dual = {state OK / error / busy, grad {arms {current_bot, brain_own: {verdict, passed, failed, waiting, checks[{key, label, state, value, need}], numbers}}, notes}, auto {last_run_ts, runs, steps {scalp_lab, ledger: {ok, note}}}}. Graduation gate of the Dual Bot / Brain (paper only) + the automatic Scalp Lab / Ledger run. Read only.
  Future<Map<String, dynamic>> fetchGradDual() => _sniperGet('/api/v2/grad_dual');

  /// Part 17c: GET /api/v2/sniper_bridge = {state, by_source {dual, brain, main: {records, rows, labels, examples}}, learn {...}, lines[]}: how much the Sniper learns from the trades of the other bots. Read only (the backend caches it 10 minutes).
  Future<Map<String, dynamic>> fetchSniperBridge() => _sniperGet('/api/v2/sniper_bridge');

  /// Part 17c: Dual Bot side data, read only: GET /api/layers/pa and /api/layers/vol = {running, report, last, error}, GET /api/dual_universe = {days[], saved_days, cap, err}, GET /api/archive_check = {state match / differ / error / none, json_closed, db_closed, missing, text}.
  Future<Map<String, dynamic>> fetchLayerPa() => _sniperGet('/api/layers/pa');
  Future<Map<String, dynamic>> fetchLayerVol() => _sniperGet('/api/layers/vol');
  Future<Map<String, dynamic>> fetchDualUniverse() => _sniperGet('/api/dual_universe');
  Future<Map<String, dynamic>> fetchArchiveCheck() => _sniperGet('/api/archive_check');

  /// Part 17d: GET /api/v2/data_health = {state OK / error, candles {switch ON / OFF, owner_off, runner_running, runner_beat_age_s}, history {by_source {dual, brain, main: {records, ready, needs_fetch, known_gap, too_old, too_recent}}, requests_needed, lines[]}, learning {state EXPLORE / LEARNED, n_train, n_test, days, reasons[], age_s}, jobs[{key, label, age_s}]}. Read only.
  Future<Map<String, dynamic>> fetchDataHealth() => _sniperGet('/api/v2/data_health');

  /// Part 12 (Risk Box, read only): GET /api/v2/sniper_riskbox = {state: OK / NOT_ENOUGH_DATA / NO_SIGNAL / busy / error / off, text, lines, n, min_n, win_pct, exp_r, exp_usdt, median_secs, worst_r, ...}.
  /// side empty = the Sniper's own signal. Same answer rules as the other Sniper fetches. Never throws.
  Future<Map<String, dynamic>> fetchSniperRiskBox(String symbol, {String tf = '5m', String side = '', double size = 10, double lev = 1}) =>
      _sniperGet('/api/v2/sniper_riskbox?symbol=${Uri.encodeQueryComponent(symbol)}&tf=$tf&side=$side&size=$size&lev=$lev');

  /// Part 35 (small account card, read only): GET /api/v2/sniper_capital = {state: OK / NOT_ENOUGH_DATA / off / error, text, lines, book, n_trades, capital, one_trade, ladder, report {throttle, plan, daily, weekly, capital_now}, simulated: true}.
  /// book = learn or real (one book per answer, never added). The USDT is a replay of the saved paper results in R at the owner's capital, not real money. Same answer rules as the other Sniper fetches. Never throws.
  Future<Map<String, dynamic>> fetchSniperCapital({double capital = 10, double stop = 0.5, double lev = 10, double risk = 1, String book = 'learn'}) =>
      _sniperGet('/api/v2/sniper_capital?capital=$capital&stop=$stop&lev=$lev&risk=$risk&book=$book');

  /// Part 39 (study verdicts, read only): GET /api/v2/sniper_prior = {state: OK / busy / error / off, text, lines, rows [{id, source, kind, what, n, date, verdict, line, entry_known, used_by_sniper: YES / TESTING / NO, why}], counts (per verdict), used_counts, sources, cands, notes, fresh_days}.
  /// The backend builds it slowly and caches it 10 minutes (state busy = still building). Same answer rules as the other Sniper fetches. Never throws.
  Future<Map<String, dynamic>> fetchSniperPrior({String tf = '5m', int freshDays = 30}) => _sniperGet('/api/v2/sniper_prior?tf=$tf&fresh_days=$freshDays');

  /// Part 44 (self log): GET /api/v2/sniper_selflog = {state: OK / EMPTY / broken / busy / error / off, text, lines, entries [{ts, kind LEARNED / MISTAKE / CHANGED, text, src}] newest first, counts, n_total, last_look, answer_age_sec}.
  /// The backend builds it slowly, caches it 10 minutes and writes only the self log's own small file. Same answer rules as the other Sniper fetches. Never throws.
  Future<Map<String, dynamic>> fetchSniperSelfLog({int limit = 60}) => _sniperGet('/api/v2/sniper_selflog?limit=$limit');

  /// Part 48 (App Problems, read only): GET /api/v2/app_problems = {state: OK / PROBLEMS / busy / off, headline, counts {BAD, WARN, INFO}, items [{sev, area, where, text, fix, when}], copy_text, ...}.
  /// Same answer rules as the other Sniper fetches (off / old / error). Never throws.
  Future<Map<String, dynamic>> fetchAppProblems() => _sniperGet('/api/v2/app_problems');

  /// Health of the Sniper: model, scan, candles, switches, executor (NOT_AVAILABLE until it is built). overall = OK / WARN / BAD.
  Future<Map<String, dynamic>> fetchSniperHealth() => _sniperGet('/api/v2/sniper_health');

  /// Round 28 (Data Doctor): the newest candle gap records (GET /api/v2/gaps, the backend caps it at 200 rows) and the collector status (GET /api/v2/status: candle switch, store size).
  Future<Map<String, dynamic>> fetchV2Gaps() => _sniperGet('/api/v2/gaps?limit=200');
  Future<Map<String, dynamic>> fetchV2Status() => _sniperGet('/api/v2/status');

  /// Round 30 (PAPER only): PAPER ENTER for one coin. The backend runs every executor gate (armed, paper, TRENDING, 85% floor proven, stop range, cap 1, kill switch, same signal once)
  /// and answers {decision: OPEN / BLOCKED, gate, text}. Not armed = the real gate says "OFF (not armed)"; since Part 4 the answer also carries lane (REAL / LEARN) and a tiny paper LEARN trade may open. Never throws. No real order exists.
  Future<Map<String, dynamic>> postSniperEnter(String symbol) async {
    try {
      final res = await _postResilient(
        _u('/api/v2/sniper_enter'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'symbol': symbol}),
      );
      if (res.statusCode == 404 && res.body.contains('"enabled"')) return {'decision': 'BLOCKED', 'text': 'The V2 API is off (the file v2_api_enabled is missing).'};
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic>) return data;
      return {'decision': 'BLOCKED', 'text': 'Unexpected answer from the backend. Nothing was opened.'};
    } catch (_) {
      return {'decision': 'BLOCKED', 'text': 'The request failed. Nothing was opened.'};
    }
  }

  Future<Map<String, dynamic>> _sniperGet(String path) async {
    final sw = Stopwatch()..start();
    try {
      final res = await _getResilient(_u(path));
      if (sw.elapsed.inSeconds >= 8) AppErrorLog.add(path, 'Slow: the backend took ${sw.elapsed.inSeconds} s to answer.', slow: true);
      if (res.statusCode == 404 && res.body.contains('"enabled"')) {
        AppErrorLog.add(path, 'The V2 data API is off (404, file v2_api_enabled).');
        return {'state': 'off'};
      }
      if (res.statusCode != 200) {
        AppErrorLog.add(path, 'The backend answered HTTP ${res.statusCode} (old backend, or the route is not mounted).');
        return {'state': 'old', 'code': res.statusCode};
      }
      final data = jsonDecode(res.body);
      if (data is Map<String, dynamic>) return data;
      AppErrorLog.add(path, 'The answer was not a JSON object.');
      return {'state': 'old'};
    } catch (_) {
      AppErrorLog.add(path, 'The request failed (backend not reachable, or the answer was not JSON).');
      return {'state': 'error'};
    }
  }
}

/// Part 48 (FILE 57): the app's OWN list of failed or slow fetches, for the App Problems page. In memory only (empty after an app restart), newest first, max 30.
/// The same problem again within 60 seconds is not added twice. Only the path is kept (no query text, no token). Nothing here is sent anywhere.
class AppErrorEntry {
  final DateTime at;
  final String path;
  final String what;
  final bool slow;
  const AppErrorEntry(this.at, this.path, this.what, this.slow);
}

class AppErrorLog {
  AppErrorLog._();
  static final List<AppErrorEntry> items = <AppErrorEntry>[];

  static void add(String path, String what, {bool slow = false}) {
    final clean = path.split('?').first;
    final now = DateTime.now();
    if (items.isNotEmpty) {
      final top = items.first;
      if (top.path == clean && top.what == what && now.difference(top.at).inSeconds < 60) return;
    }
    items.insert(0, AppErrorEntry(now, clean, what, slow));
    if (items.length > 30) items.removeLast();
  }

  static void clear() => items.clear();
}
