part of 'app_provider.dart';

/// Part 8A (README_FILTER): fetches and switches for the Filter Lab tab. The study is READ ONLY. The only call that can change trading is postFilterGate (the Part 7 gate mode, default off).
/// Same answer rules as the Sniper and Chop fetches: the backend map, or {"state": "off"} (404 with the switch text), {"state": "old"} (any other non-200)
/// or {"state": "error"} (the request failed). Never throws.
extension AppProviderFilter on AppProvider {
  /// GET /api/v2/filter = {gate {mode, status, made_utc, rules, combined, signals_checked, signals_hit, signals_skipped_no_numbers, last_error},
  /// run {running, current, done[{id, label, seconds}], failed[{id, label, why}], started_ts, finished_ts}, parts[{id, label, saved_ts}], auto, gate_log[{t, sym, side, mode, rules, blocked}]}
  Future<Map<String, dynamic>> fetchFilter() => _sniperGet('/api/v2/filter');

  /// GET /api/v2/filter_part?id=f1|f1b|f2|f3a|f3b|f4|f5a|f5b|f6 = {id, saved_ts, data} (the saved summary of that Part) or {id, state: "none"} when it was not made yet.
  Future<Map<String, dynamic>> fetchFilterPart(String id) => _sniperGet('/api/v2/filter_part?id=$id');

  /// GET /api/v2/filter_rules = {status, made_utc, rules[{id, name, kind, luck_random_as_good_pct, train, test}], combined {train, test}} or {state: "none"}.
  Future<Map<String, dynamic>> fetchFilterRules() => _sniperGet('/api/v2/filter_rules');

  /// POST /api/v2/filter_run: starts ONE study run in the background (409 if one is going on). Answers {started, note, run}. Never throws.
  Future<Map<String, dynamic>> postFilterRun() => _filterPost('/api/v2/filter_run', null);

  /// POST /api/v2/filter_gate {"mode": "off" | "log" | "block"}: sets the gate mode (Part 7). Answers {mode, note} or {error}. Never throws.
  Future<Map<String, dynamic>> postFilterGate(String mode) => _filterPost('/api/v2/filter_gate', {'mode': mode});

  Future<Map<String, dynamic>> _filterPost(String path, Map<String, dynamic>? body) async {
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
