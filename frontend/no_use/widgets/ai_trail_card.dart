import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Overview card: "Trailing test (replay only)".
///
/// The bot takes a trade with a fixed stop loss and TP1..TP4. After TP1 the stop moves to entry.
/// This card replays every saved bot trade under two other stop-loss ladders and shows what they
/// would have given. Nothing here opens, closes or changes a trade, and the bot's strategy is not touched.
///
///   Current bot : stop to entry after TP1, close at TP4.
///   STEP1       : TP1 -> stop at entry, TP2 -> stop at TP1, TP3 -> stop at TP2, close at TP4.
///   STEP2       : TP1 -> same stop, TP2 -> stop at entry, TP3 -> stop at TP1, close at TP4.
///
/// All numbers come from the backend (GET /api/ai/observer, ai_observer.py). Fee is already inside.
class AiTrailCard extends StatefulWidget {
  final TabController? tabs; // when given, loading / refreshing only happens while this tab is the open one
  final int tabIndex;
  const AiTrailCard({super.key, this.tabs, this.tabIndex = 0});

  @override
  State<AiTrailCard> createState() => _AiTrailCardState();
}

class _AiTrailCardState extends State<AiTrailCard> {
  Map<String, dynamic>? _o;
  bool _loading = false;
  String? _error;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _o = context.read<AppProvider>().peekAi('/api/ai/observer'); // old numbers at once, fresh ones behind them
    // The screen's own numbers go first: this heavy replay card starts a moment later, and only while its tab is open.
    Future.delayed(const Duration(milliseconds: 900), () {
      if (mounted && _isVisibleTab) _load();
    });
    _timer = Timer.periodic(const Duration(seconds: 120), (_) {
      if (_isVisibleTab) _load();
    });
  }

  bool get _isVisibleTab => widget.tabs == null || widget.tabs!.index == widget.tabIndex;

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading || !mounted) return;
    _loading = true;
    final prov = context.read<AppProvider>();
    final r = await prov.fetchAiObserver();
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (r != null) {
        _o = r;
        _error = null;
      } else {
        _error = prov.aiLastError ?? 'The backend did not answer.';
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<dynamic> _l(dynamic v) => v is List ? v : const [];
  static String _s(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

  static String _ago(dynamic ts) {
    if (ts is! num) return 'a while ago';
    final s = (DateTime.now().millisecondsSinceEpoch / 1000.0 - ts.toDouble()).round();
    return '${fmtSpan(s)} ago';
  }

  Map<String, dynamic> _pol(String key) {
    for (final x in _l(_o?['policies'])) {
      final m = _m(x);
      if (m['key'] == key) return m;
    }
    return <String, dynamic>{};
  }

  Color _roi(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  String _verdictText(Map<String, dynamic> r) {
    switch ((r['verdict'] ?? '').toString()) {
      case 'CLEAR':
        return 'Clearly better than the bot: ahead in the older trades and in the newer trades.';
      case 'MAYBE':
        return 'Maybe better. It is ahead overall, but not in both the older and the newer trades yet.';
      case 'SAME':
        return 'About the same as the bot.';
      case 'WORSE':
        return 'Worse than the bot.';
      default:
        return 'Collecting data.';
    }
  }

  Color _verdictColor(AppPalette p, Map<String, dynamic> r) {
    switch ((r['verdict'] ?? '').toString()) {
      case 'CLEAR':
        return p.profit;
      case 'WORSE':
        return p.loss;
      default:
        return p.warning;
    }
  }

  Widget _box(AppPalette p, Widget child, {Color? edge}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: (edge ?? p.border).withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _head(BuildContext context, String sub) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('TRAILING TEST (REPLAY ONLY)', style: context.type.section.copyWith(fontSize: 13)),
          Text(sub, style: context.type.metadata),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final o = _o;
    if (o == null) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _head(context, 'Same bot trades, only the stop loss moves. The live bot is not changed.'),
          if (_error != null) ...[
            Text('Could not load the trailing test.', style: context.type.section.copyWith(fontSize: 13, color: p.loss)),
            const SizedBox(height: 4),
            Text(_error!, style: context.type.secondary),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _load, child: const Text('Retry')),
          ] else ...[
            Text('Loading... the first replay can take up to 40 seconds on the phone.', style: context.type.secondary),
            const SizedBox(height: 8),
            const LinearProgressIndicator(minHeight: 3),
          ],
        ]),
      );
    }

    final bot = _pol('BOT');
    final s1 = _pol('STEP1');
    final s2 = _pol('STEP2');
    final n = _i(o['n']);
    final fid = _m(o['fidelity']);
    final ee = _m(o['entry_exit']);
    final never = _m(ee['never']);
    final gave = _m(ee['gave_back']);
    final kept = _m(ee['kept']);
    final tooFew = (o['status'] ?? '') != 'OK';
    final hasUsdt = bot['usdt'] != null && s1['usdt'] != null && s2['usdt'] != null;
    final rows = <Map<String, dynamic>>[
      {'name': 'Current bot', 'sub': 'Stop to entry after TP1', 'r': bot},
      {'name': 'STEP1', 'sub': 'TP1: entry | TP2: TP1 | TP3: TP2', 'r': s1},
      {'name': 'STEP2', 'sub': 'TP1: same stop | TP2: entry | TP3: TP1', 'r': s2},
    ];

    Widget cell(String t, int flex, {TextAlign a = TextAlign.right, Color? c, bool bold = false}) => Expanded(
        flex: flex,
        child: Text(t,
            textAlign: a,
            style: context.type.secondary.copyWith(color: c, fontWeight: bold ? FontWeight.w800 : null, fontSize: 12.5)));

    Widget rowFor(Map<String, dynamic> row) {
      final r = _m(row['r']);
      final isBot = row['name'] == 'Current bot';
      final avg = _n(r['avg']);
      final total = hasUsdt ? _n(r['usdt']) : _n(r['total']);
      final botTotal = hasUsdt ? _n(bot['usdt']) : _n(bot['total']);
      final diff = total - botTotal;
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            flex: 6,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(row['name'].toString(), style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w800)),
              Text(row['sub'].toString(), style: context.type.metadata.copyWith(fontSize: 10.5)),
            ]),
          ),
          cell('${_s(avg, d: 2)}%', 3, c: _roi(p, avg), bold: true),
          cell(hasUsdt ? _s(total, d: 1) : '${_s(total, d: 0)}%', 3, c: _roi(p, total)),
          cell(isBot ? 'control' : (hasUsdt ? _s(diff, d: 1) : '${_s(diff, d: 0)}%'), 3,
              c: isBot ? p.textMuted : _roi(p, diff), bold: !isBot),
        ]),
      );
    }

    // Plain English "what next": based only on the verdict words, nothing guessed.
    final v1 = (s1['verdict'] ?? '').toString();
    final v2 = (s2['verdict'] ?? '').toString();
    String next;
    if (tooFew || n < 30) {
      next = 'Next step: wait. Only $n trades have a saved journey. A verdict needs 30 or more.';
    } else if (v1 == 'CLEAR' || v2 == 'CLEAR') {
      final w = (v1 == 'CLEAR' && v2 == 'CLEAR') ? (_n(s1['gain_total']) >= _n(s2['gain_total']) ? 'STEP1' : 'STEP2') : (v1 == 'CLEAR' ? 'STEP1' : 'STEP2');
      next = 'Next step: $w is clearly better in replay. It is worth testing in paper trading before touching the live bot.';
    } else if (v1 == 'MAYBE' || v2 == 'MAYBE') {
      next = 'Next step: keep collecting trades. One ladder looks promising but is not proven in both halves of the data.';
    } else {
      next = 'Next step: keep the current trailing. Neither ladder beat the bot in replay.';
    }

    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, 'Same bot trades, same entry, SL and targets. Only the stop loss moves. The live bot is not changed.'),
        Row(children: [
          Expanded(flex: 6, child: Text('Rule', style: context.type.metadata)),
          Expanded(flex: 3, child: Text('Avg/trade', textAlign: TextAlign.right, style: context.type.metadata)),
          Expanded(flex: 3, child: Text(hasUsdt ? 'Total USDT' : 'Total ROI', textAlign: TextAlign.right, style: context.type.metadata)),
          Expanded(flex: 3, child: Text('vs bot', textAlign: TextAlign.right, style: context.type.metadata)),
        ]),
        const Divider(height: 10),
        for (final row in rows) rowFor(row),
        const SizedBox(height: 6),
        for (final row in rows.skip(1))
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text.rich(TextSpan(children: [
              TextSpan(text: '${row['name']}: ', style: TextStyle(fontWeight: FontWeight.w800, color: _verdictColor(p, _m(row['r'])))),
              TextSpan(text: _verdictText(_m(row['r']))),
            ]), style: context.type.secondary.copyWith(fontSize: 12.5)),
          ),
        const SizedBox(height: 4),
        Text(next, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
        if (n > 0) ...[
          const SizedBox(height: 12),
          Text('WHERE THE LOSSES COME FROM', style: context.type.section.copyWith(fontSize: 12)),
          const SizedBox(height: 4),
          _leak(context, p, 'Never reached TP1', _i(never['n']), _n(never['sum']),
              'Entry side. A trailing stop cannot fix these.'),
          _leak(context, p, 'Reached TP1, then lost', _i(gave['n']), _n(gave['sum']),
              'Exit side. Trailing can help here.'),
          _leak(context, p, 'Reached TP1 and kept profit', _i(kept['n']), _n(kept['sum']), 'These are the trades that pay.'),
        ],
        const SizedBox(height: 8),
        Text(
          '$n trades replayed | calculated ${_ago(o['ts'])}. Replay has no slippage, so real results are a little worse.'
          '${fid['ok'] == false && _i(fid['n']) > 0 ? ' Warning: the replay of the current bot rule does not match the real results well (${_n(fid['close_pct']).toStringAsFixed(0)}% close), so treat these numbers as rough.' : ''}',
          style: context.type.metadata,
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('Refresh failed: $_error. These are the last good numbers.',
                style: context.type.metadata.copyWith(color: p.loss, fontWeight: FontWeight.w700)),
          ),
      ]),
    );
  }

  Widget _leak(BuildContext context, AppPalette p, String label, int n, double sum, String hint) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('$label ($n)', style: context.type.secondary.copyWith(fontSize: 12.5))),
            Text('${_s(sum, d: 0)}%', style: context.type.secondary.copyWith(fontSize: 12.5, fontWeight: FontWeight.w800, color: _roi(p, sum))),
          ]),
          Text(hint, style: context.type.metadata.copyWith(fontSize: 10.5)),
        ]),
      );
}
