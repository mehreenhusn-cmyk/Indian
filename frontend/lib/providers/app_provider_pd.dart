part of 'app_provider.dart';

/// Pump / Dump scanner (26 Nov 2026): the app's calls to the scanner on this phone. Same rules as the Brain fetches: a GET, never throws,
/// answers a map or {"state": off / old / error}. The scanner lives in backend/pd_*.py + api/pd_route.py; the alert sound + tab dot are pdPoll() in app_provider.dart.
extension AppProviderPd on AppProvider {
  Future<void> pdPoll() async {
    if (_pdBusy) return;
    _pdBusy = true;
    try {
      final r = await _brainGet('/api/pd/live');
      final list = r['latest_starts'];
      if (list is! List || list.isEmpty) {
        _pdBaselined = true;
        return;
      }
      final newest = '${(list.first as Map)['id']}';
      if (!_pdBaselined) {
        _pdBaselined = true;
        _pdSeenId = newest;
        return;
      }
      if (newest == _pdSeenId) return;
      var n = 0;
      for (final e in list) {
        if ('${(e as Map)['id']}' == _pdSeenId) break;
        n++;
      }
      _pdSeenId = newest;
      if (n <= 0) return;
      if (!pdOnTab) pdNewCount += n;
      if (soundEnabled) sound.play(TradeSound.orderFilled);
      notifyListeners();
    } catch (_) {
      // the scanner is optional: a failed call must never disturb the app
    } finally {
      _pdBusy = false;
    }
  }

  void pdSetOnTab(bool on) {
    pdOnTab = on;
    if (on && pdNewCount != 0) {
      pdNewCount = 0;
      notifyListeners();
    }
  }

  Future<Map<String, dynamic>> fetchPdLive() => _brainGet('/api/pd/live');

  /// [day] = YYYY-MM-DD (IST) or '' for today.
  Future<Map<String, dynamic>> fetchPdDay(String day) => _brainGet('/api/pd/day${day.isEmpty ? '' : '?day=${Uri.encodeQueryComponent(day)}'}');

  Future<Map<String, dynamic>> fetchPdLearning() => _brainGet('/api/pd/learning');

  /// Round 1 (28 Nov 2026): Naye movers + Pehle se chal rahe hain (backend/pd_rank.py). Never throws; {"state": old / error} on an old backend.
  Future<Map<String, dynamic>> fetchPdMovers() => _brainGet('/api/pd/movers');

  /// Round 2 (28 Nov 2026): Taiyari me = pre-pump / pre-dump (backend/pd_pre.py). Never throws; {"state": old / error} on an old backend.
  Future<Map<String, dynamic>> fetchPdPre() => _brainGet('/api/pd/pre');

  /// Part 4 (28 Nov 2026): Cooling watch = coins that pumped in the last 10 days (backend/pd_cool.py). Never throws; {"state": old / error} on an old backend.
  Future<Map<String, dynamic>> fetchPdCool() => _brainGet('/api/pd/cool');

  /// The two switches: the scanner on / off (off = no data is used) and the self-tuning on / off. true = the phone accepted it.
  Future<bool> setPdSwitch({bool? enabled, bool? autoTune}) async {
    try {
      final body = <String, dynamic>{};
      if (enabled != null) body['enabled'] = enabled;
      if (autoTune != null) body['auto_tune'] = autoTune;
      final res = await http.post(_u('/api/pd/toggle'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body)).timeout(const Duration(seconds: 8));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }
}
