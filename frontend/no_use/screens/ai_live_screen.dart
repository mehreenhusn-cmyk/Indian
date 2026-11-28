import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// STAGE 2 controls: the AI trades its OWN Binance account (its own API key, never the bot's). Everything here is OFF by default and
/// every restart of the backend switches it OFF again. Order of use: 1) key + connection check, 2) limits, 3) type the confirm text.
class AiLiveScreen extends StatefulWidget {
  const AiLiveScreen({super.key});

  @override
  State<AiLiveScreen> createState() => _AiLiveScreenState();
}

class _AiLiveScreenState extends State<AiLiveScreen> {
  Map<String, dynamic>? _d;
  bool _busy = false;
  bool _filled = false;
  String _msg = '';
  Timer? _timer;
  final _key = TextEditingController();
  final _secret = TextEditingController();
  final _margin = TextEditingController();
  final _maxOpen = TextEditingController();
  final _lossCap = TextEditingController();
  final _maxLev = TextEditingController();
  final _coin = TextEditingController();
  final _coinMargin = TextEditingController();
  final _confirm = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) {
      if (!_busy) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    for (final c in [_key, _secret, _margin, _maxOpen, _lossCap, _maxLev, _coin, _coinMargin, _confirm]) {
      c.dispose();
    }
    super.dispose();
  }

  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List _l(dynamic v) => v is List ? v : const [];
  static double _n(dynamic v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);
  static String _f(double v, [int d = 2]) => v.toStringAsFixed(d);

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchAiLive();
    if (!mounted) return;
    setState(() {
      _d = r ?? _d;
      if (r != null && !_filled) {
        final cfg = _m(_m(r['guard'])['cfg']);
        _margin.text = _n(cfg['margin_per_trade']) > 0 ? _f(_n(cfg['margin_per_trade'])) : '';
        _maxOpen.text = '${_n(cfg['max_open']).round()}';
        _lossCap.text = _n(cfg['daily_loss_cap']) > 0 ? _f(_n(cfg['daily_loss_cap'])) : '';
        _maxLev.text = '${_n(cfg['max_leverage']).round()}';
        _filled = true;
      }
    });
  }

  /// Runs one action, shows its result line, then refreshes the numbers.
  Future<void> _act(Future<String> Function() go) async {
    setState(() {
      _busy = true;
      _msg = '';
    });
    String m;
    try {
      m = await go();
    } catch (e) {
      m = 'Something went wrong: $e';
    }
    if (!mounted) return;
    setState(() {
      _busy = false;
      _msg = m;
    });
    _load();
  }

  Future<bool> _ask(String title, String body, String yes) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(title),
        content: Text(body),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: Text(yes)),
        ],
      ),
    );
    return ok == true;
  }

  void _saveKeys() => _act(() async {
        final k = _key.text.trim();
        final s = _secret.text.trim();
        if (k.isEmpty || s.isEmpty) return 'Paste both the API key and the secret.';
        final r = await context.read<AppProvider>().postAiLive('keys', {'key': k, 'secret': s});
        if (r == null) return 'No answer from the backend. Try again.';
        if (r['ok'] == true) {
          _key.clear();
          _secret.clear();
          return 'Key saved. Connection check passed.';
        }
        return 'Not accepted: ${r['error'] ?? 'unknown reason'}';
      });

  void _check() => _act(() async {
        final r = await context.read<AppProvider>().postAiLive('check');
        if (r == null) return 'No answer from the backend. Try again.';
        return r['ok'] == true ? 'Connection check passed.' : 'Check failed: ${r['why'] ?? r['error'] ?? 'unknown'}';
      });

  void _clearKey() async {
    if (!await _ask('Remove the AI key?', 'Real trading is switched OFF and the key is deleted from the phone. Open real trades keep their stop on Binance.', 'Remove')) return;
    _act(() async {
      final r = await context.read<AppProvider>().postAiLive('keys/clear');
      return r != null && r['ok'] == true ? 'Key removed.' : 'Could not remove the key.';
    });
  }

  void _saveLimits() => _act(() async {
        double? v(TextEditingController c) => c.text.trim().isEmpty ? 0.0 : double.tryParse(c.text.trim());
        final a = v(_margin), b = v(_maxOpen), c = v(_lossCap), d = v(_maxLev);
        if (a == null || b == null || c == null || d == null) return 'Limits must be numbers.';
        final r = await context.read<AppProvider>().postAiLive('config', {'margin_per_trade': a, 'max_open': b, 'daily_loss_cap': c, 'max_leverage': d});
        return r != null && r['ok'] == true ? 'Limits saved.' : 'Limits not saved: ${r?['error'] ?? 'no answer'}';
      });

  void _saveCoinCap() => _act(() async {
        final sym = _coin.text.trim().toUpperCase();
        final m = _coinMargin.text.trim().isEmpty ? 0.0 : double.tryParse(_coinMargin.text.trim());
        if (sym.isEmpty || m == null) return 'Type a coin like ABCUSDT and a margin (0 removes the cap).';
        final r = await context.read<AppProvider>().postAiLive('config', {'coin_cap': {'sym': sym, 'margin': m}});
        if (r != null && r['ok'] == true) {
          _coin.clear();
          _coinMargin.clear();
          return m == 0 ? 'Cap for $sym removed.' : 'Real trades on $sym will use at most ${_f(m)} USDT margin.';
        }
        return 'Cap not saved (the coin must look like BTCUSDT, the margin must be a number).';
      });

  void _enable() => _act(() async {
        final r = await context.read<AppProvider>().postAiLive('enable', {'confirm': _confirm.text.trim()});
        if (r == null) return 'No answer from the backend. Try again.';
        if (r['ok'] == true) {
          _confirm.clear();
          return 'Real trading is ON. The AI now copies its own decisions to its Binance account.';
        }
        return '${r['why'] ?? 'Not switched on.'}';
      });

  void _disable() => _act(() async {
        final r = await context.read<AppProvider>().postAiLive('disable');
        return r != null && r['ok'] == true ? 'Real trading is OFF. Trades already open stay protected.' : 'No answer. Try again.';
      });

  void _reset() => _act(() async {
        final r = await context.read<AppProvider>().postAiLive('reset');
        return r != null && r['ok'] == true ? 'Halt cleared. Real trading stays OFF until you switch it on again.' : 'No answer. Try again.';
      });

  void _panic() async {
    if (!await _ask('PANIC: close everything?', 'This halts real trading, cancels every stop and closes every open position on the AI account at market price. It does not touch the bot.', 'CLOSE ALL')) return;
    _act(() async {
      final r = await context.read<AppProvider>().postAiLive('panic');
      if (r == null) return 'No answer from the backend. Open the Binance app and check the AI account NOW.';
      return r['ok'] == true ? 'PANIC done: ${r['closed'] is List ? (r['closed'] as List).length : 0} position(s) closed.' : 'PANIC did not fully finish: ${r['error'] ?? r['why'] ?? 'check the Binance app now'}';
    });
  }

  Widget _card(AppPalette p, List<Widget> kids, {Color? edge}) => Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: edge ?? p.border, width: 0.8),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: kids),
      );

  Widget _title(AppPalette p, String s) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Text(s, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)),
      );

  Widget _text(AppPalette p, String s, {bool bold = false, Color? c}) =>
      Text(s, style: TextStyle(fontSize: 12.5, height: 1.4, fontWeight: bold ? FontWeight.w700 : FontWeight.w500, color: c ?? p.textPrimary));

  Widget _field(TextEditingController c, String label, {bool secret = false, bool number = false}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: TextField(
          controller: c,
          obscureText: secret,
          autocorrect: false,
          enableSuggestions: !secret,
          keyboardType: number ? const TextInputType.numberWithOptions(decimal: true) : TextInputType.text,
          decoration: InputDecoration(isDense: true, labelText: label, border: const OutlineInputBorder()),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    final g = _m(d?['guard']);
    final cfg = _m(g['cfg']);
    final on = g['enabled'] == true;
    final halted = '${g['halted'] ?? ''}'.isNotEmpty;
    final hasKey = _m(d?['key'])['has'] == true;
    final mask = '${_m(d?['key'])['mask'] ?? ''}';
    final today = _m(d?['today']);
    final slip = _m(d?['slip']);
    final caps = _m(g['coin_caps']);
    final open = _l(d?['open']);
    final closed = _l(d?['closed']);
    final events = _l(d?['events']);
    final unknown = _l(d?['unknown']);
    final confirmText = '${d?['confirm_text'] ?? 'ENABLE REAL TRADING'}';
    final pnl = _n(today['pnl']);
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(title: const Text('AI real trading'), backgroundColor: p.bg, elevation: 0),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _load,
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                children: [
                  _card(
                    p,
                    [
                      _title(p, 'STATUS'),
                      Text(halted ? 'HALTED' : on ? 'ON' : 'OFF',
                          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w900, color: halted ? p.loss : on ? p.profit : p.textMuted)),
                      if (halted) ...[
                        const SizedBox(height: 4),
                        _text(p, '${g['halted']}', bold: true, c: p.loss),
                        const SizedBox(height: 6),
                        _text(p, 'Look at the AI account in Binance first. Then clear the halt. Real trading stays OFF until you switch it on again.'),
                        const SizedBox(height: 6),
                        OutlinedButton(onPressed: _busy ? null : _reset, child: const Text('I checked it, clear the halt')),
                      ],
                      const SizedBox(height: 8),
                      Row(children: [
                        Expanded(child: _kv(p, 'Real P&L today (after fees)', '${pnl >= 0 ? '+' : ''}${_f(pnl)} USDT', pnl >= 0 ? p.profit : p.loss)),
                        Expanded(child: _kv(p, 'Free balance', d['balance'] == null ? '-' : '${_f(_n(d['balance']))} USDT', p.textPrimary)),
                      ]),
                      const SizedBox(height: 6),
                      Row(children: [
                        Expanded(child: _kv(p, 'Open real trades', '${open.length}', p.textPrimary)),
                        Expanded(child: _kv(p, 'Open P&L', '${_f(_n(d['upnl']))} USDT', _n(d['upnl']) >= 0 ? p.profit : p.loss)),
                      ]),
                      if (_n(slip['n']) > 0) ...[
                        const SizedBox(height: 6),
                        _text(p,
                            'Real vs paper entry: real fills were ${_n(slip['avg_pct']) > 0 ? 'worse' : 'better'} by ${_f(_n(slip['avg_pct']).abs(), 3)}% on average '
                            '(worst ${_f(_n(slip['worst_pct']), 3)}%, ${_n(slip['n']).round()} trades). This is the gap between the paper P&L and the real P&L.'),
                      ],
                      if (unknown.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        _text(p, 'Positions on the AI account the app does not know: ${unknown.join(', ')}. Check Binance.', bold: true, c: p.loss),
                      ],
                    ],
                    edge: halted ? p.loss : null,
                  ),
                  if (_msg.isNotEmpty) _card(p, [_text(p, _msg, bold: true)]),
                  _card(p, [
                    _title(p, '1. THE AI\'S OWN BINANCE KEY'),
                    _text(p,
                        'Use a separate Binance account or sub-account only for the AI. Never the bot\'s key. Turn withdrawals OFF, allow Futures only, and set the account to One-way mode (not Hedge).'),
                    const SizedBox(height: 8),
                    if (hasKey) ...[
                      _text(p, 'Key saved: $mask', bold: true),
                      const SizedBox(height: 6),
                      Row(children: [
                        OutlinedButton(onPressed: _busy ? null : _check, child: const Text('Check connection')),
                        const SizedBox(width: 8),
                        TextButton(onPressed: _busy ? null : _clearKey, child: const Text('Remove key')),
                      ]),
                      const SizedBox(height: 6),
                      _text(p, 'To replace it, paste a new key below.'),
                      const SizedBox(height: 6),
                    ],
                    _field(_key, 'API key'),
                    _field(_secret, 'API secret', secret: true),
                    FilledButton(onPressed: _busy ? null : _saveKeys, child: Text(_busy ? 'Working...' : 'Save key and check')),
                  ]),
                  _card(p, [
                    _title(p, '2. LIMITS (all three must be set before it can start)'),
                    _field(_margin, 'Margin per trade (USDT)', number: true),
                    _field(_lossCap, 'Daily loss cap (USDT). Day = 5:30 AM to 5:30 AM IST', number: true),
                    _field(_maxOpen, 'Max open real trades', number: true),
                    _field(_maxLev, 'Max leverage (the AI never goes above it)', number: true),
                    OutlinedButton(onPressed: _busy ? null : _saveLimits, child: const Text('Save limits')),
                    const SizedBox(height: 12),
                    _text(p, 'Smaller size for one coin (thin or jumpy coins). It can only lower the margin, never raise it.', bold: true),
                    if (caps.isNotEmpty) ...[
                      const SizedBox(height: 4),
                      for (final e in caps.entries) _text(p, '${e.key}: max ${_f(_n(e.value))} USDT per trade'),
                    ],
                    const SizedBox(height: 6),
                    Row(children: [
                      Expanded(flex: 3, child: _field(_coin, 'Coin, e.g. ABCUSDT')),
                      const SizedBox(width: 8),
                      Expanded(flex: 2, child: _field(_coinMargin, 'Margin', number: true)),
                    ]),
                    OutlinedButton(onPressed: _busy ? null : _saveCoinCap, child: const Text('Set coin cap (0 removes)')),
                  ]),
                  _card(p, [
                    _title(p, '3. SWITCH'),
                    if (!on) ...[
                      _text(p,
                          'First run: use the coin minimum, one trade, and watch it on Binance. The stop order format was taken from Binance\'s documents and has not been tried on a live account yet.'),
                      const SizedBox(height: 8),
                      _field(_confirm, 'Type exactly: $confirmText'),
                      FilledButton(
                        style: FilledButton.styleFrom(backgroundColor: p.loss),
                        onPressed: (_busy || !hasKey || halted) ? null : _enable,
                        child: const Text('Switch real trading ON'),
                      ),
                      if (!hasKey) _text(p, 'Save a key first.', c: p.textMuted),
                    ] else ...[
                      _text(p, 'The AI is copying its own decisions to its Binance account. Stops only ever tighten, never loosen.'),
                      const SizedBox(height: 8),
                      OutlinedButton(onPressed: _busy ? null : _disable, child: const Text('Switch OFF (no new trades; open ones stay protected)')),
                    ],
                    const SizedBox(height: 12),
                    FilledButton(
                      style: FilledButton.styleFrom(backgroundColor: p.loss),
                      onPressed: (_busy || !hasKey) ? null : _panic,
                      child: const Text('PANIC: close everything on the AI account'),
                    ),
                  ]),
                  if (open.isNotEmpty)
                    _card(p, [
                      _title(p, 'OPEN REAL TRADES'),
                      for (final o in open) _text(p, '${o['sym']}  ${o['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ${_n(o['lev']).round()}x  entry ${o['entry']}  stop ${o['stop_px']}'),
                    ]),
                  if (closed.isNotEmpty)
                    _card(p, [
                      _title(p, 'LAST REAL TRADES (after fees)'),
                      for (final c in closed.take(12))
                        Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: _text(p, '${c['sym']}  ${c['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ${_n(c['pnl']) >= 0 ? '+' : ''}${_f(_n(c['pnl']), 3)} USDT  (${c['by'] ?? ''})',
                              c: _n(c['pnl']) >= 0 ? p.profit : p.loss),
                        ),
                    ]),
                  if (events.isNotEmpty)
                    _card(p, [
                      _title(p, 'WHAT HAPPENED'),
                      for (final e in events.take(15)) Padding(padding: const EdgeInsets.only(bottom: 3), child: _text(p, '${_m(e)['text'] ?? e}', c: p.textSecondary)),
                    ]),
                ],
              ),
            ),
    );
  }

  Widget _kv(AppPalette p, String k, String v, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(k, style: TextStyle(fontSize: 11, color: p.textMuted)),
        Text(v, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
      ]);
}
