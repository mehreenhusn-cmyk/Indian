import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'candle_chart.dart';
import 'owl_card.dart';

/// Round 26 (OwlSniper, read-only): the SIGNAL CARD = one order card with a mini chart, one decision line, Entry / Stop / Target / R:R,
/// an evidence check (5 dots) and the buttons SKIP and WHY. Every number comes from the backend card (GET /api/v2/sniper or /api/v2/sniper_live); nothing is invented here.
/// Entry / stop / target: the triple-barrier lines (card['barrier']) when the live route sent them, else card entry_price / stop_loss / take_profit. No value = "n/a".
/// Evidence dots (green = yes, red = no, grey = not known): market TRENDING, signal side known, win chance >= the floor, floor proven on unseen TEST days, stop size fits the 10 USDT base.
/// PAPER ENTER (Round 30, PAPER only): SniperSignalList passes `onEnter` to a passing card only while the executor is ARMED (card r['executor']['armed']); the button asks once, then POSTs /api/v2/sniper_enter,
///   where the backend runs every executor gate again. Not armed = no button and one grey hint line (arming is the 2-step Termux command). SKIP only hides the card on this screen until the next refresh; nothing is saved or sent.
/// SniperSignalList has the same constructor as SniperCards (screens/sniper_panels.dart), so the Sniper screen swaps one name. Chart candles load when a card is opened (open by default for a PASS card).
/// Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
double? _n(Object? v) => v is num ? v.toDouble() : null;
String _px(Object? v) {
  final x = _n(v);
  if (x == null) return 'n/a';
  if (x >= 100) return x.toStringAsFixed(2);
  if (x >= 1) return x.toStringAsFixed(4);
  return x.toStringAsFixed(6);
}

String _pc(Object? v, [int d = 1]) => _n(v) == null ? 'n/a' : '${_n(v)!.toStringAsFixed(d)}%';
String _two(int n) => n < 10 ? '0$n' : '$n';

String _utc(Object? t) {
  if (t is! num) return 'n/a';
  final d = DateTime.fromMillisecondsSinceEpoch(t.toInt() * 1000, isUtc: true);
  return '${_two(d.hour)}:${_two(d.minute)} UTC';
}

/// One evidence row: ok true = green, false = red, null = grey (not known).
class _Check {
  final String label;
  final bool? ok;
  const _Check(this.label, this.ok);
}

class SniperSignalCard extends StatefulWidget {
  final Map<String, dynamic> card;
  final Map<String, dynamic> r;
  final VoidCallback? onSkip;
  final VoidCallback? onEnter;
  const SniperSignalCard({super.key, required this.card, required this.r, this.onSkip, this.onEnter});

  @override
  State<SniperSignalCard> createState() => _SniperSignalCardState();
}

class _SniperSignalCardState extends State<SniperSignalCard> {
  late bool _open;
  List<dynamic>? _candles;
  bool _loading = false;
  String? _err;

  Map<String, dynamic> get c => widget.card;
  bool get _pass => c['action'] == 'SNIPER_LONG' || c['action'] == 'SNIPER_SHORT';
  Map<String, dynamic> get _bar => _m(c['barrier']);
  bool get _barOk => _bar['ok'] == true;

  @override
  void initState() {
    super.initState();
    _open = _pass;
    if (_open) _loadCandles();
  }

  Future<void> _loadCandles() async {
    if (_candles != null || _loading) return;
    setState(() => _loading = true);
    final tf = '${widget.r['interval'] ?? '5m'}';
    final p = context.read<AppProvider>();
    final data = await p.fetchCandles('${c['symbol']}', limit: 120, tf: tf);
    if (!mounted) return;
    setState(() {
      _candles = data;
      _err = data.isEmpty ? p.lastCandleError : null;
      _loading = false;
    });
  }

  double? get _entry => _barOk ? _n(_bar['entry']) : _n(c['entry_price']);
  double? get _stop => _barOk ? _n(_bar['sl']) : _n(c['stop_loss']);
  double? get _tp => _barOk ? _n(_bar['tp']) : _n(c['take_profit']);

  double? get _rr {
    if (_barOk) return _n(_bar['reward_risk']);
    final e = _entry, s = _stop, t = _tp;
    if (e == null || s == null || t == null || e == s) return null;
    return (t - e).abs() / (e - s).abs();
  }

  List<_Check> _checks() {
    final conf = _n(c['confidence']);
    final floor = _n(widget.r['floor']);
    final hasBar = c.containsKey('barrier');
    return [
      _Check('Market is trending', c['regime'] == null ? null : c['regime'] == 'TRENDING'),
      _Check('Signal on the newest candle', c['side'] != null),
      _Check('Win chance at or above the floor', (conf == null || floor == null) ? null : conf >= floor),
      _Check('Floor proven on unseen TEST days', widget.r['floor_verified'] is bool ? widget.r['floor_verified'] as bool : null),
      _Check('Stop size fits a 10 USDT base', hasBar ? (c['barrier'] == null ? null : _barOk) : null),
    ];
  }

  String _decision() {
    final side = '${c['side'] ?? ''}';
    if (_pass) return '$side passes every check. Watch only, no order is sent.';
    final why = '${c['reason'] ?? ''}'.trim();
    return why.isEmpty ? 'Blocked: a check failed.' : 'Blocked: $why';
  }

  Widget _level(AppPalette p, String label, String value, [Color? col]) => Expanded(
        child: Column(children: [
          Text(value, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: col ?? p.textPrimary)),
          const SizedBox(height: 2),
          Text(label, style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      );

  Widget _dots(AppPalette p) {
    final list = _checks();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final k in list)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(children: [
            Icon(k.ok == null ? Icons.help_outline_rounded : (k.ok! ? Icons.check_circle_outline_rounded : Icons.cancel_outlined),
                size: 15, color: k.ok == null ? p.textMuted : (k.ok! ? p.profit : p.loss)),
            const SizedBox(width: 8),
            Expanded(child: Text(k.label, style: TextStyle(fontSize: 12, color: p.textSecondary))),
            Text(k.ok == null ? 'not known' : (k.ok! ? 'yes' : 'no'), style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
    ]);
  }

  Widget _chart(AppPalette p) {
    if (_loading) return const SizedBox(height: 150, child: Center(child: CircularProgressIndicator(strokeWidth: 2)));
    final ts = _n(c['t']);
    return SizedBox(
      height: 150,
      child: CandleChart(
        candles: _candles ?? const [],
        entry: _entry,
        sl: _stop,
        tpLevels: _tp == null ? null : {1: _tp},
        entryTsMs: ts == null ? null : (ts * 1000).round(),
        showEma: true,
        visibleCount: 60,
        errorText: _err,
      ),
    );
  }

  void _why() {
    final p = context.palette;
    final rule = _m(widget.r['barrier_rule'])['text'];
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: p.surfaceElevated,
      isScrollControlled: true,
      builder: (_) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Why ${c['symbol'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 8),
            Text('${c['reason'] ?? 'n/a'}', style: TextStyle(fontSize: 13, color: p.textPrimary)),
            if ('${c['report'] ?? ''}'.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('${c['report']}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
            ],
            if (c['z'] != null || c['sd_len'] != null) ...[
              const SizedBox(height: 8),
              Text('Lookback length ${c['sd_len'] ?? 'n/a'}  |  Z-Score ${c['z'] ?? 'n/a'}  |  Win chance ${_n(c['confidence']) == null ? 'n/a' : _pc(_n(c['confidence'])! * 100)}',
                  style: TextStyle(fontSize: 12, color: p.textMuted)),
            ],
            if (rule != null) ...[
              const SizedBox(height: 8),
              Text('$rule', style: TextStyle(fontSize: 12, color: p.textMuted)),
            ],
            const SizedBox(height: 10),
            Text('Candle ${_utc(c['t'])}  |  market ${c['regime'] ?? 'n/a'}', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final col = _pass ? p.profit : p.warning;
    final conf = _n(c['confidence']);
    final hold = _bar['hold'];
    return OWLCard(
      edge: col,
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${c['symbol'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: col.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
            child: Text(_pass ? 'PASSES  ${c['side'] ?? ''}' : 'BLOCKED', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: col)),
          ),
        ]),
        const SizedBox(height: 6),
        Text(_decision(), style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        const SizedBox(height: 8),
        if (_open) ...[_chart(p), const SizedBox(height: 8)],
        Row(children: [
          _level(p, 'entry', _px(_entry)),
          _level(p, 'stop', _px(_stop), p.loss),
          _level(p, 'target', _px(_tp), p.profit),
          _level(p, 'reward : risk', _rr == null ? 'n/a' : '${_rr!.toStringAsFixed(1)} : 1'),
        ]),
        const SizedBox(height: 4),
        Text(
          'Win chance ${conf == null ? 'n/a' : _pc(conf * 100)}'
          '${_barOk ? '  |  stop ${_pc(_bar['sl_pct'], 2)}  |  target ${_pc(_bar['tp_pct'], 2)}  |  max $hold candles' : ''}',
          style: TextStyle(fontSize: 11, color: p.textMuted),
        ),
        const SizedBox(height: 8),
        _dots(p),
        const SizedBox(height: 4),
        Text('Candle ${_utc(c['t'])}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        Row(children: [
          TextButton(
            onPressed: () {
              setState(() => _open = !_open);
              if (_open) _loadCandles();
            },
            child: Text(_open ? 'Hide chart' : 'Show chart'),
          ),
          TextButton(onPressed: _why, child: const Text('WHY')),
          const Spacer(),
          if (widget.onSkip != null) TextButton(onPressed: widget.onSkip, child: const Text('SKIP')),
          if (_pass && widget.onEnter != null)
            FilledButton(onPressed: widget.onEnter, child: const Text('PAPER ENTER')),
        ]),
      ]),
    );
  }
}

/// Same constructor as SniperCards. Newest first, 8 shown unless showAll. SKIP hides a card until the next refresh of this screen (nothing is saved).
class SniperSignalList extends StatefulWidget {
  final Map<String, dynamic> r;
  final bool showAll;
  final VoidCallback onToggle;
  const SniperSignalList({super.key, required this.r, required this.showAll, required this.onToggle});

  @override
  State<SniperSignalList> createState() => _SniperSignalListState();
}

class _SniperSignalListState extends State<SniperSignalList> {
  final Set<String> _skipped = <String>{};
  bool _busy = false;

  String _key(Map<String, dynamic> c) => '${c['symbol']}|${c['t']}|${c['side']}';

  bool get _armed => _m(widget.r['executor'])['armed'] == true;

  Future<void> _enter(Map<String, dynamic> c) async {
    final sym = '${c['symbol']}';
    final yes = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('PAPER ENTER'),
        content: Text('Open one PAPER trade on $sym (${c['side']}) with 10 USDT and no leverage? The executor checks every gate again. No real order is sent.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Open paper trade')),
        ],
      ),
    );
    if (yes != true || _busy || !mounted) return;
    setState(() => _busy = true);
    final res = await context.read<AppProvider>().postSniperEnter(sym);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${res['text'] ?? 'No answer from the backend.'}')));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final raw = widget.r['cards'];
    final all = <Map<String, dynamic>>[
      if (raw is List) for (final e in raw) _m(e),
    ].where((c) => !_skipped.contains(_key(c))).toList();
    final shown = widget.showAll || all.length <= 8 ? all : all.sublist(0, 8);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(
        padding: const EdgeInsets.only(left: 2, bottom: 6),
        child: Text('Signal cards (newest first)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
      ),
      if (!_armed)
        Padding(
          padding: const EdgeInsets.only(left: 2, bottom: 6),
          child: Text('PAPER ENTER shows when the executor is armed (Termux: owl_sniper_exec.py arm, then confirm).', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ),
      if (all.isEmpty)
        OWLCard(child: Text('No signal to show. A card appears when a coin crosses and the checks either pass or block it.', style: TextStyle(fontSize: 12.5, color: p.textMuted)))
      else
        for (final c in shown)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: SniperSignalCard(key: ValueKey(_key(c)), card: c, r: widget.r, onSkip: () => setState(() => _skipped.add(_key(c))), onEnter: _armed && !_busy ? () => _enter(c) : null),
          ),
      if (_skipped.isNotEmpty)
        TextButton(onPressed: () => setState(_skipped.clear), child: Text('Show ${_skipped.length} skipped card(s) again')),
      if (all.length > 8)
        TextButton(onPressed: widget.onToggle, child: Text(widget.showAll ? 'Show fewer' : 'Show all ${all.length} cards')),
    ]);
  }
}
