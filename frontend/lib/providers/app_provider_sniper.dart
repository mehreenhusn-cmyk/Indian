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
