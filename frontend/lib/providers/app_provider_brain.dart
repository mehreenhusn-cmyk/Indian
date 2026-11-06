part of 'app_provider.dart';

/// Part M4c (split of app_provider_positions.dart, which had grown to 389 lines): the Brain Trader / Brain screens' read-only fetches, MOVED here with the same code and the same names
/// (provider.fetchBrainToday() etc. are called exactly as before). Every one is a GET on /api/v2/..., never throws, answers a map or {"state": off / old / error}.
/// An extension in a part file sees every private member of AppProvider (same library).
extension AppProviderBrain on AppProvider {
  /// Part 86b (Brain Today screen): read-only Part 86a routes. Today = report lines + newest answer per coin; chart = the CURRENT chart of one coin in plain sentences.
  Future<Map<String, dynamic>> fetchBrainToday() => _brainGet('/api/v2/brain_today?source=PAPER');

  Future<Map<String, dynamic>> fetchBrainChart(String symbol, String interval) =>
      _brainGet('/api/v2/brain_chart?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  /// Part 87 (Signal Detail + Active Paper Trade): read-only Part 87 routes.
  Future<Map<String, dynamic>> fetchBrainSignal(String symbol, String interval) =>
      _brainGet('/api/v2/brain_signal?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  Future<Map<String, dynamic>> fetchBrainTrade(String symbol, String interval) =>
      _brainGet('/api/v2/brain_trade?symbol=${Uri.encodeQueryComponent(symbol)}&interval=${Uri.encodeQueryComponent(interval)}');

  /// Part 88d (What the Brain is learning): read-only Part 88c routes. Playbook = USE / AVOID / thin chart states per indicator; what-if = skip / only rules (dim:label joined by |) on the same closed paper trades.
  /// Part 88e: [interval] 5m / 15m and [state] TREND / SIDEWAYS / CONSOLIDATION / BREAKOUT are optional (empty = no filter).
  Future<Map<String, dynamic>> fetchBrainPlaybook([String interval = '', String state = '']) {
    final q = '${interval.isEmpty ? '' : '&interval=${Uri.encodeQueryComponent(interval)}'}${state.isEmpty || state == 'ALL' ? '' : '&state=${Uri.encodeQueryComponent(state)}'}';
    return _brainGet('/api/v2/brain_playbook?source=PAPER$q');
  }

  /// Part 89c (Zone, squeeze and limits studies): read-only Part 89a / 89b routes. They only read the study files the auto-runner makes every 6 hours.
  Future<Map<String, dynamic>> fetchBrainZones() => _brainGet('/api/v2/brain_zones?interval=5m');

  Future<Map<String, dynamic>> fetchBrainLimits() => _brainGet('/api/v2/brain_limits?interval=5m');

  /// Part 90b (Brain Health): read-only Part 90a route. Pipeline, sample coverage per market state, safety, graduation, what is missing. Live is always LOCKED.
  Future<Map<String, dynamic>> fetchBrainHealth([String interval = '5m']) => _brainGet('/api/v2/brain_health?source=PAPER&interval=${Uri.encodeQueryComponent(interval)}');

  /// Part X2 (Day calendar + comparison): read-only Part X1 route. Owl Brain vs Current Bot vs Take-All (simulated) for one UTC day + a 30-day calendar. day = YYYY-MM-DD or null (today).
  Future<Map<String, dynamic>> fetchBrainCompare([String source = 'PAPER', String? day]) =>
      _brainGet('/api/v2/brain_compare?source=${Uri.encodeQueryComponent(source)}${day == null ? '' : '&day=${Uri.encodeQueryComponent(day)}'}');

  /// Part 91b (Simple Results): read-only Part 91a route. One verdict word, net, worst dip, losing streak, equity line, USE / STOP lines. Source = PAPER, SHADOW or REPLAY (never LIVE).
  Future<Map<String, dynamic>> fetchBrainVerdict([String source = 'PAPER']) => _brainGet('/api/v2/brain_verdict?source=${Uri.encodeQueryComponent(source)}');

  /// E6: read-only route brain_why = {state, total, taken, waited, skipped, no_opinion, open_now, reasons[{decision, reason, n}], last[], lines[]}: why the Brain is not trading today.
  Future<Map<String, dynamic>> fetchBrainWhy([String source = 'PAPER']) => _brainGet('/api/v2/brain_why?source=${Uri.encodeQueryComponent(source)}');

  /// Part M3 (Brain Dashboard): read-only route brain_dash. Today net, Brain vs Current Bot 30 days, open trades, signals, daily loss cap, recent days. Source = PAPER, SHADOW or REPLAY (never LIVE).
  Future<Map<String, dynamic>> fetchBrainDash([String source = 'PAPER']) => _brainGet('/api/v2/brain_dash?source=${Uri.encodeQueryComponent(source)}');

  /// Part L2 (Learning Progress): read-only Part L1 route. Today (trades / profit / loss / net), 30 days, 5 weeks (losing trades per 10), trend, mistakes, fixed, learned. Source = PAPER, SHADOW or REPLAY (never LIVE).
  Future<Map<String, dynamic>> fetchBrainProgress([String source = 'PAPER']) => _brainGet('/api/v2/brain_progress?source=${Uri.encodeQueryComponent(source)}');
  Future<Map<String, dynamic>> fetchBrainExits([String source = 'REPLAY']) => _brainGet('/api/v2/brain_exits?source=${Uri.encodeQueryComponent(source)}');
  Future<Map<String, dynamic>> fetchSysHealth() => _brainGet('/api/v2/sys_health');
  Future<Map<String, dynamic>> fetchBrainMonth([String source = 'PAPER', String? month]) =>
      _brainGet('/api/v2/brain_month?source=${Uri.encodeQueryComponent(source)}${month == null ? '' : '&month=${Uri.encodeQueryComponent(month)}'}');

  Future<Map<String, dynamic>> fetchBrainWhatif(String skip, String only) =>
      _brainGet('/api/v2/brain_whatif?source=PAPER&skip=${Uri.encodeQueryComponent(skip)}&only=${Uri.encodeQueryComponent(only)}');

  /// Part M4b (Brain and Activity timeline): read-only route brain_timeline. One UTC day: Brain decisions / trades next to the Current Bot's trades + a per-coin table. day = YYYY-MM-DD or null (today). Source = PAPER, SHADOW or REPLAY (never LIVE).
  Future<Map<String, dynamic>> fetchBrainTimeline([String source = 'PAPER', String? day]) =>
      _brainGet('/api/v2/brain_timeline?source=${Uri.encodeQueryComponent(source)}${day == null ? '' : '&day=${Uri.encodeQueryComponent(day)}'}');

  /// Same answer rules as _ledgerGet in the positions file (kept as its own copy so the two extensions never call each other): the backend map, or {"state": "off"} (404 with the switch text),
  /// {"state": "old"} (any other non-200, e.g. an older backend) or {"state": "error"} (the request failed). Never throws.
  Future<Map<String, dynamic>> _brainGet(String path) async {
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

  /// Part N2 (Brain Ready?): read-only route brain_ready. What the Brain does by itself + 8 plain checks. Live is always LOCKED.
  Future<Map<String, dynamic>> fetchBrainReady([String source = 'PAPER']) => _brainGet('/api/v2/brain_ready?source=${Uri.encodeQueryComponent(source)}');

  /// Part S6 (OwlSniper): read-only route sniper (Part S5). Banner, order cards, equity of the unseen test days, floor proof, insight report. Watch only, never an order.
  Future<Map<String, dynamic>> fetchSniper() => _brainGet('/api/v2/sniper');

  /// Round 8 (Study Lab hub): read-only route /api/v2/verdicts = one verdict card per study (see backend/v2_verdicts.py). Same answer rules as every fetch here.
  Future<Map<String, dynamic>> fetchVerdicts() => _brainGet('/api/v2/verdicts');

  /// R16b (BTC Lab): read-only route /api/v2/btc_lab = BTC's OWN numbers (BTC is the indicator test coin, kept out of every total).
  Future<Map<String, dynamic>> fetchBtcLab() => _brainGet('/api/v2/btc_lab');

  /// R6a (Sniper modes): read-only route /api/v2/sniper_modes = SCALP / SHORT_SWING / SWING per market state (advice only). A screen for it comes in R17.
  Future<Map<String, dynamic>> fetchSniperModes() => _brainGet('/api/v2/sniper_modes');

  /// R7 (Sniper lessons): read-only route /api/v2/sniper_lessons = tag per closed Sniper trade, setup penalty, 3 lessons of the week (advice only). A screen for it comes in R17.
  Future<Map<String, dynamic>> fetchSniperLessons() => _brainGet('/api/v2/sniper_lessons');

  /// R11 (Lab loss source): read-only route /api/v2/lab_loss = where the money is lost (Entry / Exit / Sideways, in R) + the two fix checks from the learners (advice only). Shown by LabLossSourceCard.
  Future<Map<String, dynamic>> fetchLabLoss() => _brainGet('/api/v2/lab_loss');

  /// R24a (Current Bot vs Sniper, same days): read-only route /api/v2/sniper_h2h = % per trade of both sides on the days both traded + a verdict from the backend only.
  Future<Map<String, dynamic>> fetchSniperH2H() => _brainGet('/api/v2/sniper_h2h');

  /// R24b (Sniper graduation checklist): read-only route /api/v2/sniper_grad = 7 checks PASS / FAIL / WAIT + an overall word from the backend only.
  Future<Map<String, dynamic>> fetchSniperGrad() => _brainGet('/api/v2/sniper_grad');

  /// R13 (Study Lab results board): read-only route /api/v2/lab_results = every test of the V2 Lab backend in ONE shape (verdict, numbers, caveat). Shown by IndicatorLabScreen. Filters are done on the phone.
  Future<Map<String, dynamic>> fetchLabResults() => _brainGet('/api/v2/lab_results');

  /// R17a (Sniper banner): read-only route /api/v2/sniper_autopilot = EXPLORE / LEARNED, plain reasons, the unseen-days compare (R after fees). Advice only, paper only.
  Future<Map<String, dynamic>> fetchSniperAutopilot() => _brainGet('/api/v2/sniper_autopilot');

  /// R17b (Sniper learning cards): read-only routes. sniper_hist = training data health (per book apart); sniper_exitlearn = booking learner + the entry learner under 'entry'. (Lessons use fetchSniperLessons.)
  Future<Map<String, dynamic>> fetchSniperHist() => _brainGet('/api/v2/sniper_hist');

  Future<Map<String, dynamic>> fetchSniperExit() => _brainGet('/api/v2/sniper_exitlearn');

  /// R12 (Lab exit table): read-only route /api/v2/lab_exit = the 9 exit rules x market state table (R per trade after fees, train pick, unseen-days verdict; advice only). Shown by LabExitTableCard.
  Future<Map<String, dynamic>> fetchLabExit() => _brainGet('/api/v2/lab_exit');
}
