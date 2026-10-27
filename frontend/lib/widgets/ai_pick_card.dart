import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Bot vs AI tab, top card: "AI Pick".
///
/// On every bot signal the AI says TAKE, SKIP or WATCH (paper only, nothing real is touched):
///   TAKE  = a situation of this signal is PROVEN to pay (two proven situations, or one proven combo).
///   SKIP  = a situation of this signal is PROVEN to lose.
///   WATCH = nothing is proven yet. The AI only watches and writes down what the bot made.
/// The AI Coach still opens a virtual trade on every signal (that is how it keeps learning). The scoreboard splits those
/// finished trades by the AI's call, so you see what the AI would have made by taking only its picks.
///
/// Everything comes from GET /api/ai/pick (backend ai_pick.py). All text is plain English.
class AiPickCard extends StatefulWidget {
  final TabController? tabs; // when given, refreshing only happens while this tab is the open one
  final int tabIndex;
  const AiPickCard({super.key, this.tabs, this.tabIndex = 0});

  @override
  State<AiPickCard> createState() => _AiPickCardState();
}

class _AiPickCardState extends State<AiPickCard> {
  Map<String, dynamic>? _o;
  bool _loading = false;
  String? _error;
  Timer? _timer;
  bool _showLists = false;

  @override
  void initState() {
    super.initState();
    _o = context.read<AppProvider>().peekAi('/api/ai/pick');
    _load();
    _timer = Timer.periodic(const Duration(seconds: 120), (_) {
      if (widget.tabs != null && widget.tabs!.index != widget.tabIndex) return;
      _load();
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
    final r = await prov.fetchAiPick();
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
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _s(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

  static String _ago(dynamic ts) {
    if (ts is! num) return 'a while ago';
    final s = (DateTime.now().millisecondsSinceEpoch / 1000.0 - ts.toDouble()).round();
    return '${fmtSpan(s)} ago';
  }

  Color _pnl(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  Color _call(AppPalette p, String c) => c == 'TAKE' ? p.profit : (c == 'SKIP' ? p.loss : p.warning);

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

  Widget _head(BuildContext context, String t, {String? sub}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.section.copyWith(fontSize: 13)),
          if (sub != null) Text(sub, style: context.type.metadata),
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
          _head(context, 'AI PICK (PAPER)',
              sub: 'On every bot signal the AI says TAKE, SKIP or WATCH.'),
          if (_error != null) ...[
            Text('Could not load AI Pick.', style: context.type.section.copyWith(fontSize: 13, color: p.loss)),
            const SizedBox(height: 4),
            Text(_error!, style: context.type.secondary),
            const SizedBox(height: 8),
            OutlinedButton(onPressed: _load, child: const Text('Retry')),
          ] else ...[
            Text('Loading... the first count can take up to 40 seconds on the phone.', style: context.type.secondary),
            const SizedBox(height: 8),
            const LinearProgressIndicator(minHeight: 3),
          ],
        ]),
      );
    }
    if (o['error'] != null) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _head(context, 'AI PICK (PAPER)'),
          Text('The backend could not build AI Pick: ${o['error']}', style: context.type.secondary.copyWith(color: p.loss)),
          const SizedBox(height: 8),
          OutlinedButton(onPressed: _load, child: const Text('Retry')),
        ]),
        edge: p.loss,
      );
    }
    if (o['enabled'] == false) {
      return _box(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _head(context, 'AI PICK (PAPER)'),
          Text('AI Pick is switched off (setting pick_enabled).', style: context.type.secondary),
        ]),
      );
    }

    final counts = _m(o['counts']);
    final calls = _m(o['calls']);
    final be = _m(_m(o['break_even'])['ALL']);
    final sb = _m(o['scoreboard']);
    final all = _m(sb['all']);
    final take = _m(sb['take']);
    final out = _m(sb['stayed_out']);
    final tfTxt = (o['tf'] ?? '3m').toString();
    final decided = _i(calls['TAKE']) + _i(calls['SKIP']) + _i(calls['WATCH']);

    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _scoreboard(context, p, all, take, out, sb, decided),
      const SizedBox(height: 10),
      _proof(context, p, counts, calls, be, tfTxt, _m(o['rules'])),
      const SizedBox(height: 10),
      _decisions(context, p, _l(o['recent'])),
      const SizedBox(height: 10),
      _lists(context, p, o),
      if (_l(o['log']).isNotEmpty) ...[
        const SizedBox(height: 10),
        _changes(context, p, _l(o['log'])),
      ],
      const SizedBox(height: 6),
      Text(
        'Counted ${_ago(o['built_ts'])} | AI Pick engine checked ${o['tick_age'] == null ? 'not yet' : '${_i(o['tick_age'])}s ago'}'
        '${(_o?['tick_age'] is num && _i(o['tick_age']) > 90) ? '. The engine looks stuck: open http://localhost:8000/api/ai/health and send me what it shows.' : ''}',
        style: context.type.metadata.copyWith(color: (o['tick_age'] is num && _i(o['tick_age']) > 90) ? p.loss : null),
      ),
      if (_error != null)
        Text('Refresh failed: $_error. These are the last good numbers.',
            style: context.type.metadata.copyWith(color: p.loss, fontWeight: FontWeight.w700)),
    ]);
  }

  // ------------------------------------------------------------------ 1. scoreboard
  Widget _scoreboard(BuildContext context, AppPalette p, Map<String, dynamic> all, Map<String, dynamic> take,
      Map<String, dynamic> out, Map<String, dynamic> sb, int decided) {
    final st = context.type.secondary.copyWith(fontSize: 12.5);
    Widget cell(String t, int flex, {TextAlign a = TextAlign.right, Color? c, bool bold = false}) => Expanded(
        flex: flex, child: Text(t, textAlign: a, style: st.copyWith(color: c, fontWeight: bold ? FontWeight.w800 : null)));
    Widget row(String label, String sub, Map<String, dynamic> g, {bool showAi = true}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 6,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(label, style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w800)),
                Text(sub, style: context.type.metadata.copyWith(fontSize: 10.5)),
              ]),
            ),
            cell('${_i(g['n'])}', 2),
            cell(_s(_n(g['bot_pnl'])), 3, c: _pnl(p, _n(g['bot_pnl'])), bold: true),
            cell(showAi ? _s(_n(g['ai_pnl'])) : '-', 3, c: showAi ? _pnl(p, _n(g['ai_pnl'])) : p.textMuted, bold: true),
          ]),
        );

    final nTake = _i(take['n']);
    final saved = _n(sb['saved']);
    final pickGain = _n(sb['pick_vs_all']);
    String verdict;
    if (_i(all['n']) == 0) {
      verdict = decided == 0
          ? 'No decision yet. When the bot takes its next signal, the AI judges it and the numbers start here.'
          : 'The AI has judged $decided signals. Their trades have not finished yet.';
    } else if (nTake < 10) {
      verdict = 'Too early to judge. Only $nTake picked trades have finished. Look again at 30 or more.';
    } else if (pickGain > 0) {
      verdict = 'Picking helped: by taking only its picks the AI made ${pickGain.toStringAsFixed(1)} USDT more than by taking everything.';
    } else {
      verdict = 'Picking has not helped yet: taking only its picks gave ${pickGain.toStringAsFixed(1)} USDT compared with taking everything.';
    }
    final outN = _i(out['n']);
    final stayLine = outN == 0
        ? ''
        : (saved > 0
            ? 'By staying out of $outN signals, the AI avoided a bot loss of ${saved.toStringAsFixed(1)} USDT.'
            : 'The $outN signals the AI stayed out of made the bot ${(-saved).toStringAsFixed(1)} USDT. That is profit the AI missed.');

    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, 'AI PICK SCOREBOARD (PAPER)',
            sub: 'The AI says TAKE, SKIP or WATCH on every bot signal. USDT, after fees, finished trades only.'),
        Row(children: [
          Expanded(flex: 6, child: Text('Group', style: context.type.metadata)),
          Expanded(flex: 2, child: Text('Trades', textAlign: TextAlign.right, style: context.type.metadata)),
          Expanded(flex: 3, child: Text('Bot', textAlign: TextAlign.right, style: context.type.metadata)),
          Expanded(flex: 3, child: Text('AI', textAlign: TextAlign.right, style: context.type.metadata)),
        ]),
        const Divider(height: 10),
        row('All judged signals', 'If the AI took everything', all),
        row('AI said TAKE', 'Only the signals the AI picked', take),
        row('AI stayed out', 'SKIP and WATCH (the AI took no trade)', out, showAi: false),
        const SizedBox(height: 6),
        Text(verdict, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
        if (stayLine.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(stayLine, style: context.type.secondary),
        ],
        const SizedBox(height: 4),
        Text(
            'The AI Coach still opens a virtual trade on every bot signal so it keeps learning. This table splits those trades by what the AI Pick said.',
            style: context.type.metadata),
      ]),
      edge: nTake >= 10 && pickGain > 0 ? p.profit : null,
    );
  }

  // ------------------------------------------------------------------ 2. what the AI has proven
  Widget _proof(BuildContext context, AppPalette p, Map<String, dynamic> counts, Map<String, dynamic> calls,
      Map<String, dynamic> be, String tf, Map<String, dynamic> rules) {
    final beWr = be['be'];
    final wr = _n(be['wr']);
    final String beLine;
    if (beWr == null || _i(be['n']) < 10) {
      beLine = 'Break-even win rate: not enough finished signals yet.';
    } else {
      final b = _n(beWr);
      beLine = 'Break-even win rate (after fees): ${b.toStringAsFixed(1)}%. The bot wins ${wr.toStringAsFixed(1)}% '
          '(avg win ${_s(_n(be['avg_win']), d: 1)}%, avg loss -${_n(be['avg_loss']).toStringAsFixed(1)}%). '
          '${wr < b ? 'It wins less often than it needs, so the AI must find situations where it wins more.' : 'It wins more often than it needs.'}';
    }
    final taking = _i(counts['taking']);
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, 'WHAT THE AI HAS PROVEN SO FAR',
            sub: 'Situations are counted on the newest ${_i(counts['signals'])} finished $tf signals of the bot, BUY and SELL apart.'),
        Wrap(spacing: 8, runSpacing: 6, children: [
          _pill(p, 'Taking $taking', p.profit),
          _pill(p, 'Watching ${_i(counts['watching'])}', p.warning),
          _pill(p, 'Avoid ${_i(counts['avoid'])}', p.loss),
          _pill(p, 'Stopped ${_i(counts['stopped'])}', p.textMuted),
        ]),
        const SizedBox(height: 8),
        Text(
            taking == 0
                ? 'Nothing is proven yet, so the AI takes no trade. That is on purpose: a situation must pay clearly, in both the older and the newer signals, before the AI trusts it.'
                : '$taking situations are proven to pay. A signal is TAKE only when two of them match, or one proven combo matches, and nothing proven to lose matches.',
            style: context.type.secondary),
        const SizedBox(height: 6),
        Text(beLine, style: context.type.secondary),
        const SizedBox(height: 6),
        Text(
            'Decisions so far: TAKE ${_i(calls['TAKE'])}, SKIP ${_i(calls['SKIP'])}, WATCH ${_i(calls['WATCH'])}. '
            'Re-counted every ${(_i(rules['rebuild_s']) / 60).round()} min, so a situation that stops working is dropped.',
            style: context.type.metadata),
      ]),
    );
  }

  Widget _pill(AppPalette p, String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(12)),
        child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
      );

  // ------------------------------------------------------------------ 3. latest decisions
  Widget _decisions(BuildContext context, AppPalette p, List<Map<String, dynamic>> recent) {
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, 'LATEST AI DECISIONS', sub: 'One line per bot signal: what the AI said and why.'),
        if (recent.isEmpty)
          Text('No decision yet. The AI judges a signal about a minute after the bot takes it.', style: context.type.secondary)
        else
          for (final r in recent.take(10)) _decisionRow(context, p, r),
      ]),
    );
  }

  Widget _decisionRow(BuildContext context, AppPalette p, Map<String, dynamic> r) {
    final call = (r['call'] ?? '').toString();
    final bot = r['bot_pnl'];
    final ai = r['ai_pnl'];
    final side = (r['side'] ?? '').toString() == 'BUY' ? 'LONG' : 'SHORT';
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _pill(p, call, _call(p, call)),
          const SizedBox(width: 8),
          Expanded(
              child: Text('${r['sym']} $side', style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w800))),
          Text(
              bot == null ? 'running' : 'bot ${_s(_n(bot))}${call == 'TAKE' && ai != null ? ' | AI ${_s(_n(ai))}' : ''} USDT',
              style: context.type.metadata.copyWith(color: bot == null ? p.textMuted : _pnl(p, _n(bot)), fontWeight: FontWeight.w700)),
        ]),
        const SizedBox(height: 2),
        Text('${(r['why'] ?? '').toString()}  (${_ago(r['t'])})', style: context.type.metadata.copyWith(fontSize: 11)),
      ]),
    );
  }

  // ------------------------------------------------------------------ 4. lists of situations
  Widget _lists(BuildContext context, AppPalette p, Map<String, dynamic> o) {
    final taking = _l(o['taking']);
    final close = _l(o['close']);
    final avoid = _l(o['avoid']);
    final stopped = _l(o['stopped']);
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        GestureDetector(
          onTap: () => setState(() => _showLists = !_showLists),
          child: Row(children: [
            Expanded(child: _head(context, 'SITUATIONS THE AI HAS COUNTED', sub: 'Tap to ${_showLists ? 'hide' : 'show'} the lists.')),
            Icon(_showLists ? Icons.expand_less_rounded : Icons.expand_more_rounded, color: p.textMuted),
          ]),
        ),
        if (_showLists) ...[
          _group(context, p, 'Taking now', 'Proven to pay.', taking, p.profit, empty: 'Nothing proven yet.'),
          _group(context, p, 'Closest to proven', 'Positive, but the proof is not strong enough yet.', close, p.warning,
              empty: 'No situation is close yet.'),
          _group(context, p, 'Avoid', 'Proven to lose. A signal with one of these is SKIP.', avoid, p.loss, empty: 'None.'),
          _group(context, p, 'Stopped', 'Were taken before, but no longer show an edge.', stopped, p.textMuted, empty: 'None.'),
        ],
      ]),
    );
  }

  Widget _group(BuildContext context, AppPalette p, String title, String sub, List<Map<String, dynamic>> items, Color c,
      {required String empty}) {
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$title (${items.length})', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: c)),
        Text(sub, style: context.type.metadata.copyWith(fontSize: 10.5)),
        const SizedBox(height: 4),
        if (items.isEmpty)
          Text(empty, style: context.type.secondary)
        else
          for (final s in items.take(8))
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${(s['side'] ?? '') == 'BUY' ? 'LONG' : 'SHORT'}: ${s['text']}',
                    style: context.type.secondary.copyWith(fontSize: 12.5, fontWeight: FontWeight.w700)),
                Text('${s['kind']} | ${_s(_n(s['avg']))}% avg | ${_i(s['n'])} signals | wins ${_n(s['wr']).toStringAsFixed(0)}%',
                    style: context.type.metadata.copyWith(fontSize: 11)),
              ]),
            ),
      ]),
    );
  }

  // ------------------------------------------------------------------ 5. what changed
  Widget _changes(BuildContext context, AppPalette p, List<Map<String, dynamic>> log) {
    return _box(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _head(context, 'WHAT CHANGED LATELY', sub: 'When the AI starts or stops trusting a situation.'),
        for (final x in log.take(6))
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text('${(x['text'] ?? '').toString()}  (${_ago(x['t'])})', style: context.type.secondary.copyWith(fontSize: 12.5)),
          ),
      ]),
    );
  }
}
