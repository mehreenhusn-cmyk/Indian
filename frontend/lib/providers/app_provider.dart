import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import '../services/sound_service.dart';

/// The real state-management class the whole app depends on
/// (main.dart does `ChangeNotifierProvider(create: (_) => AppProvider(prefs)..init())`
/// and every screen does `Consumer<AppProvider>` / `provider.movers` etc).
///
/// This file used to contain a duplicate copy of dashboard_screen.dart by
/// mistake (no `class AppProvider` existed anywhere in the repo) — that's
/// why nothing ever connected. This is the actual class.
///
/// Talks to backend/api_server.py:
///   GET  /api/status    -> full status dict (today_pnl_usdt, open_positions,
///                          market_movers, alerts, etc — same shape pushed
///                          over the WebSocket)
///   GET  /api/signals    -> {"signals": [...]}
///   GET  /api/settings   -> flat settings dict
///   POST /api/settings   -> body = new settings dict, returns updated dict
///   POST /api/close/{id} -> close one position
///   POST /api/close_all  -> close all open positions
///   WS   /ws              -> pushes {"type":"init"/"update","data": <status dict>}
///
/// NETWORK NOTE (Sep 2026): the deployed Render backend is on the FREE tier,
/// which spins the whole instance down after ~15 min of inactivity and takes
/// up to ~50s to wake back up on the next request (confirmed in Render's own
/// dashboard banner + logs — the app itself and the backend code were both
/// fine, the fixed 5s timeout below was just too short to survive a cold
/// start). _getResilient() below does a fast 5s attempt first (so a genuine
/// dead/unreachable backend still fails fast), and only if THAT times out
/// does it assume a cold start and retry once with a much longer timeout,
/// setting isWakingUp so the UI can show "Waking up backend..." instead of
/// a raw error during that wait.
class AppProvider extends ChangeNotifier {
  final SharedPreferences prefs;
  AppProvider(this.prefs) {
    _restoreAiDiskCache(); // last AI numbers are on screen the moment the app opens
  }

  static const _backendUrlKey = 'backend_url';
  // NETWORK FIX (Sep 2026): 'localhost' does NOT resolve inside the Android
  // app sandbox the way it does in a desktop browser or in Termux's own
  // shell - Android's network stack has no loopback hostname mapping for
  // apps by default, so every request threw
  // `ClientException: Failed host lookup: 'localhost'`
  // (SocketException, errno=7, "No address associated with hostname") even
  // though the FastAPI backend was correctly bound and reachable at
  // 127.0.0.1:8000 in Termux. 127.0.0.1 is the numeric loopback address -
  // it never needs DNS/hostname resolution at all, so it works identically
  // on-device (Termux backend + this Flutter app, same phone) without
  // relying on any hosts-file/DNS entry existing for 'localhost'. Candle
  // fetch (and every other /api/* call) now targets this by default.
  static const _defaultBaseUrl = 'http://127.0.0.1:8000';

  static const _quickTimeout = Duration(seconds: 5);
  static const _wakeTimeout = Duration(seconds: 45);

  String baseUrl = _defaultBaseUrl;

  Map<String, dynamic> status = {};

  // Bot 2 was removed - there is only one bot. These stay so the rest of the app keeps working.
  String activeBot = 'b1';
  Map<String, dynamic> _lastRawStatus = {};
  List<dynamic> _rawAlerts = [];
  String get botQuery => 'bot=b1';

  /// Daily schedule info from the backend: {enabled, state: awake|night|sleep|off, text, ist}.
  Map<String, dynamic>? get dayGate {
    final g = status['day_gate'];
    return g is Map ? Map<String, dynamic>.from(g) : null;
  }

  List<dynamic> _alertsForBot(List<dynamic> raw) => raw;

  List<dynamic> movers = [];
  List<dynamic> positions = [];
  List<dynamic> signals = [];

  // Change counters for the slow-moving lists. Screens that only show alerts /
  // movers / signals watch THESE (via Selector) instead of the whole provider,
  // so the 250ms price tick no longer rebuilds them when their data did not
  // actually change. Bumped only when the content really changed.
  int alertsRev = 0;
  int moversRev = 0;
  int signalsRev = 0;
  int _moversSig = 0;
  List<dynamic> alerts = [];
  List<Map<String, dynamic>> equityCurve = [];
  Map<String, dynamic> settings = {};

  /// Dashboard AI Insights card data (GET /api/ai/insights, see ai_stats.py).
  /// null until the first successful fetch.
  Map<String, dynamic>? aiInsights;
  String? _aiInsightsRaw;

  /// Background refresh for the AI Insights card. Uses a plain quick-timeout
  /// GET (not _getResilient) so this periodic poll can never trigger the
  /// "backend waking up" banner, and only notifies listeners when the data
  /// actually changed.
  Future<void> fetchAiInsights() async {
    try {
      final res = await http.get(_u('/api/ai/insights')).timeout(_quickTimeout);
      if (res.statusCode == 200 && res.body != _aiInsightsRaw) {
        _aiInsightsRaw = res.body;
        aiInsights = jsonDecode(res.body) as Map<String, dynamic>;
        notifyListeners();
      }
    } catch (_) {
      // Non-critical card - keep showing the last data on any failure.
    }
  }
  String? error;

  /// True while a request has timed out once and we're giving the backend
  /// a longer window to wake up (Render free-tier cold start). Screens can
  /// show a "Waking up backend..." state instead of the raw error while
  /// this is true.
  bool isWakingUp = false;

  /// Mirrors WebSocketService.isConnected (see main.dart's onConnectionChange
  /// wiring) so any screen can show a live connection indicator via
  /// Consumer<AppProvider> without holding its own reference to the socket.
  bool wsConnected = false;

  /// Cross-screen "please switch to this bottom-nav tab" signal. MainScreen
  /// (main.dart) owns the actual _currentIndex, which isn't reachable from
  /// a Dashboard sub-widget any other way (DashboardScreen is const, no
  /// callback threaded through). Dashboard just calls goToTab(1); MainScreen
  /// listens via Consumer/Selector and consumes the request via
  /// consumeTabRequest() so the same request never re-fires on an unrelated
  /// rebuild.
  int navigateToTabRequest = -1;

  void goToTab(int index) {
    navigateToTabRequest = index;
    notifyListeners();
  }

  int? consumeTabRequest() {
    if (navigateToTabRequest < 0) return null;
    final i = navigateToTabRequest;
    navigateToTabRequest = -1;
    return i;
  }

  /// Theme Mode (Light/Dark) - stored locally in SharedPreferences so it is
  /// instant, works offline, and defaults to LIGHT unless dark was chosen (a fresh install used to start black).
  /// Deliberately NOT read from the backend `theme` setting: that key is a
  /// legacy Kivy default of "light" and would flip every existing user to
  /// light mode on first launch.
  ThemeMode get themeMode =>
      prefs.getString('theme_mode') == 'dark' ? ThemeMode.dark : ThemeMode.light;

  Future<bool> setThemeMode(ThemeMode mode) async {
    final ok = await prefs.setString('theme_mode', mode == ThemeMode.light ? 'light' : 'dark');
    notifyListeners();
    pushPrefsBackup();
    return ok;
  }

  /// When the last WebSocket status payload was applied. main.dart's REST
  /// safety poll only fires when this is old (see wsStale) - while the socket
  /// is pushing ~4 updates/sec, a second REST copy of the same status is just
  /// wasted backend work.
  DateTime? _lastWsDataAt;

  /// True when the WebSocket is disconnected or has gone quiet (>6s). Backend
  /// pushes every 250ms (1s in live-trading mode), so 6s of silence is a real
  /// problem, not jitter.
  bool get wsStale {
    final t = _lastWsDataAt;
    return !wsConnected ||
        t == null ||
        DateTime.now().difference(t) > const Duration(seconds: 6);
  }

  /// System Load card (GET /api/system). Returns the decoded map instead of
  /// storing it + notifyListeners(): the card keeps its own state, so its 3s
  /// refresh never rebuilds any other screen. null on any failure.
  Future<Map<String, dynamic>?> fetchSystem() async {
    try {
      final res = await http.get(_u('/api/system')).timeout(_quickTimeout);
      if (res.statusCode == 200) {
        final body = jsonDecode(res.body);
        if (body is Map<String, dynamic>) return body;
      }
    } catch (_) {}
    return null;
  }

  /// True only after the socket has been down for [_bannerDelay]. A 1-3 s reconnect is invisible to the user
  /// (the red "connection lost" banner used to flash on every blip); the small WS dot still shows the truth.
  bool wsLongDown = false;
  Timer? _downTimer;
  static const _bannerDelay = Duration(seconds: 6);

  void setWsConnected(bool connected) {
    if (wsConnected == connected) return;
    wsConnected = connected;
    if (!connected) wsLatencyMs = null;
    _downTimer?.cancel();
    if (connected) {
      wsLongDown = false;
    } else {
      _downTimer = Timer(_bannerDelay, () {
        if (!wsConnected) {
          wsLongDown = true;
          notifyListeners();
        }
      });
    }
    notifyListeners();
  }

  /// Round-trip ping/pong latency in ms (see websocket_service.dart's
  /// sendPing()/onLatency wiring in main.dart) - null until the first pong
  /// arrives, or whenever the socket drops (see setWsConnected above).
  int? wsLatencyMs;

  void setWsLatency(int ms) {
    wsLatencyMs = ms;
    notifyListeners();
  }

  Uri _u(String path) => Uri.parse('$baseUrl$path');

  /// GET with a fast-fail + cold-start-tolerant retry. Only retries on an
  /// actual timeout (TimeoutException) — a genuine connection error (DNS
  /// failure, refused connection, etc.) fails immediately since waiting
  /// longer won't help those.
  Future<http.Response> _getResilient(Uri uri) => _withWakeHint(() => http.get(uri));

  /// POST: ONE request only. The old code sent the same POST a second time after a timeout - for
  /// /api/close_all that could close or modify things twice.
  Future<http.Response> _postResilient(Uri uri,
          {Map<String, String>? headers, Object? body}) =>
      _withWakeHint(() => http.post(uri, headers: headers, body: body));

  /// Sends the request once and waits for the slow answer instead of firing a duplicate. After
  /// [_quickTimeout] the UI only gets the "waking up" hint; the call itself gives up after [_wakeTimeout].
  Future<http.Response> _withWakeHint(Future<http.Response> Function() send) async {
    final hint = Timer(_quickTimeout, () {
      isWakingUp = true;
      notifyListeners();
    });
    try {
      return await send().timeout(_wakeTimeout);
    } finally {
      hint.cancel();
      if (isWakingUp) {
        isWakingUp = false;
        notifyListeners();
      }
    }
  }

  /// Ops panel (GET /api/ops): which zip is live, uptime, restarts, last problems. Returns the map (no notifyListeners). null on failure.
  Future<Map<String, dynamic>?> fetchOps() async {
    try {
      final res = await http.get(_u('/api/ops')).timeout(_quickTimeout);
      if (res.statusCode == 200) {
        final body = jsonDecode(res.body);
        if (body is Map<String, dynamic>) return body;
      }
    } catch (_) {}
    return null;
  }

  // ---- AI keys: paste any key, the backend finds whose key it is and picks the model (GET/POST /api/ai/vkeys/*)
  Future<Map<String, dynamic>?> fetchAiVKeys() async {
    try {
      final res = await http.get(_u('/api/ai/vkeys')).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// sub: add | test | detect | clear. add/test/detect talk to the AI company, so they wait longer.
  Future<Map<String, dynamic>?> postAiVKey(String sub, Map<String, dynamic> body) async {
    try {
      final res = await http
          .post(_u('/api/ai/vkeys/$sub'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body))
          .timeout(Duration(seconds: sub == 'clear' ? 15 : 60));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return {'ok': false, 'state': 'error', 'message': 'The backend answered ${res.statusCode}. Update the backend zip first.'};
    } catch (_) {}
    return {'ok': false, 'state': 'error', 'message': 'The backend did not answer.'};
  }

  /// Load report (GET /api/load_report?hours=): meters + the main bottleneck for the last 1 / 4 / 24 h.
  Future<Map<String, dynamic>?> fetchLoadReport(double hours) async {
    try {
      final res = await http.get(_u('/api/load_report?hours=$hours')).timeout(const Duration(seconds: 15));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  Future<List<dynamic>> fetchLoadDaily() async {
    try {
      final res = await http.get(_u('/api/load_report/daily')).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final b = jsonDecode(res.body);
        if (b is Map && b['days'] is List) return b['days'] as List;
      }
    } catch (_) {}
    return const [];
  }

  // ---- App-choice backup: theme + sound choices are copied to the phone's backend (owl_data), so a freshly installed app gets them back.
  static const _prefsRestoredKey = 'prefs_restored_v1';
  static const _syncKeys = ['theme_mode', 'voice_enabled', 'voice_entry', 'voice_exit', 'voice_fg_only'];
  Timer? _pushTimer;

  void pushPrefsBackup() {
    _pushTimer?.cancel();
    _pushTimer = Timer(const Duration(seconds: 2), () async {
      try {
        final m = <String, dynamic>{};
        for (final k in _syncKeys) {
          final v = prefs.get(k);
          if (v is String || v is bool || v is int) m[k] = v;
        }
        if (m.isEmpty) return;
        await http
            .post(_u('/api/app_prefs'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(m))
            .timeout(const Duration(seconds: 8));
      } catch (_) {}
    });
  }

  /// Fresh install only: copies the saved choices back, never overwrites a choice already made on this phone.
  Future<void> _restorePrefsIfFresh() async {
    try {
      if (prefs.getBool(_prefsRestoredKey) == true) return;
      final res = await http.get(_u('/api/app_prefs')).timeout(_quickTimeout);
      if (res.statusCode != 200) return;
      final body = jsonDecode(res.body);
      if (body is Map) {
        for (final k in _syncKeys) {
          if (prefs.containsKey(k)) continue;
          final v = body[k];
          if (v is String) {
            await prefs.setString(k, v);
          } else if (v is bool) {
            await prefs.setBool(k, v);
          } else if (v is int) {
            await prefs.setInt(k, v);
          }
        }
      }
      await prefs.setBool(_prefsRestoredKey, true);
      notifyListeners();
    } catch (_) {}
  }

  Future<void> init() async {
    baseUrl = prefs.getString(_backendUrlKey) ?? _defaultBaseUrl;
    await Future.wait([
      fetchStatus(),
      fetchSignals(),
      fetchSettings(),
      fetchEquity(),
      fetchCalendar(),
    ]);
    initLoaded = true; // the welcome loading bar reads this: status, signals, settings, equity and calendar are all fetched
    notifyListeners();
    _restorePrefsIfFresh().then((_) => pushPrefsBackup()); // not awaited
    warmAi(); // not awaited: runs quietly behind the first screen
  }

  /// True once init() has finished its first fetches (welcome loading bar uses it as a REAL milestone).
  bool initLoaded = false;

  /// Called once from MainScreen right after init() so the WebSocket
  /// connects to the same backend URL settings uses (not a hardcoded one).
  String get wsUrl => baseUrl.replaceFirst('http', 'ws') + '/ws';

  /// Currently selected Dashboard equity-curve timeframe - one of
  /// 15m/1h/2h/1d/3d/7d. Kept here (not just passed as an argument) so the
  /// chip row on the Dashboard can read back which one is active after a
  /// rebuild/hot-reload.
  String equityTf = '7d';

  // Equity fetch cache: the curve is re-fetched on app start, on every closed
  // trade (forced) and on timeframe change. Per-timeframe bodies are kept for
  // 20s so flipping chips back and forth is instant and does not hit the
  // backend again, and an unchanged body never replaces equityCurve (so the
  // dashboard does not rebuild/redraw the chart for identical data).
  final Map<String, String> _equityBodyByTf = {};
  final Map<String, DateTime> _equityAtByTf = {};
  String? _equityShownBody;

  bool _applyEquityBody(String body) {
    if (body == _equityShownBody) return false;
    final data = jsonDecode(body) as Map<String, dynamic>;
    final curve = (data['curve'] as List<dynamic>?) ?? [];
    equityCurve = curve.map((e) => e as Map<String, dynamic>).toList();
    _equityShownBody = body;
    return true;
  }

  Future<void> fetchEquity({String? tf, bool force = false}) async {
    if (tf != null) equityTf = tf;
    final key = equityTf;
    final cachedAt = _equityAtByTf[key];
    final cachedBody = _equityBodyByTf[key];
    if (!force && cachedAt != null && cachedBody != null && DateTime.now().difference(cachedAt).inSeconds < 20) {
      try {
        _applyEquityBody(cachedBody);
      } catch (_) {}
      notifyListeners(); // equityTf may have changed (chip highlight)
      return;
    }
    try {
      final res = await _getResilient(_u('/api/equity?tf=$key&$botQuery'));
      if (res.statusCode == 200) {
        _equityBodyByTf[key] = res.body;
        _equityAtByTf[key] = DateTime.now();
        // Only show it if the user is still on the timeframe it was fetched for.
        if (key == equityTf) _applyEquityBody(res.body);
      }
    } catch (_) {
      // status fetch already surfaces the connection error; don't overwrite it here
    }
    notifyListeners();
  }

  /// Daily P&L calendar under the equity curve (GET /api/calendar). calendarMonth is "YYYY-MM"
  /// or null = the backend's current trading month. Closed trades only, same days as the Today ring.
  Map<String, dynamic>? calendarData;
  String? calendarMonth;
  String? _calendarShownBody;

  Future<void> fetchCalendar({String? month}) async {
    if (month != null) calendarMonth = month;
    try {
      final q = calendarMonth == null ? '?$botQuery' : '?month=$calendarMonth&$botQuery';
      final res = await _getResilient(_u('/api/calendar$q'));
      if (res.statusCode == 200 && res.body != _calendarShownBody) {
        _calendarShownBody = res.body;
        calendarData = jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {
      // status fetch already surfaces the connection error; keep the last calendar on screen
    }
    notifyListeners();
  }

  /// Fire-and-forget hit on /health - used purely as a keep-alive while the
  /// app is in the foreground, so a free-tier backend (Render etc, see the
  /// cold-start note at the top of this file) sees regular traffic and is
  /// less likely to spin down between real requests. Never touches
  /// error/isWakingUp/notifyListeners - a failed ping just means the next
  /// real request will hit the normal cold-start retry path, nothing else
  /// to report here.
  Future<void> ping() async {
    try {
      await http.get(_u('/health')).timeout(_quickTimeout);
    } catch (_) {}
  }

  /// One request per endpoint at a time: when the backend is busy, every timer/screen used to add ANOTHER
  /// identical request (the log showed 10 x /api/status in one burst), which made the stall longer.
  final Map<String, Future<void>> _once = {};
  Future<void> _single(String key, Future<void> Function() job) =>
      _once[key] ??= job().whenComplete(() => _once.remove(key));

  Future<void> fetchStatus() => _single('status', _fetchStatus);

  Future<void> _fetchStatus() async {
    try {
      final res = await _getResilient(_u('/api/status'));
      if (res.statusCode == 200) {
        _applyStatus(jsonDecode(res.body) as Map<String, dynamic>);
        error = null;
      } else {
        error = 'Backend returned ${res.statusCode}';
      }
    } on TimeoutException {
      error = 'Backend busy - waiting for it (data will refresh by itself)';
    } catch (e) {
      error = 'Cannot reach backend: $e';
    }
    notifyListeners();
  }

  Future<void> fetchSignals() => _single('signals', _fetchSignals);

  Future<void> _fetchSignals() async {
    try {
      final res = await _getResilient(_u('/api/signals?$botQuery'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        signals = (data['signals'] as List<dynamic>?) ?? [];
        signalsRev++;
      }
    } catch (_) {
      // status fetch already surfaces the connection error; don't overwrite it here
    }
    notifyListeners();
  }

  Future<void> fetchSettings() async {
    try {
      final res = await _getResilient(_u('/api/settings'));
      if (res.statusCode == 200) {
        settings = jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    notifyListeners();
  }

  /// PHASE 2 - instant live-state sync: fires `POST /api/settings` with just
  /// `{"live_trading_enabled": value}` the moment the Settings screen's Live
  /// Trading switch is flipped - does NOT wait for the screen's normal
  /// "Save Settings" button, so the backend's dispatcher (app.py) starts
  /// routing signals to the newly-selected engine (live vs paper) on the
  /// very next signal, not just after a manual save. Returns true if the
  /// backend confirmed the change.
  Future<bool> setLiveTradingEnabledImmediate(bool value) async {
    final server = await updateSettings({'live_trading_enabled': value});
    return server != null && server['live_trading_enabled'] == value;
  }

  /// Saves (merges) the given settings on the backend. Returns the settings
  /// map the SERVER now holds on success, or null on failure - callers can
  /// compare it against what they sent to show a "server confirmed" receipt.
  /// Asks the backend to zip the trade / alert / AI history and send it to the
  /// Telegram chat. Returns (ok, message) - never throws.
  Future<({bool ok, String message})> exportBackup() async {
    try {
      final res = await http
          .post(_u('/api/backup/export'), headers: {'Content-Type': 'application/json'})
          .timeout(const Duration(seconds: 90));
      if (res.statusCode == 200) {
        final m = jsonDecode(res.body) as Map<String, dynamic>;
        final ok = m['ok'] == true;
        return (
          ok: ok,
          message: ok ? 'Backup Telegram pe bhej diya (${m['size_kb']} KB)' : '${m['message'] ?? 'Backup fail'}',
        );
      }
      return (ok: false, message: 'Backup fail (${res.statusCode})');
    } catch (e) {
      return (ok: false, message: 'Backend se connect nahi hua: $e');
    }
  }

  Future<Map<String, dynamic>?> updateSettings(Map<String, dynamic> newSettings) async {
    try {
      final res = await _postResilient(
        _u('/api/settings'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(newSettings),
      );
      if (res.statusCode == 200) {
        settings = jsonDecode(res.body) as Map<String, dynamic>;
        error = null;
        notifyListeners();
        return settings;
      }
      error = 'Failed to save settings (${res.statusCode})';
    } catch (e) {
      error = 'Cannot reach backend: $e';
    }
    notifyListeners();
    return null;
  }

  /// Fetches OHLC candles for one symbol (used by the candle chart sheet
  /// opened from Market Watch / Positions). Returns an empty list on any
  /// failure instead of throwing - the chart widget shows its own
  /// "couldn't load candles" state for that.
  /// Set by fetchCandles() whenever it returns an empty list, to the
  /// backend's actual reason (e.g. "2U2USDTM candles unavailable (...) -
  /// symbol may be thinly traded, delisted, or not a valid Binance Futures
  /// contract") instead of leaving the chart screen to guess with a
  /// generic "Could not load candles". Read by candle_chart.dart right
  /// after awaiting fetchCandles(); not notifyListeners()-backed since
  /// it's consumed synchronously by a single caller, not globally reactive.
  String? lastCandleError;

  Future<List<dynamic>> fetchCandles(String symbol, {int limit = 600, String? tf}) async {
    try {
      // CONFIGURABLE STRATEGY TIMEFRAME: defaults to whatever the backend
      // has saved (settings['timeframe'], e.g. "5m"/"1h") so the chart
      // always matches the timeframe the strategy is actually scanning on,
      // instead of silently always requesting 5m. Callers can still pass an
      // explicit tf to override (not currently used, but keeps the option).
      final resolvedTf = tf ?? (settings['timeframe'] as String?) ?? '5m';
      final res = await _getResilient(_u('/api/candles/$symbol?limit=$limit&tf=$resolvedTf'));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final candles = (data['candles'] as List<dynamic>?) ?? [];
        lastCandleError = candles.isEmpty ? data['error']?.toString() : null;
        return candles;
      }
      lastCandleError = 'Backend returned ${res.statusCode}';
    } catch (e) {
      lastCandleError = 'Cannot reach backend: $e';
    }
    return [];
  }

  /// Tests the saved Binance API credentials without placing any order -
  /// called from the Settings screen's "Test Binance Connection" button.
  Future<Map<String, dynamic>> testBinanceConnection() async {
    try {
      final res = await _postResilient(_u('/api/binance/test-connection'));
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
      return {'ok': false, 'error': 'Backend returned ${res.statusCode}'};
    } catch (e) {
      return {'ok': false, 'error': 'Cannot reach backend: $e'};
    }
  }

  /// OWL Terminal is hard-locked to Binance Futures - there is no exchange
  /// switcher anymore (KuCoin support and the /api/exchange/switch round
  /// trip were removed in the Batch 3 purge). This getter is kept only so
  /// existing call sites (Settings' summary line, the drawer's status chip)
  /// don't need to hardcode the string in more than one place.
  String get activeExchange => 'binance';

  /// AI tab -> Trade Book. All-time summary (first page only) + one filtered
  /// page of closed trades from GET /api/ai/book. Returns null on failure so
  /// the screen can show a retry instead of a blank list.
  Uri _bookUri({int offset = 0, int limit = 40, String side = '', String result = '', String q = '', String grp = '', String gval = '', int hour = -1}) =>
      _u('/api/ai/book').replace(queryParameters: {
        'offset': '$offset',
        'limit': '$limit',
        if (side.isNotEmpty) 'side': side,
        if (result.isNotEmpty) 'result': result,
        if (q.isNotEmpty) 'q': q,
        if (grp.isNotEmpty && gval.isNotEmpty) ...{'grp': grp, 'gval': gval},
        if (hour >= 0) 'hour': '$hour',
      });

  /// Last Overview summary (book endpoint, 1-row page) - painted at once, refreshed behind it.
  Map<String, dynamic>? peekAiBook() => _aiCache[_bookUri(limit: 1).toString()];

  Future<Map<String, dynamic>?> fetchAiBook({
    int offset = 0,
    int limit = 40,
    String side = '',
    String result = '',
    String q = '',
    String grp = '',
    String gval = '',
    int hour = -1,
  }) async {
    try {
      final uri = _bookUri(offset: offset, limit: limit, side: side, result: result, q: q, grp: grp, gval: gval, hour: hour);
      return await _aiGet(uri, timeout: const Duration(seconds: 12)); // fails fast: the screen shows Retry instead of spinning
    } catch (_) {}
    return null;
  }

  /// Bot vs AI -> tap a row: ROI path + Z-score / TSI / SD of ONE signal (GET /api/ai/pair_replay). null on failure.
  Future<Map<String, dynamic>?> fetchAiPairReplay(dynamic id, dynamic opened) async {
    try {
      final uri = _u('/api/ai/pair_replay').replace(queryParameters: {'id': '$id', 'opened': '${opened ?? 0}'});
      return await _aiGet(uri, timeout: const Duration(seconds: 25), tries: 1);
    } catch (_) {}
    return null;
  }

  bool _aiWarmed = false;

  /// Right after start-up, one at a time and quietly, load the three AI screens the user opens most, so the first tap
  /// on Insights / Book / Bot vs AI already finds numbers (the backend answers from its own warm cache).
  Future<void> warmAi() async {
    if (_aiWarmed) return;
    _aiWarmed = true;
    await Future.delayed(const Duration(seconds: 6));
    for (final f in <Future<Map<String, dynamic>?> Function()>[
      () => fetchAiBook(offset: 0, limit: 1), // the Overview summary (the Trade Book list is gone)
      () => fetchAiCoach(),
      () => fetchAiAbBoard(),
    ]) {
      try {
        await f();
      } catch (_) {}
      await Future.delayed(const Duration(seconds: 2));
    }
  }

  /// Trade Book replay: saved price path of one closed trade (GET /api/ai/path).
  /// Returns null on failure; {'ok': false} when that trade has no saved path
  /// (trades closed before path recording started).
  Future<Map<String, dynamic>?> fetchAiPath(dynamic id, dynamic opened) async {
    try {
      final uri = _u('/api/ai/path').replace(queryParameters: {
        'id': '$id',
        'opened': '${opened ?? 0}',
      });
      final res = await _getResilient(uri);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// OWNER-ONLY screen card: has the ML model's quiet guess at trade-open matched the
  /// real result? (GET /api/ai/shadow). Never passed to the chat AI. null on failure.
  Future<Map<String, dynamic>?> fetchAiShadow() async {
    try {
      final res = await http.get(_u('/api/ai/shadow')).timeout(_quickTimeout);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// "What has the AI learned about the EMA50 strategy": timeline, works / fails / uncertain with
  /// evidence status, TP funnel, timeframes (GET /api/ai/learning, see ai_learning.py).
  /// Read-only research numbers. null on failure.
  Future<Map<String, dynamic>?> fetchAiLearning({bool refresh = false}) async {
    try {
      final uri = _u('/api/ai/learning').replace(queryParameters: refresh ? {'refresh': 'true'} : null);
      final res = await http.get(uri).timeout(_quickTimeout);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// A/B scoreboard: bot as it is vs bot + TSI filter (GET /api/ai/ab_board, see ai_ab_board.py).
  /// Read-only research numbers. null on failure.
  Future<Map<String, dynamic>?> fetchAiAbBoard({String tf = ''}) =>
      _aiGet(_u('/api/ai/ab_board').replace(queryParameters: tf.isEmpty ? null : {'tf': tf}));

  /// AI research screens read big lab files on the backend: the first call can take 20-40 s on a phone,
  /// so they get a long timeout + one retry (the normal 5 s timeout made A/B say "backend check karo").
  /// The reason of the last failure is kept in [aiLastError] so the screen can show the real cause.
  static const _aiTimeout = Duration(seconds: 40);
  String? aiLastError;

  /// Last good answer of every AI endpoint, so a screen can paint the OLD numbers at once when it opens
  /// (no "Load ho raha hai..." on every tab switch) and refresh them quietly behind it.
  final Map<String, Map<String, dynamic>> _aiCache = {};
  final Map<String, Future<Map<String, dynamic>?>> _aiInflight = {};

  // ---- disk copy of the AI answers (so the AI tab shows the last numbers at once, even right after the app starts) ----
  static const _aiDiskKey = 'ai_disk_cache_v1';
  static const _aiDiskMaxBytes = 80000; // an answer bigger than this is not stored on disk (it stays in memory only)
  static const _aiDiskMaxEntries = 14;
  final Map<String, Map<String, dynamic>> _aiDisk = {}; // url -> {'t': saved at (ms), 'v': answer}
  Timer? _aiDiskTimer;

  void _restoreAiDiskCache() {
    try {
      final raw = prefs.getString(_aiDiskKey);
      if (raw == null || raw.isEmpty) return;
      final m = Map<String, dynamic>.from(jsonDecode(raw) as Map);
      final rows = m.entries.where((e) => e.value is Map).toList()
        ..sort((a, b) => ((a.value['t'] ?? 0) as num).compareTo((b.value['t'] ?? 0) as num)); // oldest first: the newest wins 'latest:'
      for (final e in rows) {
        final v = e.value['v'];
        if (v is! Map) continue;
        final ans = Map<String, dynamic>.from(v);
        _aiDisk[e.key] = {'t': e.value['t'] ?? 0, 'v': ans};
        _aiCache[e.key] = ans;
        final path = Uri.tryParse(e.key)?.path ?? '';
        if (path.isNotEmpty) _aiCache['latest:$path'] = ans;
      }
    } catch (_) {
      // a damaged copy is simply ignored: the app then asks the backend as usual
    }
  }

  void _saveAiDisk(String url, Map<String, dynamic> answer, int bytes) {
    if (bytes > _aiDiskMaxBytes || answer['building'] == true || answer['error'] != null) return;
    _aiDisk[url] = {'t': DateTime.now().millisecondsSinceEpoch, 'v': answer};
    if (_aiDisk.length > _aiDiskMaxEntries) {
      final oldest = _aiDisk.entries.reduce((a, b) => (a.value['t'] as int) <= (b.value['t'] as int) ? a : b).key;
      _aiDisk.remove(oldest);
    }
    _aiDiskTimer ??= Timer(const Duration(seconds: 6), () {
      _aiDiskTimer = null;
      try {
        prefs.setString(_aiDiskKey, jsonEncode(_aiDisk)); // one write for all answers that arrived in the last 6 seconds
      } catch (_) {}
    });
  }

  /// tf '' = the newest answer of that endpoint whatever timeframe it was asked for.
  Map<String, dynamic>? peekAi(String path, [String tf = '']) => tf.isEmpty
      ? _aiCache['latest:$path']
      : _aiCache[_u(path).replace(queryParameters: {'tf': tf}).toString()];

  /// Two screens asking for the same URL at the same time share ONE request (the log showed /api/ai/desk 4-5x in a row).
  Future<Map<String, dynamic>?> _aiGet(Uri uri, {Duration? timeout, int tries = 2}) {
    final k = uri.toString();
    return _aiInflight[k] ??= _aiGetRaw(uri, timeout ?? _aiTimeout, tries).whenComplete(() => _aiInflight.remove(k));
  }

  /// [tries] = 1 for screens that already show the old numbers: one short attempt, then the screen keeps the old
  /// answer and offers a Retry / "Refresh now" button (two long attempts used to freeze the spinner for 25+ seconds).
  Future<Map<String, dynamic>?> _aiGetRaw(Uri uri, Duration timeout, [int tries = 2]) async {
    for (var i = 0; i < tries; i++) {
      try {
        final res = await http.get(uri).timeout(timeout);
        if (res.statusCode == 200) {
          aiLastError = null;
          final m = jsonDecode(res.body) as Map<String, dynamic>;
          _aiCache[uri.toString()] = m;
          _aiCache['latest:${uri.path}'] = m;
          _saveAiDisk(uri.toString(), m, res.body.length);
          return m;
        }
        aiLastError = 'The backend answered with HTTP ${res.statusCode}';
      } on TimeoutException {
        aiLastError = 'The backend did not answer within ${timeout.inSeconds}s (it is busy)';
      } catch (e) {
        aiLastError = e.toString();
      }
      if (i < tries - 1) await Future.delayed(const Duration(seconds: 2));
    }
    return null;
  }

  /// Phase 2: which exit rule (TP1 .. TP4 hold) did best per scenario (GET /api/ai/exit_study). Read-only.
  Future<Map<String, dynamic>?> fetchAiExitStudy({String tf = ''}) => _getAiMap('/api/ai/exit_study', tf);

  /// Indicator reading: what MAIN chart / Z-score / TSI said at signal time + wrong-use habits + best/avoid combos (GET /api/ai/reading). Read-only.
  Future<Map<String, dynamic>?> fetchAiReading({String tf = ''}) => _getAiMap('/api/ai/reading', tf);

  /// Strategy Doctor report (GET /api/ai/doctor, see strategy_doctor.py). null on failure.
  Future<Map<String, dynamic>?> fetchDoctor() => _getAiMap('/api/ai/doctor', '');

  /// Phase 3: repeat-SL coins + "enter only when Z and TSI confirm" test (GET /api/ai/wait_study). Read-only.
  Future<Map<String, dynamic>?> fetchAiWaitStudy({String tf = ''}) => _getAiMap('/api/ai/wait_study', tf);

  /// Result page: which signals to take + where to exit, proven on newer data (GET /api/ai/recipe). Read-only.
  Future<Map<String, dynamic>?> fetchAiRecipe({String tf = ''}) => _getAiMap('/api/ai/recipe', tf);

  /// AI Desk: the AI's own virtual account next to the bot (GET /api/ai/desk). Read-only.
  Future<Map<String, dynamic>?> fetchAiDesk() => _getAiMap('/api/ai/desk', '');

  /// AI Coach: AI-managed virtual trades vs the bot + what the AI found in Z/TSI/SD situations (GET /api/ai/coach). Read-only.
  Future<Map<String, dynamic>?> fetchAiCoach() => _aiGet(_u('/api/ai/coach'), timeout: const Duration(seconds: 10), tries: 1);

  /// AI Coach virtual balance in USDT (POST /api/ai/coach/config). 0 = default. null on failure.
  Future<Map<String, dynamic>?> setAiCoachBalance(double balance) async {
    try {
      final res = await http
          .post(_u('/api/ai/coach/config'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'balance': balance}))
          .timeout(_quickTimeout);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// The AI's day plan (paper only): target / loss cap / max open trades / give-back %. 0 = off (POST /api/ai/plan/config).
  Future<Map<String, dynamic>?> setAiPlanConfig(Map<String, double> cfg) async {
    try {
      final res = await http
          .post(_u('/api/ai/plan/config'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(cfg))
          .timeout(_quickTimeout);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// AI data backups: list + last time (GET /api/ai/backup). Not cached: the card wants the live answer.
  Future<Map<String, dynamic>?> fetchAiBackup() async {
    try {
      final res = await http.get(_u('/api/ai/backup')).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// Backup now (POST /api/ai/backup/run). The zip can be big, so it waits longer than a normal call.
  Future<Map<String, dynamic>?> runAiBackup() async {
    try {
      final res = await http.post(_u('/api/ai/backup/run'), headers: {'Content-Type': 'application/json'}, body: '{}').timeout(const Duration(seconds: 90));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  // ---- STAGE 2: the AI's own REAL Binance account (backend: /api/ai/live/*). Everything is OFF until the owner switches it on.
  Future<Map<String, dynamic>?> fetchAiLive() async {
    try {
      final res = await http.get(_u('/api/ai/live')).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

  /// POST /api/ai/live/<sub> (keys, keys/clear, check, config, enable, disable, panic, reset). Returns the answer, or null if it
  /// did not arrive. PANIC and the key check talk to Binance, so they wait longer than a normal call.
  Future<Map<String, dynamic>?> postAiLive(String sub, [Map<String, dynamic>? body]) async {
    try {
      final res = await http
          .post(_u('/api/ai/live/$sub'), headers: {'Content-Type': 'application/json'}, body: jsonEncode(body ?? <String, dynamic>{}))
          .timeout(Duration(seconds: (sub == 'panic' || sub == 'keys' || sub == 'check') ? 90 : 20));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
      return {'ok': false, 'error': 'The backend answered ${res.statusCode}.'};
    } catch (_) {}
    return null;
  }

  /// Queue a restore of one backup; it is applied when the backend restarts (POST /api/ai/backup/restore).
  Future<Map<String, dynamic>?> restoreAiBackup(String name) async {
    try {
      final res = await http.post(_u('/api/ai/backup/restore'), headers: {'Content-Type': 'application/json'}, body: jsonEncode({'name': name})).timeout(const Duration(seconds: 90));
      if (res.statusCode == 200) return jsonDecode(res.body) as Map<String, dynamic>;
    } catch (_) {}
    return null;
  }

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

  Future<Map<String, dynamic>?> fetchVisionDays({int n = 14}) async {
    try {
      final res = await http.get(_u('/api/vision/days?n=$n')).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }


  /// AI Pick: TAKE / SKIP / WATCH on every bot signal + what the AI has proven (GET /api/ai/pick). Read-only.
  Future<Map<String, dynamic>?> fetchAiPick() => _getAiMap('/api/ai/pick', '');

  /// AI own signals, shadow only: starts by itself once the AI Pick has proven something (GET /api/ai/selfsignal). Read-only.
  Future<Map<String, dynamic>?> fetchAiSelfSignal() => _getAiMap('/api/ai/selfsignal', '');

  /// One Free AI trade as chart data (candles, entry, first stop, every stop move, exit).
  Future<Map<String, dynamic>?> fetchAiFreeTrade(String key) =>
      _aiGet(_u('/api/ai/free_trade?k=${Uri.encodeQueryComponent(key)}'), timeout: const Duration(seconds: 20), tries: 1);

  /// Observer: the same bot trades replayed under other exit rules + entry-vs-exit verdict (GET /api/ai/observer). Read-only.
  Future<Map<String, dynamic>?> fetchAiObserver() => _getAiMap('/api/ai/observer', '');

  /// Per-trade diary: every saved bot trade with what the two trailing tests (STEP1 / STEP2) would have given (GET /api/ai/diary). Read-only.
  Future<Map<String, dynamic>?> fetchAiDiary() => _aiGet(_u('/api/ai/diary'), timeout: const Duration(seconds: 20), tries: 1);

  /// Yesterday / today / last 7 days in plain English, from the permanent trade archive (GET /api/daily-report). Read-only.
  Future<Map<String, dynamic>?> fetchDailyReport() => _aiGet(_u('/api/daily-report'), timeout: const Duration(seconds: 12), tries: 1);

  /// SD level / Z-SMA behaviour study: bounce vs break counts (GET /api/ai/levels). Read-only.
  Future<Map<String, dynamic>?> fetchAiLevels() => _getAiMap('/api/ai/levels', '');

  /// Phase 4: display-only advice badges per open position (GET /api/ai/advice).
  Future<Map<String, dynamic>?> fetchAiAdvice() => _getAiMap('/api/ai/advice', '');

  Future<Map<String, dynamic>?> _getAiMap(String path, String tf) =>
      _aiGet(_u(path).replace(queryParameters: tf.isEmpty ? null : {'tf': tf}));

  /// Restarts the A/B forward test from now (POST /api/ai/ab_board/reset). null on failure.
  Future<Map<String, dynamic>?> resetAiAbBoard() async {
    try {
      final res = await http.post(_u('/api/ai/ab_board/reset')).timeout(_quickTimeout);
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// Restores the saved AI Assistant conversation from the backend (see
  /// ai_chat_store.py) - called once when the chat screen opens, so a
  /// previous conversation survives an app restart instead of starting
  /// blank every time.
  Future<List<Map<String, dynamic>>> fetchAiHistory({String? chatId}) async {
    try {
      final uri = chatId == null || chatId.isEmpty
          ? _u('/api/ai/history')
          : _u('/api/ai/history').replace(queryParameters: {'chat_id': chatId});
      final res = await _getResilient(uri);
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return List<Map<String, dynamic>>.from(
          (data['messages'] as List<dynamic>? ?? []).map((m) => Map<String, dynamic>.from(m as Map)),
        );
      }
    } catch (_) {}
    return [];
  }

  /// Full multi-chat payload: messages + chat list + active id + mode.
  Future<Map<String, dynamic>> fetchAiHistoryBundle({String? chatId}) async {
    try {
      final uri = chatId == null || chatId.isEmpty
          ? _u('/api/ai/history')
          : _u('/api/ai/history').replace(queryParameters: {'chat_id': chatId});
      final res = await _getResilient(uri);
      if (res.statusCode == 200) {
        return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
      }
    } catch (_) {}
    return {'messages': [], 'chats': [], 'active': null, 'mode': 'general'};
  }

  Future<bool> clearAiHistory({String? chatId}) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/history/clear'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>?> createAiChat({String mode = 'general', String title = ''}) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'mode': mode, 'title': title}),
      );
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  Future<bool> setActiveAiChat(String chatId) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/active'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> deleteAiChat(String chatId) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/delete'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> renameAiChat(String chatId, String title) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/rename'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId, 'title': title}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

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

  // ---------------------------------------------------------------- live sync --

  /// Short human line shown for a few seconds after the live connection
  /// comes back ("Reconnected after 12s - synced, 1 trade closed while
  /// away"). Null when there is nothing to show.
  String? syncNotice;
  bool syncNoticeIsGood = true;
  Timer? _syncNoticeTimer;

  /// Set by main.dart: re-opens the WebSocket against the new URL.
  VoidCallback? onBackendUrlChanged;

  int? _lastTotalTrades;
  DateTime? _lastEquityRefresh;

  /// ISSUE 4 FIX - REST vs WS RACE: server_ts (epoch seconds, status.py's
  /// _display_status()) of the last status payload actually applied to
  /// `status`/`movers`/`positions`/`alerts` - from EITHER source, WS push
  /// or REST poll, whichever landed most recently. See _applyStatus()
  /// below for the sequencing check itself; this field only ever moves
  /// forward.
  double? _lastAppliedServerTs;

  void _showNotice(String text, {bool good = true, int seconds = 7}) {
    syncNotice = text;
    syncNoticeIsGood = good;
    _syncNoticeTimer?.cancel();
    _syncNoticeTimer = Timer(Duration(seconds: seconds), () {
      syncNotice = null;
      notifyListeners();
    });
    notifyListeners();
  }

  /// Asks the backend to catch-up-check every open trade against candles
  /// since it was last watched live (a TP/SL touched while the connection
  /// was down is applied now). Returns the summary or null if unreachable.
  Future<Map<String, dynamic>?> reconcileNow({String trigger = 'reconnect'}) async {
    try {
      final res = await _postResilient(
        _u('/api/reconcile'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'trigger': trigger}),
      );
      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  bool _resyncing = false;

  /// Called by WebSocketService.onReconnected. The WebSocket already
  /// delivered a fresh FULL_STATE_SNAPSHOT; this additionally makes the
  /// backend reconcile open trades and refreshes the REST-only data.
  Future<void> onWsReconnected(Duration outage) async {
    if (_resyncing) return;
    _resyncing = true;
    try {
      Map<String, dynamic>? rec;
      if (outage.inSeconds >= 5) {
        rec = await reconcileNow(trigger: 'reconnect');
      }
      await Future.wait([
        fetchStatus(),
        fetchSignals(),
        fetchEquity(force: true), // trades may have closed while we were offline
        fetchCalendar(),
      ]);
      final closed = (rec?['closed'] as num?)?.toInt() ?? 0;
      final checked = (rec?['checked'] as num?)?.toInt() ?? 0;
      var text = 'Reconnected after ${outage.inSeconds}s - live data synced';
      if (rec != null && checked > 0) {
        text += closed > 0
            ? ' · $closed of $checked open trades had closed while away'
            : ' · $checked open trades verified';
      }
      if (outage.inSeconds >= 10) _showNotice(text, good: true); // short blips stay silent
    } finally {
      _resyncing = false;
    }
  }

  /// Pushed data from the WebSocket connection (see websocket_service.dart).
  /// `init` = FULL_STATE_SNAPSHOT (sent on every (re)connect): replaces all
  /// live state. `update` = the 1s tick, same shape (the alert list is only
  /// included when it changed - the previous list is kept otherwise).
  void updateFromWebSocket(Map<String, dynamic> message) {
    final data = message['data'];
    if (data is Map<String, dynamic>) {
      _lastWsDataAt = DateTime.now();
      final isSnapshot = message['type'] == 'init';
      _applyStatus(data, snapshot: isSnapshot);
      error = null;
      // The backend pushes every 250ms. State is updated on EVERY message (so nothing is lost), but the
      // screens are only rebuilt about twice a second - 4 full rebuilds/s was what made the phone UI hang.
      // A snapshot (connect / resync) rebuilds right away.
      if (isSnapshot) {
        _wsNotifyTimer?.cancel();
        _wsNotifyTimer = null;
        _lastWsNotify = DateTime.now();
        notifyListeners();
      } else {
        _scheduleWsNotify();
      }
    }
  }

  static const Duration _wsNotifyGap = Duration(milliseconds: 500);
  Timer? _wsNotifyTimer;
  DateTime _lastWsNotify = DateTime.fromMillisecondsSinceEpoch(0);

  void _scheduleWsNotify() {
    if (_wsNotifyTimer != null) return; // a rebuild is already queued - it will show the newest state
    final wait = _wsNotifyGap - DateTime.now().difference(_lastWsNotify);
    if (wait <= Duration.zero) {
      _lastWsNotify = DateTime.now();
      notifyListeners();
      return;
    }
    _wsNotifyTimer = Timer(wait, () {
      _wsNotifyTimer = null;
      _lastWsNotify = DateTime.now();
      notifyListeners();
    });
  }

  /// ISSUE 4 FIX - REST vs WS RACE: this is the single choke point both
  /// fetchStatus() (main.dart's 15s Timer.periodic REST poll) and
  /// updateFromWebSocket() (the WebSocket's ~1s push) funnel through
  /// before touching `status`/`movers`/`positions`/`alerts`. Without a
  /// sequencing check, a REST response that happens to resolve AFTER a
  /// newer WS tick already landed (slow network hop, a Render free-tier
  /// cold-start retry, anything) would silently overwrite fresher data
  /// with staler data - screen flicker, or worse, a position/PnL number
  /// briefly regressing to an old value.
  ///
  /// The backend already stamps every payload with `server_ts` (epoch
  /// seconds, see status.py's _display_status()) - computed server-side
  /// so this is immune to phone/server clock drift, same reasoning
  /// feedAgeSec below already relies on. The fix is Flutter-only: compare
  /// the incoming server_ts against the last one actually applied
  /// (_lastAppliedServerTs), and discard anything strictly older.
  ///
  /// FAIL-OPEN, deliberately: if `server_ts` is missing, null, or not a
  /// number (an older backend build that predates this field, or any
  /// payload shape this never anticipated), the payload is always
  /// applied - a formatting quirk must never silently drop real data.
  /// A FULL_STATE_SNAPSHOT (`snapshot: true`, sent on every WS (re)connect)
  /// is also always applied regardless of its timestamp - a reconnect
  /// resync is a deliberate full refresh, not a routine tick that lost a
  /// race, and must never be the payload that gets dropped.
  bool _isStaleStatusPayload(Map<String, dynamic> data, {required bool snapshot}) {
    if (snapshot) return false;
    final rawTs = data['server_ts'];
    final incomingTs = (rawTs is num) ? rawTs.toDouble() : null;
    if (incomingTs == null) return false; // fail-open
    final lastTs = _lastAppliedServerTs;
    if (lastTs != null && incomingTs < lastTs) return true;
    return false;
  }

  void _applyStatus(Map<String, dynamic> data, {bool snapshot = false}) {
    if (_isStaleStatusPayload(data, snapshot: snapshot)) {
      // A fresher payload (almost always a WS tick) already landed after
      // this one was sent - drop it silently, exactly like the update it
      // lost a race with never happened. Nothing here to roll back: this
      // request never got a chance to mutate any state in the first place.
      return;
    }
    final rawTs = data['server_ts'];
    if (rawTs is num) {
      final incomingTs = rawTs.toDouble();
      if (_lastAppliedServerTs == null || incomingTs > _lastAppliedServerTs!) {
        _lastAppliedServerTs = incomingTs;
      }
    }

    final merged = Map<String, dynamic>.from(data);
    _lastRawStatus = data;
    if (!merged.containsKey('alerts')) merged['alerts'] = alerts;
    // New signal -> refresh the Signals list right away (the backend records it
    // in the DB within ms of updating last_signals; 800ms delay covers that).
    final prevSig = (status['last_signals'] as List?)?.isNotEmpty == true ? '${(status['last_signals'] as List).first}' : null;
    final newSig = (merged['last_signals'] as List?)?.isNotEmpty == true ? '${(merged['last_signals'] as List).first}' : null;
    if (!snapshot && newSig != null && newSig != prevSig) Future.delayed(const Duration(milliseconds: 800), fetchSignals);
    status = merged;
    final prevAlertsRef = alerts;
    final rawA = data['alerts'];
    if (rawA is List<dynamic>) _rawAlerts = rawA;
    if (snapshot) {
      movers = (merged['market_movers'] as List<dynamic>?) ?? [];
      positions = (merged['open_positions'] as List<dynamic>?) ?? [];
    } else {
      movers = (merged['market_movers'] as List<dynamic>?) ?? movers;
      positions = (merged['open_positions'] as List<dynamic>?) ?? positions;
    }
    if (rawA is List<dynamic> || snapshot) alerts = _alertsForBot(_rawAlerts);
    // Rev counters: alerts only come over the wire when they changed (the
    // backend skips them otherwise), so a new list object == changed.
    if (!identical(prevAlertsRef, alerts)) alertsRev++;
    final mSig = Object.hashAll(movers.map((m) => m is Map
        ? Object.hash(m['symbol'], m['price'], m['change_pct'], m['category'])
        : 0));
    if (mSig != _moversSig || movers.isEmpty) {
      _moversSig = mSig;
      moversRev++;
    }
    _soundOnStatus(snapshot: snapshot);
    // A trade closed -> the equity curve is stale. Refresh it (at most every
    // 5s) instead of only on app start / timeframe change.
    final tt = (merged['total_trades'] as num?)?.toInt();
    if (tt != null) {
      final prev = _lastTotalTrades;
      _lastTotalTrades = tt;
      final now = DateTime.now();
      if (prev != null &&
          prev != tt &&
          (_lastEquityRefresh == null || now.difference(_lastEquityRefresh!).inSeconds >= 5)) {
        _lastEquityRefresh = now;
        Future.microtask(() => fetchEquity(force: true));
        Future.microtask(() => fetchCalendar());
      }
    }
  }

  // ------------------------------------------------ diagnostics telemetry --
  // Typed accessors over the raw `status` map (populated by _applyStatus()
  // from every WS push / fetchStatus() call) for the DiagnosticsCard and
  // anything else that wants real feed-health data - see api_server.py's
  // _display_status() for the real (never-mocked) backend contract behind
  // every one of these. No independent caching or computation here: each
  // getter just reads straight out of whatever the backend most recently
  // sent, so it can never drift from ground truth.

  /// Seconds since the last successful market-data tick, AS OF THE SERVER'S
  /// OWN CLOCK at the moment it built this payload - computed server-side
  /// (server_ts - feed_last_update_ts) specifically so this is immune to
  /// phone/server clock drift. Null until the feed has ticked at least once.
  double? get feedAgeSec => (status['feed_age_sec'] as num?)?.toDouble();

  /// Exchange-Event-Time -> Engine-Ingestion network latency, ms (from the
  /// last processed Binance WS frame's own "E" timestamp). Null until the
  /// feed has ticked at least once.
  double? get feedLatencyNetMs => (status['feed_latency_net_ms'] as num?)?.toDouble();

  /// Engine-Ingestion -> cache-write-complete processing latency, ms.
  double? get feedLatencyEngineMs => (status['feed_latency_engine_ms'] as num?)?.toDouble();

  /// Server epoch-seconds timestamp this whole status payload was built at -
  /// the reference point the DiagnosticsCard uses to derive "App Display"
  /// latency (DateTime.now() minus this, converted to the same epoch).
  double? get serverTs => (status['server_ts'] as num?)?.toDouble();

  int get wsReconnectCountFromStatus => (status['ws_reconnect_count'] as num?)?.toInt() ?? 0;

  String get marketDataState => (status['market_data_state'] as String?) ?? 'DISCONNECTED';

  /// Candle-close -> order-dispatch seconds for the last trade, plus the
  /// average / worst over the last 50 (backend app.py _record_signal_lag).
  double? get signalLagLastS => (status['signal_lag_last_s'] as num?)?.toDouble();
  double? get signalLagAvgS => (status['signal_lag_avg_s'] as num?)?.toDouble();
  double? get signalLagWorstS => (status['signal_lag_worst_s'] as num?)?.toDouble();
  int get signalLagCount => (status['signal_lag_n'] as num?)?.toInt() ?? 0;
  double? get serverTimeOffsetMs => (status['server_time_offset_ms'] as num?)?.toDouble();

  /// Symbols the most recent protection guard_tick() found with NO resting
  /// stop on Binance - empty means every open live position was confirmed
  /// protected as of that tick. See protection_manager.py's guard_tick().
  List<Map<String, dynamic>> get unprotectedPositions =>
      ((status['unprotected_positions'] as List<dynamic>?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();

  /// Rolling log of raw Binance API error codes (newest first) - see
  /// status.add_api_error(), fed from binance_trader.py's and
  /// protection_manager.py's shared signed-request choke point.
  List<Map<String, dynamic>> get recentApiErrors =>
      ((status['recent_api_errors'] as List<dynamic>?) ?? [])
          .whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e))
          .toList();

  Map<String, dynamic>? get lastGuardTick =>
      status['last_guard_tick'] is Map ? Map<String, dynamic>.from(status['last_guard_tick'] as Map) : null;

  /// Real aggregated unrealized P&L / margin across whatever open_positions
  /// are currently being shown (paper or live) - computed backend-side in
  /// _display_status() from the same list the Positions screen renders, so
  /// this can never disagree with what's on screen.
  double get openPnl => (status['open_pnl'] as num?)?.toDouble() ?? 0.0;
  /// P&L RULE FOR THE WHOLE APP (paper mode): the big TODAY number = closed trades only (changes only when a trade
  /// closes, matches the Daily target). Open P&L is shown small and separate, live. Everything is already after fee.
  double get closedPnl => (status['today_pnl_usdt'] as num?)?.toDouble() ?? 0.0;
  double get todayTotal => closedPnl + openPnl;

  /// Closed-trade P&L for the Today / 7D / 30D row (backend trade_store.get_period_stats, paper mode only, null in live).
  Map<String, dynamic>? get periodPnl =>
      status['period_pnl'] is Map ? Map<String, dynamic>.from(status['period_pnl'] as Map) : null;
  double get pnl7d => (periodPnl?['d7_pnl'] as num?)?.toDouble() ?? 0.0;
  double get pnl30d => (periodPnl?['d30_pnl'] as num?)?.toDouble() ?? 0.0;
  int get trades7d => (periodPnl?['d7_trades'] as num?)?.toInt() ?? 0;
  int get trades30d => (periodPnl?['d30_trades'] as num?)?.toInt() ?? 0;
  double get openMarginUsed => (status['open_margin_used'] as num?)?.toDouble() ?? 0.0;

  /// Real Binance USDT futures wallet (LIVE mode only, null in paper mode). Keys: ok, wallet, available,
  /// unrealized, margin_balance, margin_used, error. Sent by api_server.py as status['live_wallet'].
  Map<String, dynamic>? get liveWallet {
    final w = status['live_wallet'];
    if (w is Map) return Map<String, dynamic>.from(w);
    return null;
  }

  /// "live" or "paper" - see api_server.py's _display_status() STRICT STATE
  /// ISOLATION contract. When "live", today_pnl_usdt/total_trades/win_rate/
  /// wins/losses are all null (never a fabricated 0 or a stale paper
  /// number) because those stats are PAPER-only in this backend.
  String get statsMode => (status['stats_mode'] as String?) ?? 'paper';

  /// Sends one message to the AI Assistant backend along with recent chat
  /// history (so it has multi-turn context - this module itself stays
  /// stateless, see ai_assistant.py). Returns the reply text on success, or
  /// null with `error` set on failure so the chat screen can show it inline.
  Future<String?> askAi(String message, List<Map<String, String>> history, {String? chatId, String? mode, String? imageB64}) async {
    try {
      final body = <String, dynamic>{
        'message': message,
        'history': history,
        if (chatId != null) 'chat_id': chatId,
        if (mode != null) 'mode': mode,
        if (imageB64 != null) 'image_b64': imageB64,
      };
      final res = await _postResilient(
        _u('/api/ai/ask'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (res.statusCode == 200 && data['ok'] == true) {
        return data['reply'] as String?;
      }
      error = (data['error'] as String?) ?? 'AI request failed (${res.statusCode})';
      notifyListeners();
      return null;
    } catch (e) {
      error = 'Cannot reach backend: $e';
      notifyListeners();
      return null;
    }
  }

  /// Called from the Settings screen once a Backend URL field is added there.
  Future<void> setBackendUrl(String url) async {
    baseUrl = url.trim();
    await prefs.setString(_backendUrlKey, baseUrl);
    onBackendUrlChanged?.call();
    await init();
  }

  // ------------------------------------------------------- sound alerts --
  // Trade sounds (assets/sounds/): order_filled.mp3 on ENTRY, Target_hit.mp3
  // on a profit / TP exit, Stoploss_hit.mp3 on a stop-loss exit. The daily
  // target / loss-limit alerts reuse Target_hit / Stoploss_hit. Detection is
  // purely client-side: it diffs the open-positions list between status
  // updates, so no backend change is needed.
  //   * first data after start, a mode switch (PAPER<->LIVE) and every
  //     WebSocket (re)connect snapshot only RE-BASELINE - never play, so
  //     old positions are not re-announced.
  //   * events inside a 1.2s window are merged (one sound per kind).
  //   * exit reason (TP2 hit / Stop loss hit ...) comes from the Alerts feed
  //     entry the backend already writes for that trade.
  final SoundService sound = SoundService();

  // Pref keys kept as-is so an existing on/off choice survives the update.
  static const _kSoundOn = 'voice_enabled';
  static const _kSoundEntry = 'voice_entry';
  static const _kSoundExit = 'voice_exit';
  static const _kSoundFgOnly = 'voice_fg_only';

  bool get soundEnabled => prefs.getBool(_kSoundOn) ?? true;
  bool get soundEntryOn => prefs.getBool(_kSoundEntry) ?? true;
  bool get soundExitOn => prefs.getBool(_kSoundExit) ?? true;
  bool get soundOnlyWhenOpen => prefs.getBool(_kSoundFgOnly) ?? false;

  Future<void> setSoundEnabled(bool v) async {
    await prefs.setBool(_kSoundOn, v);
    pushPrefsBackup();
    if (!v) await sound.stop();
    notifyListeners();
  }

  Future<void> setSoundEntryOn(bool v) async {
    await prefs.setBool(_kSoundEntry, v);
    pushPrefsBackup();
    notifyListeners();
  }

  Future<void> setSoundExitOn(bool v) async {
    await prefs.setBool(_kSoundExit, v);
    pushPrefsBackup();
    notifyListeners();
  }

  Future<void> setSoundOnlyWhenOpen(bool v) async {
    await prefs.setBool(_kSoundFgOnly, v);
    pushPrefsBackup();
    notifyListeners();
  }

  /// One of the three test buttons in Settings - ignores the master toggle
  /// on purpose so the person can check volume before turning alerts on.
  Future<void> testSound(TradeSound s) => sound.play(s);

  bool _appForeground = true;
  void setAppForeground(bool fg) => _appForeground = fg;

  Map<String, Map<String, dynamic>> _soundKnown = {};
  bool _soundBaselined = false;
  String? _soundMode;
  double _soundLastAlertTs = 0;
  bool _soundEntryPending = false;
  final List<Map<String, dynamic>> _soundExitBuf = [];
  Timer? _soundFlush;

  bool get _soundMayPlay => soundEnabled && (!soundOnlyWhenOpen || _appForeground);

  void _soundOnStatus({required bool snapshot}) {
    try {
      final current = <String, Map<String, dynamic>>{};
      for (final e in positions) {
        if (e is Map) {
          final m = e.cast<String, dynamic>();
          current['${m['id']}'] = m;
        }
      }
      final mode = statsMode;
      final firstData = !_soundBaselined || _soundMode != mode;

      // Daily target / loss-limit alerts (type 'target' / 'loss').
      double maxTs = _soundLastAlertTs;
      final fresh = <Map>[];
      for (final a in alerts) {
        if (a is Map) {
          final ts = (a['ts'] as num?)?.toDouble() ?? 0;
          if (ts > maxTs) maxTs = ts;
          final type = a['type'];
          if (ts > _soundLastAlertTs && (type == 'loss' || type == 'target')) fresh.add(a);
        }
      }
      final alertBaseline = !_soundBaselined;
      _soundLastAlertTs = maxTs;

      if (firstData || snapshot) {
        _soundKnown = current;
        _soundBaselined = true;
        _soundMode = mode;
        return; // never play on baseline / reconnect snapshot
      }

      if (!alertBaseline && fresh.isNotEmpty && _soundMayPlay) {
        sound.play(fresh.first['type'] == 'loss' ? TradeSound.stopLossHit : TradeSound.targetHit);
      }

      for (final id in current.keys) {
        if (!_soundKnown.containsKey(id)) _soundEntryPending = true;
      }
      for (final id in _soundKnown.keys) {
        if (!current.containsKey(id)) _soundExitBuf.add(_soundKnown[id]!);
      }
      _soundKnown = current;
      if ((_soundEntryPending || _soundExitBuf.isNotEmpty) && _soundFlush == null) {
        _soundFlush = Timer(const Duration(milliseconds: 1200), _soundFlushNow);
      }
    } catch (e) {
      debugPrint('sound detect failed: $e');
    }
  }

  void _soundFlushNow() {
    _soundFlush = null;
    final entered = _soundEntryPending;
    final exits = List<Map<String, dynamic>>.from(_soundExitBuf);
    _soundEntryPending = false;
    _soundExitBuf.clear();
    if (!_soundMayPlay) return;
    try {
      if (entered && soundEntryOn) sound.play(TradeSound.orderFilled);
      if (exits.isNotEmpty && soundExitOn) {
        var anySl = false;
        var anyTp = false;
        for (final p in exits) {
          if (_isStopLossExit(_closeInfo(p))) {
            anySl = true;
          } else {
            anyTp = true;
          }
        }
        if (anyTp) sound.play(TradeSound.targetHit);
        if (anySl) sound.play(TradeSound.stopLossHit);
      }
    } catch (e) {
      debugPrint('sound play failed: $e');
    }
  }

  /// Stop-loss sound for SL / trailing-SL exits, and for any other exit that
  /// ended in a loss (manual close, reversed). TP hits and profitable exits
  /// get the target sound.
  bool _isStopLossExit(_CloseInfo info) {
    final r = (info.reason ?? '').toLowerCase();
    if (r.contains('stop loss') || r.contains('sl hit')) return true;
    if (r.startsWith('tp') || r.contains('target')) return false;
    return info.pnl < 0;
  }

  /// P&L + reason for a position that just disappeared: prefers the Alerts
  /// feed entry for that trade id (exact final P&L + reason label), falls
  /// back to the last P&L seen on the open position.
  _CloseInfo _closeInfo(Map<String, dynamic> lastPos) {
    double pnl = (lastPos['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
    String? reason;
    final id = '${lastPos['id']}';
    for (final a in alerts) {
      if (a is! Map) continue;
      final d = a['d'];
      if (d is Map && '${d['trade_id']}' == id && d['reason'] != null) {
        final n = d['pnl'];
        if (n is num) pnl = n.toDouble();
        final label = d['reason_label'];
        if (label is String && label.isNotEmpty) reason = label;
        break;
      }
    }
    return _CloseInfo(pnl, reason);
  }
}

/// Final P&L + human reason ("TP2 hit", "Stop loss hit") of a closed trade,
/// used only to pick the exit sound.
class _CloseInfo {
  final double pnl;
  final String? reason;
  const _CloseInfo(this.pnl, this.reason);
}
