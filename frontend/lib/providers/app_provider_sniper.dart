part of 'app_provider.dart';

/// Round 24 (OwlSniper, read-only): the three GET routes of the Sniper, as plain fetches for the screens of Rounds 25 to 28.
/// Round 30 adds ONE write call, postSniperEnter (paper only). Same answer rules as the Brain fetches: the backend map, or {"state": "off"} (404 with the switch text), {"state": "old"} (any other non-200, e.g. an older backend)
/// or {"state": "error"} (the request failed). Never throws. Nothing here sends an order: the routes only read.
/// fetchSniper() itself stays in app_provider_brain.dart (Part S6) and now also carries compare, executor and barrier_rule.
extension AppProviderSniper on AppProvider {
  /// Live scan with retries: fresh order cards with their triple-barrier lines (profit, stop, time). The backend caches it for 25 seconds.
  Future<Map<String, dynamic>> fetchSniperLive() => _sniperGet('/api/v2/sniper_live');

  /// Health of the Sniper: model, scan, candles, switches, executor (NOT_AVAILABLE until it is built). overall = OK / WARN / BAD.
  Future<Map<String, dynamic>> fetchSniperHealth() => _sniperGet('/api/v2/sniper_health');

  /// Round 28 (Data Doctor): the newest candle gap records (GET /api/v2/gaps, the backend caps it at 200 rows) and the collector status (GET /api/v2/status: candle switch, store size).
  Future<Map<String, dynamic>> fetchV2Gaps() => _sniperGet('/api/v2/gaps?limit=200');
  Future<Map<String, dynamic>> fetchV2Status() => _sniperGet('/api/v2/status');

  /// Round 30 (PAPER only): PAPER ENTER for one coin. The backend runs every executor gate (armed, paper, TRENDING, 85% floor proven, stop range, cap 1, kill switch, same signal once)
  /// and answers {decision: OPEN / BLOCKED, gate, text}. Not armed = BLOCKED with the plain text "OFF (not armed)". Never throws. No real order exists.
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
