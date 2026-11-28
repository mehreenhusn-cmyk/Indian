import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// AI COACH: on every bot signal the AI opens its own virtual trade (same entry), manages it itself, keeps
/// watching the price after it closes, and learns which Z / TSI / SD situations go with the trade.
/// Everything is computed on the backend (GET /api/ai/coach, ai_coach.py). Display only.
class AiCoachCard extends StatefulWidget {
  /// embeddedData: the host screen already loaded /api/ai/coach and passes it in (no own timer / request).
  /// part: 'all' | 'top' (AI vs Bot scoreboard) | 'rest' (margin, what the AI found, memo).
  final Map<String, dynamic>? embeddedData;
  final String part;
  final VoidCallback? onReload;
  const AiCoachCard({super.key, this.embeddedData, this.part = 'all', this.onReload});

  @override
  State<AiCoachCard> createState() => _AiCoachCardState();
}

class _AiCoachCardState extends State<AiCoachCard> with AutomaticKeepAliveClientMixin {
  Map<String, dynamic>? _d;
  bool _busy = false;
  Timer? _timer;

  @override
  bool get wantKeepAlive => true;

  @override
  void initState() {
    super.initState();
    if (widget.embeddedData != null) return;
    _d = context.read<AppProvider>().peekAi('/api/ai/coach');
    _load();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    final r = await context.read<AppProvider>().fetchAiCoach();
    _busy = false;
    if (mounted && r != null) setState(() => _d = r);
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<dynamic> _l(dynamic v) => v is List ? v : const [];
  static String _pct(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(1)}%';
  static String _usdt(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(2)}';

  static String _hm(dynamic ts) {
    if (ts is! num) return '--';
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round(), isUtc: true).add(const Duration(hours: 5, minutes: 30));
    return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
  }

  Color _col(AppPalette p, double v) => v > 0 ? p.profit : (v < 0 ? p.loss : p.textMuted);

  Widget _card(AppPalette p, Widget child) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: p.border, width: 1),
        ),
        child: child,
      );

  Widget _title(AppPalette p, String t) => Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)));

  Widget _chip(AppPalette p, String t) => Container(
        margin: const EdgeInsets.only(right: 5, bottom: 5),
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(color: p.border.withOpacity(0.5), borderRadius: BorderRadius.circular(6)),
        child: Text(t, style: TextStyle(fontSize: 11, color: p.textPrimary)),
      );

  static String _rt(dynamic v) {
    if (v is! num) return '--';
    final x = v.toDouble();
    if (x.abs() < 0.005) return '0R';
    return '${x > 0 ? '+' : '-'}${x.abs().toStringAsFixed(1)}R';
  }

  /// DECISION CARD: for every open AI trade, what the AI decided at the last closed candle (HOLD / BOOK / SCALP), where that
  /// decision came from (learned from past trades, or the basic rule) and why, plus the Risk ticks (R-multiple ladder).
  /// 1R = the distance from entry to the ORIGINAL stop. Display only: the numbers come from /api/ai/coach (ai_coach.py).
  Widget _decisionCard(AppPalette p, List<dynamic> opens) {
    final small = TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted);
    Color callColor(String c) => c == 'BOOK' ? p.loss : (c == 'SCALP' ? p.warning : p.profit);
    return _card(
      p,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'AI DECISIONS ON OPEN TRADES'),
        for (final raw in opens)
          Builder(builder: (_) {
            final o = _m(raw);
            final dec = _m(o['dec']);
            final call = '${dec['call'] ?? ''}';
            final learned = '${dec['src'] ?? ''}' == 'LEARNED';
            final stopR = o['stop_r'] is num ? (o['stop_r'] as num).toDouble() : null;
            final nowR = o['r_now'] is num ? (o['r_now'] as num).toDouble() : null;
            final tps = [for (final t in _l(o['tp_r'])) t is num ? t.toDouble() : null];
            String stopText;
            if (stopR == null) {
              stopText = 'stop: --';
            } else if (stopR.abs() < 0.005) {
              stopText = 'stop at entry (0R): this trade can no longer lose';
            } else if (stopR > 0) {
              stopText = '${o['trail'] == true ? 'trailing ' : ''}stop locks ${_rt(stopR)} of profit';
            } else {
              stopText = 'stop at ${_rt(stopR)} (the full risk of this trade)';
            }
            return Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: Text('${o['sym']} ${o['side'] == 'BUY' ? 'LONG' : 'SHORT'}', style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800))),
                  Text(_pct(o['roi']), style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: _col(p, _n(o['roi'])))),
                ]),
                const SizedBox(height: 4),
                if (call.isEmpty)
                  Text('Waiting for the first closed candle to decide.', style: small)
                else ...[
                  Row(children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
                      decoration: BoxDecoration(color: callColor(call).withOpacity(0.16), borderRadius: BorderRadius.circular(6), border: Border.all(color: callColor(call))),
                      child: Text(call == 'SCALP' ? 'SCALP: BOOK AT TP2' : call, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: callColor(call))),
                    ),
                    const SizedBox(width: 8),
                    Text(learned ? 'learned from past trades' : 'basic rule (not enough past cases yet)', style: small),
                  ]),
                  const SizedBox(height: 4),
                  Text('${dec['why'] ?? ''}', style: TextStyle(fontSize: 12.5, height: 1.35, color: p.textPrimary)),
                ],
                const SizedBox(height: 6),
                Text('Now ${_rt(nowR)} | $stopText', style: small),
                const SizedBox(height: 2),
                _RiskLadder(p: p, now: nowR, stop: stopR, tps: tps),
              ]),
            );
          }),
        Text('1R = the distance from entry to the original stop. The AI decides again at every closed candle; it can only move a stop closer to the price, never further away.',
            style: small),
      ]),
    );
  }

  Widget _learnRow(AppPalette p, Map<String, dynamic> r, Color c) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Text('${r['text']}', style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textPrimary))),
          const SizedBox(width: 8),
          Text('${_i(r['p'])}%\n${_i(r['n'])} cases', textAlign: TextAlign.right, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: c)),
        ]),
      );

  Future<void> _editBalance(double current) async {
    final ctl = TextEditingController(text: current.toStringAsFixed(0));
    final v = await showDialog<double>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('AI virtual balance (USDT)'),
        content: TextField(controller: ctl, keyboardType: const TextInputType.numberWithOptions(decimal: true)),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, double.tryParse(ctl.text.trim()) ?? -1), child: const Text('Save')),
        ],
      ),
    );
    if (v == null || v < 0 || !mounted) return;
    await context.read<AppProvider>().setAiCoachBalance(v);
    if (widget.embeddedData != null) {
      widget.onReload?.call();
    } else {
      _load();
    }
  }

  Future<void> _editPlan(Map<String, dynamic> cfg) async {
    String f(dynamic v) => (v is num && v > 0) ? v.toString() : '';
    final tgt = TextEditingController(text: f(cfg['target_usdt']));
    final cap = TextEditingController(text: f(cfg['loss_cap_usdt']));
    final mx = TextEditingController(text: f(cfg['max_open']));
    final gb = TextEditingController(text: f(cfg['giveback_pct']));
    Widget field(String label, TextEditingController c) => Padding(
          padding: const EdgeInsets.only(top: 8),
          child: TextField(
              controller: c,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              decoration: InputDecoration(labelText: label, isDense: true)),
        );
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("AI day plan (paper only)"),
        content: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            field('Daily target (USDT)', tgt),
            field('Daily loss cap (USDT)', cap),
            field('Max open AI trades', mx),
            field('Give-back after target (%)', gb),
            const SizedBox(height: 8),
            const Text('Empty or 0 = off. The AI decides everything else itself and writes the reason.', style: TextStyle(fontSize: 12)),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    double n(TextEditingController c) => double.tryParse(c.text.trim()) ?? 0.0;
    await context.read<AppProvider>().setAiPlanConfig({
      'target_usdt': n(tgt),
      'loss_cap_usdt': n(cap),
      'max_open': n(mx),
      'giveback_pct': n(gb) > 0 ? n(gb) : 50.0,
    });
    if (widget.embeddedData != null) {
      widget.onReload?.call();
    } else {
      _load();
    }
  }

  @override
  Widget build(BuildContext context) {
    super.build(context);
    final p = context.palette;
    final d = widget.embeddedData ?? _d;
    if (d == null) {
      return _card(p, Text('Loading AI Coach...', style: TextStyle(fontSize: 13, color: p.textMuted)));
    }
    final cmp = _m(d['compare']);
    final lr = _m(d['learned']);
    final sw = _m(d['sideways']);
    final minN = _i(d['min_n']);
    final n = _i(cmp['n']);
    final small = TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted);
    final best = _l(lr['best']);
    final worst = _l(lr['worst']);
    final opens = _l(d['open']);
    final memo = _l(d['memo']);
    final closed = _l(d['closed']);
    final xl = _m(d['exit_learn']);
    final xlBook = _l(xl['book']);
    final xlHold = _l(xl['hold']);
    final mg = _m(d['margin']);
    final pl = _m(d['plan']);
    final plCfg = _m(pl['cfg']);
    final lv = _m(d['live']);
    final plJr = _l(pl['journal']);
    final plMr = _m(pl['mirror']);
    final cm = _m(d['coin_memory']);
    final cmCoins = _l(cm['coins']);
    final cmCtx = _m(cm['ctx']);
    final cmRows = _m(cmCtx['rows']);
    final td = _m(d['today']);
    // BOT numbers come LIVE from the same provider the Dashboard and the top pill use, so they can never differ
    // from them (the cached coach data can be a few minutes old). AI numbers come from the coach data.
    final prov = context.watch<AppProvider>();
    final liveBot = prov.statsMode != 'live';
    Widget todayCol(String name, double closed, double open, {bool live = false}) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(name, style: small),
            Text(_usdt(closed), style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: _col(p, closed))),
            Text('Open ${_usdt(open)}${live ? ' (live)' : ''}',
                style: small.copyWith(color: p.textMuted.withOpacity(0.75), fontSize: 11)),
          ]),
        );
    final topW = <Widget>[
      if (opens.isNotEmpty) _decisionCard(p, opens),
      if (td['ok'] == true)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'TODAY (closed trades, same as Dashboard)'),
            Row(children: [
              todayCol('BOT closed today', liveBot ? prov.closedPnl : _n(_m(td['bot'])['closed']),
                  liveBot ? prov.openPnl : _n(_m(td['bot'])['open']), live: true),
              todayCol('AI closed today', _n(_m(td['ai'])['closed']), _n(_m(td['ai'])['open'])),
            ]),
            const SizedBox(height: 6),
            Text('Big number = trades that already closed today. Open trades are the small grey number and can still change. '
                'The BOT number is exactly the Dashboard number. The scoreboard below covers the last finished signals, not just today.', style: small),
          ]),
        ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: _title(p, 'AI DAY PLAN (5:30 AM to 5:30 AM IST, paper)')),
            TextButton(onPressed: () => _editPlan(plCfg), child: const Text('Edit')),
          ]),
          if (lv.containsKey('today_pnl'))
            Padding(
              padding: const EdgeInsets.only(bottom: 6),
              child: Text(
                  'REAL account (AI own key): ${_n(lv['today_pnl']) >= 0 ? '+' : ''}${_n(lv['today_pnl']).toStringAsFixed(2)} USDT closed today '
                  '(${_n(lv['today_n']).round()} trades), ${_n(lv['open_n']).round()} open (${_n(lv['upnl']).toStringAsFixed(2)}). '
                  '${lv['on'] == true ? 'Real trading is ON.' : 'Real trading is OFF.'} The daily loss cap for real money is set on the real trading screen; this plan runs on paper.',
                  style: small.copyWith(color: _col(p, _n(lv['today_pnl'])), fontWeight: FontWeight.w700)),
            ),
          if (pl['on'] != true)
            Text('Not set. Tap Edit and give the AI a daily target and a loss cap. Until then it just takes the same signals as the bot.', style: small)
          else ...[
            Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Today (closed + open)', style: small),
                  Text(_usdt(_n(pl['day_pnl'])),
                      style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: _col(p, _n(pl['day_pnl'])))),
                ]),
              ),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Target ${_n(plCfg['target_usdt']) > 0 ? _n(plCfg['target_usdt']).toStringAsFixed(2) : 'off'}', style: small),
                  Text(pl['target_pct'] == null ? '-' : '${_n(pl['target_pct']).toStringAsFixed(0)}% done',
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: p.textPrimary)),
                ]),
              ),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Loss left', style: small),
                  Text(pl['loss_left'] == null ? '-' : _n(pl['loss_left']).toStringAsFixed(2),
                      style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: p.textPrimary)),
                ]),
              ),
            ]),
            if (pl['target_pct'] != null) ...[
              const SizedBox(height: 8),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(value: (_n(pl['target_pct']) / 100).clamp(0.0, 1.0).toDouble(), minHeight: 6),
              ),
            ],
            const SizedBox(height: 8),
            Text('Mode: ${pl['mode']}  |  ${_n(pl['hours_left']).toStringAsFixed(1)} h left in this day',
                style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
            if ('${pl['why'] ?? ''}'.isNotEmpty) Text('${pl['why']}', style: small),
          ],
          const SizedBox(height: 8),
          Text('REVENGE MIRROR', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          const SizedBox(height: 4),
          Text(
              'Right after a loss: ${_i(_m(plMr['after_loss'])['n'])} trades, ${_i(_m(plMr['after_loss'])['wins'])} won   |   '
              'Same coin again: ${_i(_m(plMr['same_coin'])['n'])}, ${_i(_m(plMr['same_coin'])['wins'])} won   |   '
              'Others: ${_i(_m(plMr['other'])['n'])}, ${_i(_m(plMr['other'])['wins'])} won',
              style: TextStyle(fontSize: 12, height: 1.3, color: p.textPrimary)),
          const SizedBox(height: 2),
          Text('${plMr['text'] ?? ''}', style: small),
          const SizedBox(height: 8),
          Text('WHY THE AI DID WHAT IT DID', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          const SizedBox(height: 4),
          if (plJr.isEmpty) Text('Nothing yet. The AI writes a line for every signal it takes or skips.', style: small),
          for (final r in plJr.take(8)) Padding(
            padding: const EdgeInsets.only(bottom: 3),
            child: Text('${_m(r)['text']}', style: TextStyle(fontSize: 12, height: 1.3, color: p.textPrimary)),
          ),
          const SizedBox(height: 6),
          Text('Only two hard rules: the loss cap and max open trades. Everything else is the AI\'s own call. Reaching for the target never makes it take bigger risk.',
              style: small),
        ]),
      ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'SCOREBOARD: AI (own exits) vs BOT (fixed rules)'),
          if (n == 0)
            Text('Collecting data: 0 of $minN finished trades. The AI has ${_i(cmp['open'])} trades open. The first comparison appears when one of them closes.',
                style: TextStyle(fontSize: 13, height: 1.35, color: p.textPrimary))
          else ...[
            Row(children: [
              Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('AI (manages its own exit)', style: small),
                Text(_usdt(cmp['ai_pnl']), style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: _col(p, _n(cmp['ai_pnl'])))),
                Text('Wins: ${_i(cmp['ai_wins'])} of $n trades', style: small),
              ])),
              Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('BOT (fixed rules)', style: small),
                Text(_usdt(cmp['bot_pnl']), style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: _col(p, _n(cmp['bot_pnl'])))),
                Text('Wins: ${_i(cmp['bot_wins'])} of $n trades', style: small),
              ])),
            ]),
            const SizedBox(height: 6),
            Text(
                'Total profit/loss in USDT on the same $n signals.${cmp['ready'] == true ? '' : '  Too early to judge: $n of $minN trades needed.'}'
                '${_i(sw['n']) > 0 ? '  Sideways trades (30+ min with almost no move): ${_i(sw['n'])}, average ${_i(sw['avg_min'])} min.' : ''}',
                style: small),
          ],
        ]),
      ),
    ];
    final midW = <Widget>[
      _card(
        p,
        InkWell(
          onTap: () => _editBalance(_n(mg['balance'])),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'MARGIN (tap to change the AI balance)'),
            Text(
                'Balance ${_n(mg['balance']).toStringAsFixed(0)} USDT${mg['custom'] == true ? '' : ' (default: 20 trades)'} | per trade ${_n(mg['per_trade']).toStringAsFixed(0)} | '
                'used ${_n(mg['used']).toStringAsFixed(0)} | free ${_n(mg['free']).toStringAsFixed(0)} | ${_i(mg['open'])}/${_i(mg['slots'])} slots',
                style: TextStyle(fontSize: 12.5, height: 1.35, color: p.textPrimary, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            Text(
                _i(mg['skipped']) == 0 && _i(mg['freed']) == 0
                    ? 'When margin runs out, the AI first closes a sideways trade to make room. If there is none, it skips the new signal. This has not happened yet.'
                    : 'Signals skipped: ${_i(mg['skipped'])} (the bot made ${_usdt(mg['skipped_bot_pnl'])} USDT on them, ${_i(mg['skipped_done'])} finished). '
                        'Closed to make room: ${_i(mg['freed'])}${mg['freed_after_avg'] == null ? '' : ' (after closing, price moved another ${_pct(mg['freed_after_avg'])} on average)'}.',
                style: TextStyle(fontSize: 11.5, height: 1.35, color: p.textMuted)),
          ]),
        ),
      ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'WHEN TO EXIT, WHEN TO HOLD (learned from finished trades)'),
          Text('${_i(xl['studied'])} finished trades studied. For every candle the AI asked: close now, or keep managing the trade normally - which paid more?',
              style: small),
          const SizedBox(height: 4),
          Text(
              'Bigger trend (1h/4h/1d) learned so far: ${_i(_m(xl['ctx_obs'])['W'])} signals WITH it, ${_i(_m(xl['ctx_obs'])['A'])} AGAINST it, ${_i(_m(xl['ctx_obs'])['O'])} sideways/mixed. '
              'A trade is judged by its own group only after that group has 24+ trades with the same result in both halves; before that the normal table decides.',
              style: small),
          const SizedBox(height: 8),
          if (xlBook.isEmpty && xlHold.isEmpty)
            Text('Still collecting: no situation has enough trades yet (24+, same result in both halves of the data). Until then the AI uses its older rules.',
                style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
          if (xlBook.isNotEmpty) ...[
            Text('CLOSE NOW BEATS HOLDING', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.loss)),
            const SizedBox(height: 4),
            for (final r in xlBook)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(child: Text('${_m(r)['text']}', style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textPrimary))),
                  const SizedBox(width: 8),
                  Text('+${_n(_m(r)['avg']).abs().toStringAsFixed(1)}% ROI\n${_i(_m(r)['n'])} trades', textAlign: TextAlign.right,
                      style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: p.loss)),
                ]),
              ),
          ],
          if (xlHold.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('HOLDING BEATS CLOSING NOW', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.profit)),
            const SizedBox(height: 4),
            for (final r in xlHold)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Expanded(child: Text('${_m(r)['text']}', style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textPrimary))),
                  const SizedBox(width: 8),
                  Text('+${_n(_m(r)['avg']).toStringAsFixed(1)}% ROI\n${_i(_m(r)['n'])} trades', textAlign: TextAlign.right,
                      style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: p.profit)),
                ]),
              ),
          ],
          const SizedBox(height: 6),
          Text('The % is how much better that choice paid than the other one, on average, at your leverage (fee is the same for both). Past trades are not a promise.',
              style: small),
        ]),
      ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'BIGGER PICTURE: EACH COIN'),
          Text('COINS THE AI IS STUDYING (${_i(cm['total'])})', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          const SizedBox(height: 4),
          if (cmCoins.isEmpty)
            Text('Still collecting: coin history fills up as the Shadow Lab replays old signals and the AI closes trades.', style: small),
          for (final r in cmCoins)
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(children: [
                Expanded(
                  child: Text('${_m(r)['sym']}${_m(r)['open'] == true ? '  (open)' : ''}',
                      style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
                ),
                Text('${_i(_m(r)['n'])} trades  ${_n(_m(r)['avg_roi']) >= 0 ? '+' : ''}${_n(_m(r)['avg_roi']).toStringAsFixed(1)}%  ',
                    style: small),
                Text('${_m(r)['status']}',
                    style: TextStyle(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w800,
                        color: _m(r)['status'] == 'Trusted'
                            ? p.profit
                            : (_m(r)['status'] == 'Avoid' ? p.loss : p.textMuted))),
              ]),
            ),
          const SizedBox(height: 8),
          Text('WITH vs AGAINST THE BIGGER TREND (AI trades)', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textMuted)),
          const SizedBox(height: 4),
          Text(
              'With: ${_i(_m(cmRows['WITH'])['n'])} trades${_m(cmRows['WITH'])['avg'] == null ? '' : ', avg ${_n(_m(cmRows['WITH'])['avg']).toStringAsFixed(1)}% ROI'}   |   '
              'Against: ${_i(_m(cmRows['AGAINST'])['n'])} trades${_m(cmRows['AGAINST'])['avg'] == null ? '' : ', avg ${_n(_m(cmRows['AGAINST'])['avg']).toStringAsFixed(1)}% ROI'}',
              style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textPrimary)),
          const SizedBox(height: 4),
          Text('${cmCtx['text'] ?? ''}', style: small),
          const SizedBox(height: 6),
          Text('Status needs 8+ trades in each half of the data. This is information for the AI and for you, not a rule: no trade is blocked because of it.',
              style: small),
        ]),
      ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'WHAT THE AI LEARNED (Z-score, TSI, SD combinations)'),
          Text('${_i(lr['samples'])} samples | normal: in ${_i(lr['base'])}% of cases the next 3 candles go with the trade | ${_i(lr['trusted'])} situations have $minN+ cases',
              style: small),
          const SizedBox(height: 8),
          if (best.isEmpty && worst.isEmpty)
            Text('Still collecting: no situation has reached $minN cases yet, so there is no verdict.',
                style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
          if (best.isNotEmpty) ...[
            Text('USUALLY GO WITH THE TRADE', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.profit)),
            const SizedBox(height: 4),
            for (final r in best) _learnRow(p, _m(r), p.profit),
          ],
          if (worst.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('USUALLY TURN AGAINST THE TRADE', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.loss)),
            const SizedBox(height: 4),
            for (final r in worst) _learnRow(p, _m(r), p.loss),
          ],
          const SizedBox(height: 6),
          Text('No rule was written by hand: the AI counts how every indicator fact (and every pair of facts) behaved. It only exits on a learned situation after ${_i(lr['exit_min_n'])}+ cases. Until then it uses the basic rule only.',
              style: small),
        ]),
      ),
      _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'LOG: WHAT HAPPENED WHEN'),
          if (memo.isEmpty) Text('Nothing logged yet.', style: small),
          for (final raw in memo.take(14))
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Text('${_hm(_m(raw)['t'])}  ${_m(raw)['text']}', style: TextStyle(fontSize: 12, height: 1.3, color: p.textPrimary)),
            ),
        ]),
      ),
    ];
    final tradesW = <Widget>[
      if (opens.isNotEmpty)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'AI TRADES OPEN NOW'),
            for (final raw in opens)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text('${_m(raw)['sym']} ${_m(raw)['side'] == 'BUY' ? 'LONG' : 'SHORT'}', style: const TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800))),
                    Text(_pct(_m(raw)['roi']), style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w800, color: _col(p, _n(_m(raw)['roi'])))),
                  ]),
                  Text('peak ${_pct(_m(raw)['peak'])} | TP${_i(_m(raw)['hit']) == 0 ? '-' : _i(_m(raw)['hit'])} | ${_i(_m(raw)['min'])} min${_m(raw)['be'] == true ? ' | stop at entry' : ''}', style: small),
                  const SizedBox(height: 4),
                  Wrap(children: [for (final f in _l(_m(raw)['facts'])) _chip(p, '$f')]),
                  if ('${_m(raw)['read'] ?? ''}'.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text('AI reads now: ${_m(raw)['read']}', style: small),
                  ],
                  if ('${_m(raw)['hold'] ?? ''}'.isNotEmpty) Text('${_m(raw)['hold']}', style: small),
                ]),
              ),
          ]),
        ),
      if (closed.isNotEmpty)
        _card(
          p,
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'FINISHED TRADES: AI vs BOT'),
            for (final raw in closed.take(12))
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [
                    Expanded(child: Text('${_m(raw)['sym']} ${_m(raw)['side'] == 'BUY' ? 'LONG' : 'SHORT'}', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800))),
                    Text('AI ${_pct(_m(raw)['roi'])}', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: _col(p, _n(_m(raw)['roi'])))),
                    const SizedBox(width: 10),
                    Text(_m(raw)['bot_roi'] == null ? 'Bot: still open' : 'Bot ${_pct(_m(raw)['bot_roi'])}',
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: _m(raw)['bot_roi'] == null ? p.textMuted : _col(p, _n(_m(raw)['bot_roi'])))),
                  ]),
                  Text('${_m(raw)['reason']}${(_m(raw)['mode'] ?? '-') != '-' ? ' [${_m(raw)['mode']}]' : ''}', style: TextStyle(fontSize: 11.5, height: 1.3, color: p.textPrimary)),
                  Text((_m(raw)['after'] ?? '').toString().isEmpty ? 'watching price after the exit...' : '${_m(raw)['after']}', style: small),
                ]),
              ),
          ]),
        ),
    ];
    final shown = widget.part == 'top' ? topW : (widget.part == 'rest' ? midW : [...topW, ...midW, ...tradesW]);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: shown);
  }
}


/// RISK TICKS: a one-line ladder in R multiples. Red tick = original stop (-1R), grey = entry (0R), green = TP1..TP4,
/// white dot = price now, thick tick = where the AI's stop is now. Display only.
class _RiskLadder extends StatelessWidget {
  final AppPalette p;
  final double? now, stop;
  final List<double?> tps;
  const _RiskLadder({required this.p, required this.now, required this.stop, required this.tps});

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 50,
        width: double.infinity,
        child: CustomPaint(painter: _RiskLadderPainter(p, now, stop, tps)),
      );
}

class _RiskLadderPainter extends CustomPainter {
  final AppPalette p;
  final double? now, stop;
  final List<double?> tps;
  _RiskLadderPainter(this.p, this.now, this.stop, this.tps);

  void _label(Canvas c, String t, double x, double y, Color col, double w) {
    final tp = TextPainter(text: TextSpan(text: t, style: TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: col)), textDirection: TextDirection.ltr)..layout();
    tp.paint(c, Offset((x - tp.width / 2).clamp(0.0, math.max(0.0, w - tp.width)).toDouble(), y));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final vals = <double>[-1.0, 0.0, ...tps.whereType<double>(), if (now != null) now!, if (stop != null) stop!];
    final lo = vals.reduce(math.min) - 0.25;
    final hi = vals.reduce(math.max) + 0.25;
    final span = hi - lo;
    if (span <= 0) return;
    double x(double v) => 10 + (size.width - 20) * (v - lo) / span;
    const y = 20.0;
    canvas.drawRect(Rect.fromLTRB(x(lo), y - 2, x(0), y + 2), Paint()..color = p.loss.withOpacity(0.35));
    canvas.drawRect(Rect.fromLTRB(x(0), y - 2, x(hi), y + 2), Paint()..color = p.profit.withOpacity(0.35));
    void tick(double v, String t, Color col) {
      canvas.drawLine(Offset(x(v), y - 6), Offset(x(v), y + 6), Paint()..color = col..strokeWidth = 1.5);
      _label(canvas, t, x(v), y + 9, col, size.width);
    }

    tick(-1.0, 'SL -1R', p.loss);
    tick(0.0, 'ENTRY', p.textMuted);
    for (var i = 0; i < tps.length; i++) {
      final v = tps[i];
      if (v != null) tick(v, 'TP${i + 1}', p.profit);
    }
    if (stop != null) {
      canvas.drawLine(Offset(x(stop!), y - 12), Offset(x(stop!), y + 3), Paint()..color = (stop! >= 0 ? p.profit : p.loss)..strokeWidth = 3);
      _label(canvas, 'stop', x(stop!), 0, stop! >= 0 ? p.profit : p.loss, size.width);
    }
    if (now != null) {
      canvas.drawCircle(Offset(x(now!), y), 5, Paint()..color = p.textPrimary);
      canvas.drawCircle(Offset(x(now!), y), 5, Paint()..color = p.border..style = PaintingStyle.stroke..strokeWidth = 1);
    }
  }

  @override
  bool shouldRepaint(covariant _RiskLadderPainter o) => o.now != now || o.stop != stop || '${o.tps}' != '$tps';
}
