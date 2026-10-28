import 'dart:ui' show ImageFilter;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../services/sound_service.dart';
import '../widgets/ai_keys_card.dart';
import '../widgets/owl_route.dart';
import '../widgets/report_download_card.dart';
import '../widgets/settings_group.dart';
import '../widgets/settings_input_field.dart';
import 'ai_assistant_screen.dart';
import '../theme/app_theme.dart';

// ------------------------------------------------------------- field registry ----

/// When a saved value takes effect on the backend - shown on the change list
/// and on the "Saved" receipt so it is clear what applies right now.
const _scopeLive = 'applies live';
const _scopeNew = 'new trades only';
const _scopeNewLive = 'new live orders only';
const _scopeRestart = 'needs backend restart';

const _numKeys = <String>[
  'invest_amount',
  'leverage',
  'scalp_close_roi_pct',
  'daily_target_usdt',
  'daily_loss_limit_usdt',
  'position_size_value',
  'live_leverage',
  'max_open_trades',
];
const _textKeys = <String>[
  'telegram_bot_token',
  'telegram_chat_id',
  'binance_api_key',
  'binance_api_secret',
  'ai_api_key',
  'ai_model',
  'ai2_provider',
  'ai2_api_key',
  'ai3_provider',
  'ai3_api_key',
  'ai4_provider',
  'ai4_api_key',
];

const _labels = <String, String>{
  'timeframe': 'Strategy Timeframe',
  'trail_mode': 'Trailing stop',
  'invest_amount': 'Invest Amount',
  'leverage': 'Leverage',
  'scalp_close_roi_pct': 'Universal TP %',
  'daily_target_usdt': 'Daily Target',
  'daily_loss_limit_usdt': 'Daily Loss Limit',
  'position_size_value': 'Live position size',
  'live_leverage': 'Live leverage',
  'position_size_mode': 'Position size mode',
  'live_trading_enabled': 'Live trading',
  'ai_enabled': 'AI Assistant',
  'max_open_trades': 'Max open trades',
  'daily_gate_enabled': 'Daily schedule',
  'block_sell_on_gainer': 'No SELL on gainers',
  'block_buy_on_loser': 'No BUY on losers',
  'ai_provider': 'AI provider',
  'telegram_bot_token': 'Telegram bot token',
  'telegram_chat_id': 'Telegram chat ID',
  'binance_api_key': 'Binance API key',
  'binance_api_secret': 'Binance API secret',
  'ai_api_key': 'AI API key',
  'ai_model': 'AI model',
  'ai2_provider': 'AI backup provider',
  'ai2_api_key': 'AI backup key',
  'ai3_provider': 'AI backup provider 2',
  'ai3_api_key': 'AI backup key 2',
  'ai4_provider': 'AI backup provider 3',
  'ai4_api_key': 'AI backup key 3',
};

const _scopes = <String, String>{
  'timeframe': _scopeLive,
  'trail_mode': _scopeLive,
  'invest_amount': _scopeNew,
  'leverage': _scopeNew,
  'scalp_close_roi_pct': _scopeLive,
  'daily_target_usdt': _scopeLive,
  'daily_loss_limit_usdt': _scopeLive,
  'position_size_value': _scopeNewLive,
  'live_leverage': _scopeNewLive,
  'position_size_mode': _scopeNewLive,
  'live_trading_enabled': _scopeLive,
  'ai_enabled': _scopeLive,
  'max_open_trades': _scopeLive,
  'daily_gate_enabled': _scopeLive,
  'block_sell_on_gainer': _scopeLive,
  'block_buy_on_loser': _scopeLive,
  'ai_provider': _scopeLive,
  'telegram_bot_token': _scopeRestart,
  'telegram_chat_id': _scopeRestart,
  'binance_api_key': _scopeLive,
  'binance_api_secret': _scopeLive,
  'ai_api_key': _scopeLive,
  'ai_model': _scopeLive,
  'ai2_provider': _scopeLive,
  'ai2_api_key': _scopeLive,
  'ai3_provider': _scopeLive,
  'ai3_api_key': _scopeLive,
  'ai4_provider': _scopeLive,
  'ai4_api_key': _scopeLive,
};

const _secretKeys = <String>{
  'telegram_bot_token',
  'binance_api_key',
  'binance_api_secret',
  'ai_api_key',
  'ai2_api_key',
  'ai3_api_key',
  'ai4_api_key',
};

const _numDefaults = <String, double>{
  'invest_amount': 10.0,
  'leverage': 1.0,
  'scalp_close_roi_pct': 0.0,
  'daily_target_usdt': 0.0,
  'daily_loss_limit_usdt': 0.0,
  'position_size_value': 10.0,
  'live_leverage': 3.0,
  'max_open_trades': 0.0,
};

class _Change {
  final String key;
  final dynamic oldRaw;
  final dynamic newRaw;
  const _Change(this.key, this.oldRaw, this.newRaw);

  String get label => _labels[key] ?? key;
  String get scope => _scopes[key] ?? _scopeLive;
  bool get secret => _secretKeys.contains(key);
}

class _Receipt {
  final DateTime at;
  final List<_Change> changes;
  final Map<String, bool> confirmed;
  _Receipt(this.at, this.changes, this.confirmed);
}

String _fmtVal(dynamic v, {bool secret = false}) {
  if (secret) return (v == null || '$v'.isEmpty) ? '(empty)' : '••••';
  if (v is bool) return v ? 'ON' : 'OFF';
  if (v is num) {
    final d = v.toDouble();
    return d == d.roundToDouble() ? d.toStringAsFixed(0) : d.toString();
  }
  final s = '${v ?? ''}';
  return s.isEmpty ? '(empty)' : s;
}

bool _same(dynamic a, dynamic b) {
  if (a is num && b is num) return (a.toDouble() - b.toDouble()).abs() < 1e-9;
  return a == b;
}

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final Map<String, TextEditingController> _controllers = {};
  late TextEditingController _backendUrlController;
  late AppProvider _provider;

  /// What the SERVER currently holds (typed: doubles / strings / bools) for
  /// every field on this screen. "Unsaved changes" = form values that differ.
  Map<String, dynamic> _baseline = {};
  bool _loaded = false;
  bool _suppress = false; // true while _loadFrom writes controller text (avoids setState during initState)

  bool _isSaving = false;
  bool _isSavingBackend = false;
  bool _isTestingBinanceConnection = false;
  String? _binanceTestConnectionResult;
  bool _showDiff = false;
  _Receipt? _receipt;

  bool _liveTradingEnabled = false;
  String _positionSizeMode = 'fixed';
  bool _aiEnabled = false;
  bool _dailyGate = true;        // IST schedule: off 01:30, no trades 05:30-09:30, on 09:30
  bool _blockSellGainer = false; // no SELL on a top-10 gainer until price crosses SD0 downward
  bool _blockBuyLoser = false;   // no BUY on a top-10 loser until price crosses SD0 upward
  String _aiProvider = 'openai';
  String _timeframe = '5m';
  String _trailMode = 'step1'; // 'off' | 'step1' | 'step2' (backend setting trail_mode)
  // TP EXECUTION MODE: derived from scalp_close_roi_pct (>0 = universal),
  // but kept as its own toggle state so switching to 'strategy' can zero
  // the field WITHOUT losing whatever % the user had typed, in case they
  // flip back to 'universal' a moment later.
  String _tpMode = 'strategy'; // 'strategy' | 'universal'
  double _lastUniversalRoi = 25.0;

  static const _timeframeOptions = <String>['1m', '3m', '5m', '15m', '1h'];
  static const _trailOptions = <String>['off', 'step1', 'step2'];
  static const _trailTitles = <String, String>{'off': 'Off', 'step1': '1-step', 'step2': '2-step'};

  @override
  void initState() {
    super.initState();
    _provider = Provider.of<AppProvider>(context, listen: false);
    _backendUrlController = TextEditingController(text: _provider.baseUrl);
    for (final k in [..._numKeys, ..._textKeys]) {
      final c = TextEditingController();
      c.addListener(_onEdited);
      _controllers[k] = c;
    }
    if (_provider.settings.isNotEmpty) {
      _loadFrom(_provider.settings);
    } else {
      // Settings not fetched yet (cold start / backend slow). Saving before
      // they arrive would overwrite the real values with defaults, so the
      // form stays locked until they load.
      _provider.addListener(_waitForSettings);
      _provider.fetchSettings();
    }
  }

  void _waitForSettings() {
    if (_loaded || _provider.settings.isEmpty) return;
    _provider.removeListener(_waitForSettings);
    if (mounted) setState(() => _loadFrom(_provider.settings));
  }

  @override
  void dispose() {
    _provider.removeListener(_waitForSettings);
    for (final c in _controllers.values) {
      c.dispose();
    }
    _backendUrlController.dispose();
    super.dispose();
  }

  // ------------------------------------------------------------ state <-> UI ----

  Map<String, dynamic> _normalize(Map<String, dynamic> s) {
    final out = <String, dynamic>{};
    for (final k in _numKeys) {
      final v = s[k];
      out[k] = v is num ? v.toDouble() : (double.tryParse('${v ?? ''}') ?? _numDefaults[k]!);
    }
    for (final k in _textKeys) {
      out[k] = '${s[k] ?? ''}';
    }
    out['live_trading_enabled'] = s['live_trading_enabled'] == true;
    out['position_size_mode'] = '${s['position_size_mode'] ?? 'fixed'}';
    out['ai_enabled'] = s['ai_enabled'] == true;
    out['daily_gate_enabled'] = s['daily_gate_enabled'] != false;
    out['block_sell_on_gainer'] = s['block_sell_on_gainer'] == true;
    out['block_buy_on_loser'] = s['block_buy_on_loser'] == true;
    out['ai_provider'] = '${s['ai_provider'] ?? 'openai'}';
    out['timeframe'] = _timeframeOptions.contains(s['timeframe']) ? '${s['timeframe']}' : '5m';
    out['trail_mode'] = _trailOptions.contains(s['trail_mode']) ? '${s['trail_mode']}' : 'step1';
    return out;
  }

  /// Pushes server values into the form and makes them the new baseline.
  void _loadFrom(Map<String, dynamic> serverSettings) {
    _suppress = true;
    final n = _normalize(serverSettings);
    _baseline = n;
    for (final k in _numKeys) {
      _controllers[k]!.text = _fmtVal(n[k]);
    }
    for (final k in _textKeys) {
      _controllers[k]!.text = n[k] as String;
    }
    _liveTradingEnabled = n['live_trading_enabled'] as bool;
    _positionSizeMode = n['position_size_mode'] as String;
    _aiEnabled = n['ai_enabled'] as bool;
    _dailyGate = n['daily_gate_enabled'] as bool;
    _blockSellGainer = n['block_sell_on_gainer'] as bool;
    _blockBuyLoser = n['block_buy_on_loser'] as bool;
    _aiProvider = n['ai_provider'] as String;
    _timeframe = n['timeframe'] as String;
    _trailMode = n['trail_mode'] as String;
    final roi = n['scalp_close_roi_pct'] as double?;
    _tpMode = (roi != null && roi > 0) ? 'universal' : 'strategy';
    if (roi != null && roi > 0) _lastUniversalRoi = roi;
    _loaded = true;
    _suppress = false;
  }

  void _onEdited() {
    if (!mounted || _suppress) return;
    setState(() {
      if (_receipt != null) _receipt = null; // a new edit starts a fresh cycle
    });
  }

  /// Current form values, typed. Invalid number text -> null for that key.
  Map<String, dynamic> _current() {
    final out = <String, dynamic>{};
    for (final k in _numKeys) {
      out[k] = double.tryParse(_controllers[k]!.text.trim().replaceAll(',', '.'));
    }
    for (final k in _textKeys) {
      out[k] = _controllers[k]!.text.trim();
    }
    out['live_trading_enabled'] = _liveTradingEnabled;
    out['position_size_mode'] = _positionSizeMode;
    out['ai_enabled'] = _aiEnabled;
    out['daily_gate_enabled'] = _dailyGate;
    out['block_sell_on_gainer'] = _blockSellGainer;
    out['block_buy_on_loser'] = _blockBuyLoser;
    out['ai_provider'] = _aiProvider;
    out['timeframe'] = _timeframe;
    out['trail_mode'] = _trailMode;
    return out;
  }

  Map<String, String> _errors() {
    if (!_loaded) return const {};
    final cur = _current();
    final errs = <String, String>{};
    for (final k in _numKeys) {
      final v = cur[k];
      if (v == null) {
        errs[k] = 'Enter a number';
      } else if (v < 0) {
        errs[k] = 'Cannot be negative';
      } else if ((k == 'invest_amount' || k == 'position_size_value') && v <= 0) {
        errs[k] = 'Must be more than 0';
      } else if ((k == 'leverage' || k == 'live_leverage') && v < 1) {
        errs[k] = 'Minimum is 1';
      } else if (k == 'max_open_trades' && v != v.roundToDouble()) {
        errs[k] = 'Use a whole number';
      }
    }
    return errs;
  }

  List<_Change> _changes() {
    if (!_loaded) return const [];
    final cur = _current();
    final out = <_Change>[];
    for (final k in cur.keys) {
      final nv = cur[k];
      if (nv == null) continue; // invalid - reported via _errors()
      if (!_same(nv, _baseline[k])) out.add(_Change(k, _baseline[k], nv));
    }
    return out;
  }

  List<String> _warnings(List<_Change> changes) {
    final cur = _current();
    final w = <String>[];
    bool changed(String k) => changes.any((c) => c.key == k);
    final lev = cur['leverage'] as double?;
    final liveLev = cur['live_leverage'] as double?;
    final scalp = cur['scalp_close_roi_pct'] as double?;
    if (changed('leverage') && lev != null && lev > 10) w.add('Leverage ${_fmtVal(lev)}x is high - small moves hit SL fast.');
    if (changed('live_leverage') && liveLev != null && liveLev > 10) {
      w.add('Live leverage ${_fmtVal(liveLev)}x is high - real money.');
    }
    if (changed('live_trading_enabled') && _liveTradingEnabled) {
      w.add('Live trading will be turned ON - real orders with real money.');
    }
    if (_liveTradingEnabled && (cur['daily_loss_limit_usdt'] as double? ?? 0) == 0 && changed('live_trading_enabled')) {
      w.add('Live trading is ON but Daily Loss Limit is 0 (no limit).');
    }
    if (changed('scalp_close_roi_pct') && scalp != null && scalp > 0 && scalp < 1) {
      w.add('Universal TP % below 1% - fees/slippage can eat it.');
    }
    if (changed('scalp_close_roi_pct') && scalp != null && scalp > 100) {
      w.add('Universal TP % above 100% ROI is rarely reached.');
    }
    if (changed('timeframe')) {
      w.add('Timeframe change clears cached candle history for every symbol and re-fetches at $_timeframe - a brief gap in signals is normal right after saving.');
    }
    return w;
  }

  // ------------------------------------------------------------------- actions ----

  Future<void> _saveBackendUrl() async {
    final url = _backendUrlController.text.trim();
    if (url.isEmpty) return;
    setState(() => _isSavingBackend = true);
    await _provider.setBackendUrl(url);
    if (mounted) setState(() => _isSavingBackend = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Backend URL saved - reconnecting live data...')),
      );
      _provider.fetchSettings().then((_) {
        if (mounted && _provider.settings.isNotEmpty && _changes().isEmpty) setState(() => _loadFrom(_provider.settings));
      });
    }
  }

  /// Returns true if everything was saved (or there was nothing to save).
  Future<bool> _save({bool silent = false}) async {
    if (_isSaving) return false;
    if (!_loaded) {
      _snack('Settings are still loading - try again in a moment.');
      return false;
    }
    if (_errors().isNotEmpty) {
      _snack('Fix the highlighted fields first.');
      return false;
    }
    final changes = _changes();
    if (changes.isEmpty) {
      if (!silent) _snack('No changes to save.');
      return true;
    }
    if (!silent) {
      final warnings = _warnings(changes);
      if (warnings.isNotEmpty) {
        final p = context.palette;
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: p.surfaceElevated,
            title: Text('Please confirm', style: TextStyle(color: p.textPrimary)),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final t in warnings)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text('⚠️ $t', style: AppTypography.secondaryData.copyWith(color: p.warning, fontSize: 13)),
                  ),
              ],
            ),
            actions: [
              TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: Text('Save anyway', style: TextStyle(color: p.accent)),
              ),
            ],
          ),
        );
        if (ok != true) return false;
      }
    }

    setState(() => _isSaving = true);
    // Only the changed keys are sent - untouched settings are never rewritten.
    final payload = {for (final c in changes) c.key: c.newRaw};
    final server = await _provider.updateSettings(payload);
    if (!mounted) return server != null;
    if (server == null) {
      setState(() => _isSaving = false);
      _snack('Save failed: ${_provider.error ?? 'backend not reachable'}. Your edits are still here.', bad: true);
      return false;
    }
    // Compare what the backend now holds with what we sent.
    final confirmed = <String, bool>{};
    final serverNorm = _normalize(server);
    for (final c in changes) {
      confirmed[c.key] = _same(serverNorm[c.key], c.newRaw);
    }
    HapticFeedback.mediumImpact();
    setState(() {
      _isSaving = false;
      _baseline = serverNorm;
      _showDiff = false;
      if (!silent) _receipt = _Receipt(DateTime.now(), changes, confirmed);
    });
    return true;
  }

  Future<void> _undo() async {
    final r = _receipt;
    if (r == null) return;
    setState(() => _isSaving = true);
    final server = await _provider.updateSettings({for (final c in r.changes) c.key: c.oldRaw});
    if (!mounted) return;
    setState(() {
      _isSaving = false;
      if (server != null) {
        _loadFrom(server);
        _receipt = null;
      }
    });
    _snack(server != null ? 'Reverted ${r.changes.length} change(s).' : 'Undo failed - backend not reachable.',
        bad: server == null);
  }

  void _discard() {
    setState(() {
      _loadFrom({..._baseline});
      _showDiff = false;
    });
  }

  void _snack(String msg, {bool bad = false}) {
    if (!mounted) return;
    final p = context.palette;
    final Color tone = bad ? p.negative : p.accent;
    final IconData icon = bad ? Icons.error_outline_rounded : Icons.info_outline_rounded;
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        behavior: SnackBarBehavior.floating,
        backgroundColor: Colors.transparent,
        elevation: 0,
        margin: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.xl),
        padding: EdgeInsets.zero,
        duration: const Duration(milliseconds: 2400),
        content: Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: tone.withOpacity(0.55), width: 1),
            boxShadow: [
              BoxShadow(color: tone.withOpacity(0.22), blurRadius: 18, spreadRadius: 0),
            ],
          ),
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(color: tone.withOpacity(0.16), shape: BoxShape.circle),
                child: Icon(icon, size: 18, color: tone),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  msg,
                  style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13.5, fontWeight: FontWeight.w600, letterSpacing: 0.2),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// Tests the saved Binance API credentials via the backend's
  /// /api/binance/test-connection route - separate busy/result state of
  /// its own so a test never clobbers unrelated form state.
  Future<void> _testBinanceConnection() async {
    setState(() {
      _isTestingBinanceConnection = true;
      _binanceTestConnectionResult = null;
    });
    final saved = await _save(silent: true);
    if (!saved) {
      setState(() => _isTestingBinanceConnection = false);
      return;
    }
    final result = await _provider.testBinanceConnection();
    if (!mounted) return;
    setState(() {
      _isTestingBinanceConnection = false;
      if (result['ok'] == true) {
        _binanceTestConnectionResult = '✅ Connected - wallet ${result['wallet_usdt'] ?? result['available_usdt']} USDT, available ${result['available_usdt']} USDT';
      } else {
        _binanceTestConnectionResult = '❌ ${result['error'] ?? 'Connection failed'}';
      }
    });
  }

  // --------------------------------------------------------------------- build ----

  // Settings follows the app theme (Dark/Light) like every other screen - it
  // used to force the dark theme, which looked wrong next to the light header
  // and bottom bar in Light mode.
  @override
  Widget build(BuildContext context) => _buildBody(context);

  Widget _appearanceCard(BuildContext context) {
    final p = context.palette;
    final mode = context.select<AppProvider, ThemeMode>((p) => p.themeMode);
    final summaryText = mode == ThemeMode.system
        ? 'System · follows your phone'
        : (mode == ThemeMode.light ? 'Light · Clean White' : 'Dark · Obsidian');
    return SettingsGroup(
      icon: Icons.palette_outlined,
      title: 'Appearance',
      tint: const Color(0xFFEC4899),
      summary: summaryText,
      initiallyExpanded: false,
      children: [
        SizedBox(
          width: double.infinity,
          child: SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.light, label: Text('Light'), icon: Icon(Icons.light_mode_outlined)),
              ButtonSegment(value: ThemeMode.dark, label: Text('Dark'), icon: Icon(Icons.dark_mode_outlined)),
              ButtonSegment(value: ThemeMode.system, label: Text('System'), icon: Icon(Icons.phone_android_outlined)),
            ],
            selected: {mode},
            onSelectionChanged: (sel) => context.read<AppProvider>().setThemeMode(sel.first),
            style: SegmentedButton.styleFrom(
              selectedBackgroundColor: p.accent.withOpacity(0.18),
              selectedForegroundColor: p.accent,
            ),
          ),
        ),
      ],
    );
  }

  Widget _voiceRow(BuildContext context, String title, String subtitle, bool value, ValueChanged<bool>? onChanged) {
    final p = context.palette;
    final t = context.type;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.s),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: t.secondary.copyWith(color: p.textPrimary, fontWeight: FontWeight.w600)),
                const SizedBox(height: 2),
                Text(subtitle, style: t.metadata),
              ],
            ),
          ),
          Switch(
            value: value,
            activeColor: p.accent,
            onChanged: onChanged == null
                ? null
                : (v) {
                    AppHaptics.light();
                    onChanged(v);
                  },
          ),
        ],
      ),
    );
  }

  Widget _voiceCard(BuildContext context) {
    final t = context.type;
    // Rebuild only when one of the 4 sound switches changes - NOT on every
    // 250ms price tick (watch<AppProvider>() rebuilt this whole screen).
    context.select<AppProvider, int>((p) =>
        Object.hash(p.soundEnabled, p.soundEntryOn, p.soundExitOn, p.soundOnlyWhenOpen));
    final pr = context.read<AppProvider>();
    final on = pr.soundEnabled;
    Widget testBtn(String label, IconData icon, TradeSound snd) => Padding(
          padding: const EdgeInsets.only(top: AppSpacing.s),
          child: SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () {
                AppHaptics.light();
                pr.testSound(snd);
              },
              icon: Icon(icon, size: 18),
              label: Text(label),
            ),
          ),
        );
    final onCount = [pr.soundEntryOn, pr.soundExitOn].where((v) => v).length;
    return SettingsGroup(
      icon: on ? Icons.volume_up_rounded : Icons.volume_off_rounded,
      title: 'Sound Alerts',
      tint: AppColors.positive,
      summary: !on ? 'OFF' : 'ON · $onCount of 2 sounds${pr.soundOnlyWhenOpen ? ' · app open only' : ''}',
      initiallyExpanded: false,
      children: [
        Text('Plays a sound when a trade opens, hits target or hits stop loss. Turn OFF for silent background use.',
            style: t.metadata),
        _voiceRow(context, 'Sound alerts', 'Master switch', on, pr.setSoundEnabled),
        _voiceRow(context, 'Order filled sound', 'Plays when a trade opens', pr.soundEntryOn, on ? pr.setSoundEntryOn : null),
        _voiceRow(context, 'Target / Stop loss sound', 'Plays when a trade closes', pr.soundExitOn, on ? pr.setSoundExitOn : null),
        _voiceRow(context, 'Only when app is open', 'No sound while app is in background', pr.soundOnlyWhenOpen,
            on ? pr.setSoundOnlyWhenOpen : null),
        const SizedBox(height: AppSpacing.s),
        testBtn('Test order filled', Icons.volume_up_rounded, TradeSound.orderFilled),
        testBtn('Test target hit', Icons.volume_up_rounded, TradeSound.targetHit),
        testBtn('Test stop loss hit', Icons.volume_up_rounded, TradeSound.stopLossHit),
      ],
    );
  }

  /// Liquid-glass + spatial header: ONE frosted panel over a soft colour wash, with
  /// four clay-style chips (mode, timeframe, max open, schedule). It is the only
  /// blurred widget on the screen, so scrolling stays smooth.
  Widget _glassHeader(AppPalette p, AppText t) {
    final maxOpen = (double.tryParse(_controllers['max_open_trades']!.text.trim()) ?? 0);
    Widget chip(String label, String value, Color c) => Expanded(
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 5, horizontal: 6),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(p.brightness == Brightness.dark ? 0.08 : 0.55),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white.withOpacity(p.brightness == Brightness.dark ? 0.14 : 0.8), width: 0.8),
              boxShadow: [BoxShadow(color: c.withOpacity(0.18), blurRadius: 10, offset: const Offset(0, 4))],
            ),
            child: Column(
              children: [
                Text(value,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: t.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 15, color: c)),
                const SizedBox(height: 2),
                Text(label, style: t.metadata.copyWith(fontSize: 11, color: p.textSecondary)),
              ],
            ),
          ),
        );
    return Container(
      margin: const EdgeInsets.only(bottom: 6),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(18),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [p.accent.withOpacity(0.38), p.purple.withOpacity(0.30), const Color(0xFFEC4899).withOpacity(0.22)],
        ),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(18),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 14, sigmaY: 14),
          child: Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: Colors.white.withOpacity(p.brightness == Brightness.dark ? 0.05 : 0.30),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Colors.white.withOpacity(p.brightness == Brightness.dark ? 0.16 : 0.75), width: 1),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    chip('Mode', _liveTradingEnabled ? 'LIVE' : 'PAPER', _liveTradingEnabled ? p.loss : p.accent),
                    const SizedBox(width: 8),
                    chip('Timeframe', _timeframe, p.purple),
                    const SizedBox(width: 8),
                    chip('Max open', maxOpen == 0 ? 'No limit' : _fmtVal(maxOpen), p.warning),
                    const SizedBox(width: 8),
                    chip('Schedule', _dailyGate ? 'ON' : 'OFF', _dailyGate ? p.profit : p.textSecondary),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final changes = _changes();
    final errors = _errors();
    final dirty = changes.isNotEmpty;
    final cur = _current();

    return Scaffold(
      body: SafeArea(
        child: Stack(
          children: [
            Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, AppSpacing.s),
                  child: Row(
                    children: [
                      Text('Settings', style: t.section.copyWith(fontSize: 22, fontWeight: FontWeight.bold)),
                    ],
                  ),
                ),
                Expanded(
                  child: SingleChildScrollView(
                    padding: EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, dirty ? 120 : AppSpacing.l),
                    child: Column(
                      children: [
                        AnimatedSize(
                          duration: AppMotion.slow,
                          curve: AppMotion.standard,
                          child: _receipt == null ? const SizedBox(width: double.infinity) : _receiptCard(_receipt!),
                        ),
                        if (!_loaded)
                          Container(
                            width: double.infinity,
                            margin: const EdgeInsets.only(bottom: AppSpacing.m),
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: p.warning.withOpacity(0.1),
                              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                            ),
                            child: Text(
                              'Loading settings from the backend... saving is locked until they arrive '
                              '(so nothing gets overwritten with defaults).',
                              style: t.metadata.copyWith(color: p.warning),
                            ),
                          ),
                        _glassHeader(p, t),
                        const SettingsHeading('Trading'),
                        // ---- Section B: Trade Risk Settings ----
                        SettingsGroup(
                          icon: Icons.tune_rounded,
                          title: 'Trade Risk',
                          tint: p.accent,
                          initiallyExpanded: false,
                          summary: '$_timeframe · ${_fmtVal(cur['invest_amount'])} USDT · ${_fmtVal(cur['leverage'])}x · '
                              '${_tpMode == 'universal' ? 'TP ${_fmtVal(cur['scalp_close_roi_pct'])}%' : 'Strategy TP'}',
                          children: [
                            Text('Strategy Timeframe',
                                style: t.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w600)),
                            const SizedBox(height: 6),
                            Text(
                              'Candle size the scanner/strategy runs on for every watchlist symbol. '
                              'Changing this clears cached candle history and re-fetches fresh.',
                              style: t.metadata,
                            ),
                            const SizedBox(height: 10),
                            _timeframeSelector(p, t),
                            Divider(color: p.border, height: 24),
                            _field('Invest Amount (USDT)', 'invest_amount', errors: errors),
                            _field('Leverage', 'leverage', errors: errors),
                            Text('TP Execution Mode',
                                style: t.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w600)),
                            const SizedBox(height: 6),
                            Text(
                              _tpMode == 'strategy'
                                  ? 'Strategy TP (default): follows the Pine Script / SD-level TP1-4 ladder. '
                                      'The moment TP1 is hit, the Stop Loss auto-shifts to entry (breakeven) - '
                                      'the trade can no longer close at a loss from that point on.'
                                  : 'Universal ROI %: ignores the SD-level ladder entirely. The FULL position '
                                      'closes the instant its own ROI% (leverage included) reaches the target '
                                      'below - one flat exit, no partial TPs, no breakeven step.',
                              style: t.metadata,
                            ),
                            const SizedBox(height: 10),
                            _tpModeSelector(p, t),
                            const SizedBox(height: AppSpacing.m),
                            _field(
                              'Universal TP % (auto-close at ROI)',
                              'scalp_close_roi_pct',
                              errors: errors,
                              enabled: _tpMode == 'universal',
                              helper: _tpMode == 'universal'
                                  ? 'Any open trade closes itself the moment ITS OWN ROI reaches this %. '
                                      'Applies to already-open trades too.'
                                  : 'Switch to "Universal ROI %" above to set a target - this field is inactive '
                                      'while Strategy TP mode is selected.',
                            ),
                            if (_tpMode == 'strategy') ...[
                              Divider(color: p.border, height: 24),
                              Text('Trailing stop',
                                  style: t.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w600)),
                              const SizedBox(height: 6),
                              Text(
                                _trailMode == 'step1'
                                    ? '1-step (default): the stop follows one TP behind. TP1 hit: SL to entry. TP2 hit: SL to TP1. '
                                        'TP3 hit: SL to TP2. TP4 still closes the trade.'
                                    : _trailMode == 'step2'
                                        ? '2-step (slower): after TP1 the stop stays where it was. TP2 hit: SL to entry. '
                                            'TP3 hit: SL to TP1. TP4 still closes the trade. More room, but a trade '
                                            'that only touched TP1 can still end at the original SL.'
                                        : 'Off: once TP1 is hit the SL moves to entry, nothing more.',
                                style: t.metadata,
                              ),
                              const SizedBox(height: 10),
                              _trailSelector(p, t),
                            ],
                            Divider(color: p.border, height: 24),
                            _field('Daily Target (USDT)', 'daily_target_usdt', errors: errors),
                            _field('Daily Loss Limit (USDT)', 'daily_loss_limit_usdt', errors: errors),
                          ],
                        ),
                        SettingsGroup(
                          icon: Icons.rule_outlined,
                          title: 'Trade Rules',
                          tint: p.purple,
                          initiallyExpanded: false,
                          summary: 'Max open ${_fmtVal(double.tryParse(_controllers['max_open_trades']!.text.trim()) ?? 0)}'
                              ' · Schedule ${_dailyGate ? 'ON' : 'OFF'}',
                          children: [
                            _field(
                              'Max open trades (0 = no limit)',
                              'max_open_trades',
                              errors: errors,
                              helper: 'The bot never keeps more trades open than this number. '
                                  'Example: 2 means it opens 2 trades and skips new signals until one closes.',
                            ),
                            Divider(color: p.border, height: 24),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text('Daily schedule (IST)', style: TextStyle(color: p.textPrimary)),
                              subtitle: Text(
                                'Bot turns OFF at 1:30 AM. If you switch it ON yourself, it turns OFF again at 5:30 AM. '
                                'No new trades from 5:30 AM to 9:30 AM. It turns ON at 9:30 AM.',
                                style: t.metadata.copyWith(color: p.textMuted),
                              ),
                              activeColor: p.accent,
                              value: _dailyGate,
                              onChanged: (v) => setState(() {
                                _dailyGate = v;
                                _receipt = null;
                              }),
                            ),
                            Divider(color: p.border, height: 24),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text('No SELL on gainers', style: TextStyle(color: p.textPrimary)),
                              subtitle: Text(
                                'A top-10 gainer coin gets no SELL until price crosses SD0 from above to below.',
                                style: t.metadata.copyWith(color: p.textMuted),
                              ),
                              activeColor: p.accent,
                              value: _blockSellGainer,
                              onChanged: (v) => setState(() {
                                _blockSellGainer = v;
                                _receipt = null;
                              }),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text('No BUY on losers', style: TextStyle(color: p.textPrimary)),
                              subtitle: Text(
                                'A top-10 loser coin gets no BUY until price crosses SD0 from below to above.',
                                style: t.metadata.copyWith(color: p.textMuted),
                              ),
                              activeColor: p.accent,
                              value: _blockBuyLoser,
                              onChanged: (v) => setState(() {
                                _blockBuyLoser = v;
                                _receipt = null;
                              }),
                            ),
                          ],
                        ),
                        const SettingsHeading('Account'),
                        // ---- Section C: Binance Futures API Configuration ----
                        SettingsGroup(
                          icon: Icons.vpn_key_outlined,
                          title: 'Binance Futures API',
                          tint: p.warning,
                          initiallyExpanded: false,
                          summary: 'Binance · Live ${_liveTradingEnabled ? 'ON' : 'OFF'}',
                          children: [
                            // Static locked indicator - OWL Terminal is hard-wired to Binance
                            // Futures only (the old KuCoin/Binance exchange switcher and its
                            // /api/exchange/switch round trip were removed), so this is a
                            // read-only status chip, not a control.
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: 10),
                              margin: const EdgeInsets.only(bottom: 4),
                              decoration: BoxDecoration(
                                color: p.accent.withOpacity(0.1),
                                borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                                border: Border.all(color: p.accent.withOpacity(0.35)),
                              ),
                              child: Row(
                                children: [
                                  Icon(Icons.lock_outline, color: p.accent, size: 16),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      'Binance Futures (Locked)',
                                      style: t.secondary.copyWith(color: p.accent, fontWeight: FontWeight.bold),
                                    ),
                                  ),
                                  Icon(Icons.check_circle, color: p.accent.withOpacity(0.9), size: 18),
                                ],
                              ),
                            ),
                            const SizedBox(height: 10),
                            Text(
                              'OWL Terminal trades exclusively on Binance Futures - data feed, '
                              'watchlist and live order routing all run on this exchange only.',
                              style: t.metadata,
                            ),
                            const SizedBox(height: 6),
                            Text(
                              'All P&L numbers in the app are after the exchange fee (paper mode too). '
                              'TODAY = trades already closed today; OPEN is live and can still change.',
                              style: t.metadata,
                            ),
                            Divider(color: p.border, height: 24),
                            Container(
                              padding: const EdgeInsets.all(10),
                              margin: const EdgeInsets.only(bottom: AppSpacing.m),
                              decoration: BoxDecoration(
                                color: p.warning.withOpacity(0.1),
                                borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                              ),
                              child: Text(
                                '⚠️ Turning this ON places REAL orders with REAL money on '
                                'Binance Futures, EXCLUSIVELY - paper trading pauses '
                                'completely while this is ON, and resumes the moment it\'s '
                                'turned back OFF. Test the connection first, start with the '
                                'smallest size, and confirm one trade manually on the '
                                'exchange before trusting it.',
                                style: t.metadata.copyWith(color: p.warning),
                              ),
                            ),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text('Live Trading', style: TextStyle(color: p.textPrimary)),
                              subtitle: Text(
                                _liveTradingEnabled
                                    ? 'ON - real orders only, paper is silent'
                                    : 'OFF - paper trading only',
                                style: t.metadata.copyWith(color: _liveTradingEnabled ? p.warning : p.textMuted),
                              ),
                              activeColor: p.accent,
                              value: _liveTradingEnabled,
                              onChanged: (v) => _onLiveTradingToggled(v),
                            ),
                            const SizedBox(height: 4),
                            Text('BINANCE CREDENTIALS',
                                style: t.metadata.copyWith(letterSpacing: 1)),
                            const SizedBox(height: 4),
                            _field('Binance API Key', 'binance_api_key', isText: true, errors: errors),
                            _field('Binance API Secret', 'binance_api_secret', isText: true, errors: errors),
                            Padding(
                              padding: const EdgeInsets.only(bottom: AppSpacing.m),
                              child: OutlinedButton(
                                onPressed: _isTestingBinanceConnection ? null : _testBinanceConnection,
                                style: OutlinedButton.styleFrom(
                                  minimumSize: const Size(double.infinity, 40),
                                  side: BorderSide(color: p.accent),
                                ),
                                child: Text(
                                  _isTestingBinanceConnection ? 'Testing...' : 'Test Binance Connection',
                                  style: TextStyle(color: p.accent),
                                ),
                              ),
                            ),
                            if (_binanceTestConnectionResult != null)
                              Padding(
                                padding: const EdgeInsets.only(bottom: AppSpacing.m),
                                child: Text(
                                  _binanceTestConnectionResult!,
                                  style: AppTypography.secondaryData.copyWith(color: _binanceTestConnectionResult!.startsWith('✅') ? p.positive : p.negative, fontSize: 13),
                                ),
                              ),
                            Divider(color: p.border, height: 24),
                            Text('Position Size Mode', style: t.secondary.copyWith(color: p.textSecondary)),
                            const SizedBox(height: 4),
                            Row(
                              children: [
                                Expanded(child: _radio(p, t, 'Fixed USDT', 'fixed', _positionSizeMode, (v) => _positionSizeMode = v)),
                                Expanded(
                                  child: _radio(p, t, '% of Balance', 'percent_balance', _positionSizeMode, (v) => _positionSizeMode = v),
                                ),
                              ],
                            ),
                            _field(
                              _positionSizeMode == 'fixed' ? 'Position Size (USDT)' : 'Position Size (% of balance)',
                              'position_size_value',
                              errors: errors,
                            ),
                            _field('Live Leverage', 'live_leverage', errors: errors),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.s),
                        const SettingsHeading('Alerts & AI'),
                        _voiceCard(context),
                        // ---- Section D: System Preferences (Telegram + AI Assistant) ----
                        SettingsGroup(
                          icon: Icons.smart_toy_outlined,
                          title: 'AI & Telegram',
                          tint: p.purple,
                          initiallyExpanded: false,
                          summary: 'AI ${_aiEnabled ? 'ON' : 'OFF'} · Telegram '
                              '${(cur['telegram_bot_token'] as String? ?? '').isEmpty ? 'not linked' : 'linked'}',
                          children: [
                            Text('TELEGRAM', style: t.metadata.copyWith(letterSpacing: 1)),
                            const SizedBox(height: 4),
                            _field('Bot Token', 'telegram_bot_token', isText: true, errors: errors),
                            _field('Chat ID', 'telegram_chat_id', isText: true, errors: errors),
                            Divider(color: p.border, height: 24),
                            Text('AI ASSISTANT', style: t.metadata.copyWith(letterSpacing: 1)),
                            const SizedBox(height: 4),
                            SwitchListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text('Enable AI Assistant', style: TextStyle(color: p.textPrimary)),
                              subtitle: Text(
                                _aiEnabled ? 'ON' : 'OFF',
                                style: t.metadata.copyWith(color: _aiEnabled ? p.accent : p.textMuted),
                              ),
                              activeColor: p.accent,
                              value: _aiEnabled,
                              onChanged: (v) => setState(() {
                                _aiEnabled = v;
                                _receipt = null;
                              }),
                            ),
                            const AiKeysCard(),
                            const SizedBox(height: 10),
                            Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: OutlinedButton(
                                onPressed: () async {
                                  final ok = await _save(silent: true);
                                  if (ok && mounted) {
                                    Navigator.of(context).push(
                                      OwlRoute(builder: (_) => const AiAssistantScreen()),
                                    );
                                  }
                                },
                                style: OutlinedButton.styleFrom(
                                  minimumSize: const Size(double.infinity, 40),
                                  side: BorderSide(color: p.accent),
                                ),
                                child: Text('Open Chat', style: TextStyle(color: p.accent)),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.s),
                        const SettingsHeading('App'),
                        _appearanceCard(context),
                        const ReportDownloadCard(),
                        // ---- Section A: Backend Connection ----
                        SettingsGroup(
                          icon: Icons.dns_outlined,
                          title: 'Backend Connection',
                          tint: p.textSecondary,
                          summary: _provider.baseUrl,
                          initiallyExpanded: false,
                          children: [
                            Padding(
                              padding: const EdgeInsets.only(bottom: AppSpacing.m),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(
                                    'Backend URL (e.g. http://95.135.254.130:8000)',
                                    style: t.secondary.copyWith(color: p.textSecondary),
                                  ),
                                  const SizedBox(height: 4),
                                  TextField(
                                    controller: _backendUrlController,
                                    style: TextStyle(color: p.textPrimary),
                                    keyboardType: TextInputType.url,
                                    decoration: _inputDecoration(p),
                                  ),
                                ],
                              ),
                            ),
                            OWLButtonFull(
                              label: _isSavingBackend ? 'Connecting...' : 'Save & Reconnect',
                              onPressed: _isSavingBackend ? null : _saveBackendUrl,
                            ),
                          ],
                        ),
                        _BackupTile(),
                        const SizedBox(height: AppSpacing.xxl),
                        OWLButtonFull(
                          label: _isSaving ? 'Saving...' : '💾 Save Settings',
                          onPressed: (_isSaving || !_loaded) ? null : () => _save(),
                          height: 50,
                        ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
            // ---- floating "unsaved changes" bar ----
            Positioned(
              left: 12,
              right: 12,
              bottom: 10,
              child: AnimatedSlide(
                duration: AppMotion.base,
                curve: AppMotion.standard,
                offset: dirty ? Offset.zero : const Offset(0, 1.6),
                child: AnimatedOpacity(
                  duration: AppMotion.base,
                  opacity: dirty ? 1 : 0,
                  child: IgnorePointer(ignoring: !dirty, child: _unsavedBar(p, t, changes, errors)),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _unsavedBar(AppPalette p, AppText t, List<_Change> changes, Map<String, String> errors) {
    final n = changes.length;
    return Container(
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.warning.withOpacity(0.7)),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.35), blurRadius: 14, offset: const Offset(0, 4))],
      ),
      padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_showDiff)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 190),
                child: SingleChildScrollView(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final c in changes) _diffRow(p, t, c),
                    ],
                  ),
                ),
              ),
            ),
          Row(
            children: [
              Expanded(
                child: InkWell(
                  onTap: () => setState(() => _showDiff = !_showDiff),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(
                      children: [
                        Container(
                          width: 8,
                          height: 8,
                          decoration: BoxDecoration(color: p.warning, shape: BoxShape.circle),
                        ),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(
                            errors.isNotEmpty
                                ? '$n unsaved · ${errors.length} field(s) need fixing'
                                : '$n unsaved change${n == 1 ? '' : 's'}',
                            style: t.primary.copyWith(fontWeight: FontWeight.w600),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        Icon(_showDiff ? Icons.expand_more : Icons.expand_less, color: p.textSecondary, size: 18),
                      ],
                    ),
                  ),
                ),
              ),
              TextButton(onPressed: _isSaving ? null : _discard, child: const Text('Discard')),
              const SizedBox(width: 4),
              ElevatedButton(
                onPressed: _isSaving ? null : () => _save(),
                style: ElevatedButton.styleFrom(
                  backgroundColor: p.accent,
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusSmall)),
                ),
                child: Text(_isSaving ? '...' : 'Save', style: AppTypography.primaryData.copyWith(color: Colors.white, fontWeight: FontWeight.bold)),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _diffRow(AppPalette p, AppText t, _Change c) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            flex: 5,
            child: Text(c.label, style: t.metadata.copyWith(color: p.textSecondary)),
          ),
          Expanded(
            flex: 6,
            child: Text(
              c.secret ? 'changed' : '${_fmtVal(c.oldRaw)}  →  ${_fmtVal(c.newRaw)}',
              style: t.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }

  /// The "Saved" receipt: what changed, when each change kicks in, and
  /// whether the backend really holds the new value now.
  Widget _receiptCard(_Receipt r) {
    return Builder(builder: (context) {
      final p = context.palette;
      final t = context.type;
      final hh = r.at.hour.toString().padLeft(2, '0');
      final mm = r.at.minute.toString().padLeft(2, '0');
      final ss = r.at.second.toString().padLeft(2, '0');
      final allOk = r.confirmed.values.every((v) => v);
      final n = r.changes.length;
      final statusColor = allOk ? p.positive : p.warning;
      return Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: AppSpacing.l),
        padding: const EdgeInsets.fromLTRB(14, 12, 8, 10),
        decoration: BoxDecoration(
          color: statusColor.withOpacity(0.08),
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
          border: Border.all(color: statusColor.withOpacity(0.6)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(allOk ? Icons.verified : Icons.warning_amber_rounded, color: statusColor, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    allOk
                        ? 'Saved & confirmed by backend · $hh:$mm:$ss'
                        : 'Saved, but backend value differs · $hh:$mm:$ss',
                    style: AppTypography.secondaryData.copyWith(color: statusColor, fontSize: 13, fontWeight: FontWeight.w700),
                  ),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: Icon(Icons.close, size: 18, color: p.textSecondary),
                  onPressed: () => setState(() => _receipt = null),
                ),
              ],
            ),
            const SizedBox(height: 4),
            for (final c in r.changes)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 3),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      flex: 5,
                      child: Text(c.label, style: t.metadata.copyWith(color: p.textSecondary, fontSize: 12)),
                    ),
                    Expanded(
                      flex: 6,
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            c.secret ? 'updated' : '${_fmtVal(c.oldRaw)}  →  ${_fmtVal(c.newRaw)}',
                            style: t.primary.copyWith(fontSize: 12, fontWeight: FontWeight.w700),
                          ),
                          Text(
                            '${r.confirmed[c.key] == true ? '✓' : '⚠'} ${c.scope}',
                            style: AppTypography.metadata.copyWith(color: c.scope == _scopeRestart ? p.warning : p.textMuted, fontSize: 10.5),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            Align(
              alignment: Alignment.centerRight,
              child: TextButton.icon(
                onPressed: _isSaving ? null : _undo,
                icon: Icon(Icons.undo, size: 16, color: p.accent),
                label: Text('Undo $n change${n == 1 ? '' : 's'}', style: AppTypography.secondaryData.copyWith(color: p.accent, fontSize: 12)),
              ),
            ),
          ],
        ),
      );
    });
  }

  // ------------------------------------------------------------------- widgets ----

  InputDecoration _inputDecoration(AppPalette p, {String? errorText}) {
    return InputDecoration(
      filled: true,
      fillColor: p.surfacePrimary,
      errorText: errorText,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
        borderSide: BorderSide.none,
      ),
      contentPadding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: 10),
    );
  }

  Widget _radio(AppPalette p, AppText t, String title, String value, String group, void Function(String) set) {
    return RadioListTile<String>(
      contentPadding: EdgeInsets.zero,
      title: Text(title, style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13)),
      value: value,
      groupValue: group,
      activeColor: p.accent,
      onChanged: (v) => setState(() {
        set(v ?? value);
        _receipt = null;
      }),
    );
  }

  /// Sleek segmented selector for the Strategy Timeframe (1m/3m/5m/15m/1h) -
  /// a row of equal-width pill buttons, active one filled with the accent
  /// color. Local state only (_timeframe) - not saved until the screen's
  /// normal Save button is pressed, same as every other field here.
  Widget _timeframeSelector(AppPalette p, AppText t) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Row(
        children: _timeframeOptions.map((tf) {
          final selected = tf == _timeframe;
          return Expanded(
            child: GestureDetector(
              onTap: () => setState(() {
                _timeframe = tf;
                _receipt = null;
              }),
              child: AnimatedContainer(
                duration: AppMotion.fast,
                margin: const EdgeInsets.symmetric(horizontal: 2),
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(
                  color: selected ? p.accent : Colors.transparent,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2),
                ),
                alignment: Alignment.center,
                child: Text(
                  tf,
                  style: AppTypography.secondaryData.copyWith(
                    color: selected ? Colors.white : p.textSecondary,
                    fontWeight: selected ? FontWeight.bold : FontWeight.normal,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  /// Trailing stop selector (Off / 1-step / 2-step) - same pill style as the timeframe
  /// selector. Local state only until the normal Save button is pressed.
  Widget _trailSelector(AppPalette p, AppText t) {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Row(
        children: _trailOptions.map((m) {
          final selected = m == _trailMode;
          return Expanded(
            child: GestureDetector(
              onTap: () => setState(() {
                _trailMode = m;
                _receipt = null;
              }),
              child: AnimatedContainer(
                duration: AppMotion.fast,
                margin: const EdgeInsets.symmetric(horizontal: 2),
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(
                  color: selected ? p.accent : Colors.transparent,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2),
                ),
                alignment: Alignment.center,
                child: Text(
                  _trailTitles[m] ?? m,
                  style: AppTypography.secondaryData.copyWith(
                    color: selected ? Colors.white : p.textSecondary,
                    fontWeight: selected ? FontWeight.bold : FontWeight.normal,
                    fontSize: 13,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  /// TP EXECUTION MODE segmented toggle - 'Strategy TP' (default: follows
  /// the Pine Script / SD-level TP1-4 ladder, with an automatic
  /// breakeven-shift on TP1 - see paper_trader.py) vs 'Universal ROI %'
  /// (flat full-close the instant the position's own ROI% hits the number
  /// typed below). Switching modes only flips whether scalp_close_roi_pct
  /// is 0 or a real value - the backend already branches on that exact
  /// condition (0 = OFF -> falls through to strategy TP logic).
  Widget _tpModeSelector(AppPalette p, AppText t) {
    const options = <MapEntry<String, String>>[
      MapEntry('strategy', 'Strategy TP'),
      MapEntry('universal', 'Universal ROI %'),
    ];
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
      ),
      child: Row(
        children: options.map((opt) {
          final selected = opt.key == _tpMode;
          return Expanded(
            child: GestureDetector(
              onTap: () {
                if (!_loaded || opt.key == _tpMode) return;
                setState(() {
                  final ctrl = _controllers['scalp_close_roi_pct']!;
                  if (opt.key == 'strategy') {
                    // Remember whatever the user had typed so switching
                    // back to Universal restores it instead of a blank 0.
                    final cur = double.tryParse(ctrl.text.trim().replaceAll(',', '.'));
                    if (cur != null && cur > 0) _lastUniversalRoi = cur;
                    ctrl.text = _fmtVal(0.0);
                  } else {
                    ctrl.text = _fmtVal(_lastUniversalRoi > 0 ? _lastUniversalRoi : 25.0);
                  }
                  _tpMode = opt.key;
                  _receipt = null;
                });
              },
              child: AnimatedContainer(
                duration: AppMotion.fast,
                margin: const EdgeInsets.symmetric(horizontal: 2),
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(
                  color: selected ? p.accent : Colors.transparent,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2),
                ),
                alignment: Alignment.center,
                child: Text(
                  opt.value,
                  textAlign: TextAlign.center,
                  style: AppTypography.secondaryData.copyWith(
                    color: selected ? Colors.white : p.textSecondary,
                    fontWeight: selected ? FontWeight.bold : FontWeight.normal,
                    fontSize: 12,
                  ),
                ),
              ),
            ),
          );
        }).toList(),
      ),
    );
  }

  /// PHASE 2 - instant dispatch: flipping the Live Trading switch fires
  /// `POST /api/settings` right away (via the provider) instead of waiting
  /// for the screen's normal "Save Settings" button, so the backend's
  /// dispatcher starts/stops routing signals to the real exchange on the
  /// very next signal. Turning it ON still asks for confirmation first
  /// (real money); turning it OFF dispatches immediately with no dialog.
  Future<void> _onLiveTradingToggled(bool v) async {
    if (v) {
      final p = context.palette;
      final ok = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          backgroundColor: p.surfaceElevated,
          title: Text('Please confirm', style: TextStyle(color: p.textPrimary)),
          content: Text(
            '⚠️ Live trading will be turned ON now - real orders with real money, '
            'exclusively. Paper trading will stay silent until this is turned back OFF.',
            style: AppTypography.secondaryData.copyWith(color: p.warning, fontSize: 13),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: Text('Turn ON', style: TextStyle(color: p.accent)),
            ),
          ],
        ),
      );
      if (ok != true) return;
    }
    setState(() => _liveTradingEnabled = v); // optimistic - reverted below on failure
    final success = await _provider.setLiveTradingEnabledImmediate(v);
    if (!mounted) return;
    setState(() {
      _liveTradingEnabled = success ? v : !v;
      _baseline['live_trading_enabled'] = _liveTradingEnabled;
      _receipt = null;
    });
    _snack(
      success
          ? (v ? 'Live trading is ON - real orders only now.' : 'Live trading is OFF - paper trading resumed.')
          : 'Could not reach backend - live trading NOT changed.',
      bad: !success,
    );
  }

  /// Thin wrapper around SettingsInputField that plugs in this screen's
  /// controller/error/changed-dot/helper for one settings key - same
  /// behaviour the old `_buildTextField` provided, just built on the
  /// shared widget instead of a bespoke TextField.
  Widget _field(
    String label,
    String key, {
    bool isText = false,
    required Map<String, String> errors,
    String? helper,
    bool enabled = true,
  }) {
    final changed = _loaded &&
        (() {
          final cur = _current()[key];
          return cur != null && !_same(cur, _baseline[key]);
        })();
    return SettingsInputField(
      label: label,
      controller: _controllers[key]!,
      enabled: _loaded && enabled,
      keyboardType: isText ? TextInputType.text : const TextInputType.numberWithOptions(decimal: true),
      obscureText: isText && _secretKeys.contains(key),
      errorText: errors[key],
      helperText: helper,
      changed: changed,
    );
  }
}

/// Full-width accent action button - local to Settings so this file doesn't
/// need to pull in OWLButton's isLoading affordance for these two spots.
class OWLButtonFull extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final double height;
  const OWLButtonFull({super.key, required this.label, required this.onPressed, this.height = 44});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ElevatedButton(
      onPressed: onPressed,
      style: ElevatedButton.styleFrom(
        backgroundColor: p.accent,
        minimumSize: Size(double.infinity, height),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
      ),
      child: Text(label, style: AppTypography.primaryData.copyWith(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15)),
    );
  }
}


/// "Backup history" - zips trade / alert / AI history on the backend and sends
/// it to the Telegram chat, so a wiped phone never loses the learning data.
/// (API keys / settings.json are NOT part of the backup.)
class _BackupTile extends StatefulWidget {
  @override
  State<_BackupTile> createState() => _BackupTileState();
}

class _BackupTileState extends State<_BackupTile> {
  bool _busy = false;

  Future<void> _run() async {
    if (_busy) return;
    AppHaptics.light();
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().exportBackup();
    if (!mounted) return;
    setState(() => _busy = false);
    r.ok ? AppHaptics.medium() : AppHaptics.heavy();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(r.message), backgroundColor: r.ok ? context.palette.profit : context.palette.loss),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.border, width: 1),
      ),
      child: Row(
        children: [
          Container(
            width: 38,
            height: 38,
            decoration: BoxDecoration(
              color: p.accent.withOpacity(0.12),
              borderRadius: BorderRadius.circular(11),
            ),
            child: Icon(Icons.cloud_upload_outlined, color: p.accent, size: 20),
          ),
          const SizedBox(width: AppSpacing.m),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Backup history',
                    style: AppTypography.primaryData.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 15)),
                const SizedBox(height: 2),
                Text('Trades, alerts aur AI history Telegram pe zip me bhejo (API keys nahi jati).',
                    style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 12)),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.s),
          _busy
              ? SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2, color: p.accent))
              : OutlinedButton(
                  onPressed: _run,
                  style: OutlinedButton.styleFrom(side: BorderSide(color: p.accent)),
                  child: Text('Send', style: TextStyle(color: p.accent)),
                ),
        ],
      ),
    );
  }
}
