import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Trades tab: "TRAILING ON PAST TRADES".
///
/// For each saved past bot trade it shows three numbers side by side (ROI %, fee already inside):
///   Bot    : what the bot's rule gives (stop moves to entry after TP1, close at TP4).
///   STEP1  : TP1 -> stop at entry, TP2 -> stop at TP1, TP3 -> stop at TP2, close at TP4.
///   STEP2  : TP1 -> same stop, TP2 -> stop at entry, TP3 -> stop at TP1, close at TP4.
/// It is a replay of the saved price path of each trade. Nothing is opened, closed or changed.
/// Data: GET /api/ai/diary (backend ai_observer.diary). All text is plain English.
class AiTrailTradesCard extends StatefulWidget {
  final TabController? tabs; // when given, loading / refreshing only happens while this tab is the open one
  final int tabIndex;
  const AiTrailTradesCard({super.key, this.tabs, this.tabIndex = 0});

  @override
  State<AiTrailTradesCard> createState() => _AiTrailTradesCardState();
}

class _AiTrailTradesCardState extends State<AiTrailTradesCard> {
  Map<String, dynamic>? _d;
  bool _loading = false;
  bool _all = false;
  bool _how = false;
  String? _error;
  Timer? _timer;

  bool get _isVisibleTab => widget.tabs == null || widget.tabs!.index == widget.tabIndex;

  @override
  void initState() {
    super.initState();
    _d = context.read<AppProvider>().peekAi('/api/ai/diary'); // old numbers at once, fresh ones behind them
    Future.delayed(const Duration(milliseconds: 1500), () {
      if (mounted && _isVisibleTab) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 180), (_) {
      if (_isVisibleTab) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading || !mounted) return;
    _loading = true;
    final prov = context.read<AppProvider>();
    final r = await prov.fetchAiDiary();
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (r != null) {
        _d = r;
        _error = null;
      } else {
        _error = prov.aiLastError ?? 'The backend did not answer.';
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _s(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

  static String _ago(dynamic ts) {
    if (ts is! num || ts <= 0) return '';
    final s = (DateTime.now().millisecondsSinceEpoch / 1000.0 - ts.toDouble()).round();
    return '${fmtSpan(s)} ago';
  }

  static String _end(dynamic r) {
    final x = (r ?? '').toString().toUpperCase();
    if (x.startsWith('TP')) return 'ended at target';
    if (x == 'SL') return 'ended at stop loss';
    if (x == 'REVERSED') return 'closed by opposite signal';
    if (x == 'MANUAL') return 'closed by hand';
    return 'closed';
  }

  Color _c(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  Widget _box(AppPalette p, Widget child) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        margin: const EdgeInsets.only(bottom: 10),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: p.border.withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _num(AppPalette p, String label, double v, {bool best = false}) => Expanded(
        child: Column(children: [
          Text(label, style: TextStyle(fontSize: 10.5, color: p.textMuted, fontWeight: FontWeight.w700)),
          const SizedBox(height: 1),
          Text('${_s(v)}%',
              style: TextStyle(fontSize: 13, fontWeight: best ? FontWeight.w900 : FontWeight.w600, color: _c(p, v))),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    const title = 'TRAILING ON PAST TRADES';
    Widget head(String? sub) => Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: context.type.section.copyWith(fontSize: 13)),
            if (sub != null) Text(sub, style: context.type.metadata),
          ]),
        );
    if (d == null) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          head('What the two trailing setups would have given on your past trades.'),
          if (_error != null) ...[
            Text(_error!, style: context.type.secondary.copyWith(color: p.loss)),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _load, child: const Text('Retry')),
          ] else
            Text('Loading...', style: context.type.secondary),
        ]),
      );
    }
    final rows = _l(d['rows']).where((r) => _m(r['rules']).containsKey('STEP1') && _m(r['rules']).containsKey('STEP2')).toList();
    if (rows.isEmpty) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          head('What the two trailing setups would have given on your past trades.'),
          Text('No past trade with a saved price path yet. When the bot closes trades, they appear here.', style: context.type.secondary),
        ]),
      );
    }
    double sum(String k) => rows.fold(0.0, (a, r) => a + _n(_m(r['rules'])[k]));
    final bot = sum('BOT'), s1 = sum('STEP1'), s2 = sum('STEP2');
    final best = (s1 >= s2 ? s1 : s2);
    final bestName = s1 >= s2 ? 'STEP1' : 'STEP2';
    String verdict;
    if (best > bot + 0.5 * rows.length * 0.1) {
      verdict = 'On these ${rows.length} trades $bestName would have given ${_s(best - bot, d: 0)}% more than the bot. '
          'Check the Overview card before changing anything: it says if this holds for older and newer trades.';
    } else if (best < bot - 0.5 * rows.length * 0.1) {
      verdict = 'On these ${rows.length} trades both setups would have given less than the bot.';
    } else {
      verdict = 'On these ${rows.length} trades the two setups are about the same as the bot.';
    }
    final shown = _all ? rows : rows.take(8).toList();
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        head('Replay of your last ${rows.length} saved trades. Nothing is changed in the bot.'),
        Row(children: [
          _num(p, 'Bot', bot, best: bot >= s1 && bot >= s2),
          _num(p, 'STEP1', s1, best: s1 > bot && s1 >= s2),
          _num(p, 'STEP2', s2, best: s2 > bot && s2 > s1),
        ]),
        const SizedBox(height: 4),
        Text('Total ROI % of these trades, fee already inside.', style: context.type.metadata),
        const SizedBox(height: 6),
        Text(verdict, style: TextStyle(fontSize: 12.5, height: 1.4, fontWeight: FontWeight.w700, color: p.textPrimary)),
        const SizedBox(height: 6),
        InkWell(
          onTap: () => setState(() => _how = !_how),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(_how ? 'Hide: how the setups work' : 'Show: how the setups work',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.purple)),
          ),
        ),
        if (_how)
          Text(
              'Bot: price touches TP1, the stop moves to your entry. It stays there until TP4 or the stop.\n'
              'STEP1: TP1 -> stop at entry. TP2 -> stop at TP1. TP3 -> stop at TP2. Close at TP4. It locks profit early.\n'
              'STEP2: after TP1 the stop does not move. TP2 -> stop at entry. TP3 -> stop at TP1. Close at TP4. It gives the trade more room.\n'
              'Limits: this is a replay of saved prices, with no slippage. Inside one 15 s sample the stop is checked first, so the numbers lean pessimistic.',
              style: context.type.metadata.copyWith(height: 1.4)),
        const Divider(height: 18),
        for (final r in shown)
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${r['sym']}  ${r['side'] == 'BUY' ? 'LONG' : 'SHORT'}  ·  ${_end(r['reason'])}  ·  ${_ago(r['closed'])}',
                  style: context.type.secondary.copyWith(fontSize: 12, fontWeight: FontWeight.w700)),
              const SizedBox(height: 3),
              Builder(builder: (_) {
                final ru = _m(r['rules']);
                final b = _n(ru['BOT']), a = _n(ru['STEP1']), c = _n(ru['STEP2']);
                final top = [b, a, c].reduce((x, y) => x > y ? x : y);
                return Row(children: [
                  _num(p, 'Bot', b, best: b == top && (a != b || c != b)),
                  _num(p, 'STEP1', a, best: a == top && a != b),
                  _num(p, 'STEP2', c, best: c == top && c != b),
                ]);
              }),
            ]),
          ),
        if (rows.length > 8)
          InkWell(
            onTap: () => setState(() => _all = !_all),
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Text(_all ? 'Show fewer' : 'Show all ${rows.length} trades',
                  style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.purple)),
            ),
          ),
        if (_error != null)
          Text('Could not refresh: $_error These are the old numbers.', style: context.type.metadata.copyWith(color: p.loss)),
      ]),
    );
  }
}
