part of 'app_provider.dart';

/// Vision AI calls (backend /api/vision/*).
/// Moved out of app_provider.dart (NEXT-5a). Same code, same names: callers still write provider.xxx().
/// An extension in a part file sees every private member of AppProvider (same library).
extension AppProviderVision on AppProvider {
  // ---- Vision AI (backend: /api/vision/*, see ai_vision.py) ----
  /// Open AI trades, closed AI trades, the AI decision on every bot signal and the scoreboard. null on failure.
  Future<Map<String, dynamic>?> fetchVisionState() async {
    try {
      final res = await http.get(_u('/api/vision/state')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// The text the Vision AI is told about the indicators + the owner's own notes. null on failure.
  Future<Map<String, dynamic>?> fetchVisionGuide() async {
    try {
      final res = await http.get(_u('/api/vision/guide')).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// Saves the owner's notes that are added to the guide (POST /api/vision/notes).
  Future<bool> saveVisionNotes(String notes) async {
    try {
      final res = await http
          .post(_u('/api/vision/notes'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'notes': notes}))
          .timeout(const Duration(seconds: 10));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// The Vision AI's learning notebook: lessons, proposed / approved rules with evidence (GET /api/vision/lessons). null on failure.
  Future<Map<String, dynamic>?> fetchVisionLessons() async {
    try {
      final res = await http.get(_u('/api/vision/lessons')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// Approve / delete / un-approve one proposed rule (POST /api/vision/rule). action: 'approve' | 'delete' | 'propose'.
  Future<bool> actVisionRule(String id, String action) async {
    try {
      final res = await http
          .post(_u('/api/vision/rule'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'id': id, 'action': action}))
          .timeout(const Duration(seconds: 10));
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// URL of a chart picture. live=false: the picture the AI saw when it decided; live=true: a fresh one with stop / target lines.
  String visionImageUrl(String id, {bool live = false}) {
    final bucket = DateTime.now().millisecondsSinceEpoch ~/ (live ? 30000 : 600000);
    return '$baseUrl/api/vision/image/$id?live=${live ? 1 : 0}&t=$bucket';
  }

  /// Pump/dump memory + playbook (GET /api/vision/pumpdump).
  Future<Map<String, dynamic>?> fetchVisionPumpdump({int limit = 40}) async {
    try {
      final res = await http.get(_u('/api/vision/pumpdump?limit=$limit')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Seed pump/dump history from ~15 days of 15m candles for one symbol.
  Future<Map<String, dynamic>?> seedVisionPumpdump(String symbol) async {
    try {
      final res = await http
          .post(_u('/api/vision/pumpdump/seed'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'symbol': symbol}))
          .timeout(const Duration(seconds: 90));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Bot signals vs AI-own paper stats (GET /api/vision/compare).
  Future<Map<String, dynamic>?> fetchVisionCompare() async {
    try {
      final res = await http.get(_u('/api/vision/compare')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Switch the Vision own scanner on / off (paper only).
  Future<bool> setVisionOwnEnabled(bool enabled) async {
    try {
      final res = await http
          .post(_u('/api/vision/own'),
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({'enabled': enabled}))
          .timeout(const Duration(seconds: 10));
      return res.statusCode == 200;
    } catch (_) {}
    return false;
  }

  /// Where Vision trades peaked and what the exits did (GET /api/vision/exits).
  Future<Map<String, dynamic>?> fetchVisionExits() async {
    try {
      final res = await http.get(_u('/api/vision/exits')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  Future<Map<String, dynamic>?> fetchVisionDay(int offset) async {
    try {
      final res = await http.get(_u('/api/vision/day?offset=$offset')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// One trading day for the AI Own part: scanned coins with the reason, taken, margin used, profit (GET /api/vision/day_view).
  Future<Map<String, dynamic>?> fetchVisionDayView(int offset) async {
    try {
      final res = await http.get(_u('/api/vision/day_view?offset=$offset')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Paper capital status, candidates (stage + grade) and shadow results per source (GET /api/vision/lab). Read-only.
  Future<Map<String, dynamic>?> fetchVisionLab() async {
    try {
      final res = await http.get(_u('/api/vision/lab?limit=40')).timeout(const Duration(seconds: 15));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Bot vs Bot + AI vs AI Own after fees, and confirmed tag combinations (GET /api/vision/evidence). Read-only.
  Future<Map<String, dynamic>?> fetchVisionEvidence() async {
    try {
      final res = await http.get(_u('/api/vision/evidence')).timeout(const Duration(seconds: 15));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  /// Short "use it this way" digest of closed AI trades + pump/dump memory (GET /api/vision/notebook_digest).
  Future<Map<String, dynamic>?> fetchVisionNotebookDigest() async {
    try {
      final res = await http.get(_u('/api/vision/notebook_digest')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  Future<Map<String, dynamic>?> fetchVisionDays({int n = 14}) async {
    try {
      final res = await http.get(_u('/api/vision/days?n=$n')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }


}
