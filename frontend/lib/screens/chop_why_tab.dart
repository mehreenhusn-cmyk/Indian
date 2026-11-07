import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_button.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import '../widgets/owl_status_pill.dart';
import 'chop_plain.dart';

Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _ml(dynamic v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
String _s(dynamic v) => v == null ? '' : '$v';
String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';
String _ist(dynamic ts) {
  if (ts is! num) return '';
  final d = DateTime.fromMillisecondsSinceEpoch(ts.toInt() * 1000, isUtc: true).add(const Duration(hours: 5, minutes: 30));
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  String two(int x) => x < 10 ? '0$x' : '$x';
  return '${two(d.day)} ${mon[d.month - 1]} ${two(d.hour)}:${two(d.minute)}';
}

/// Part C4b (README_CHOP): the WHY tab of the b3 (Chop Bot) screen. PAPER ONLY, nothing here sends an order.
/// Missed Rally alarm, Skip Ledger, rule report, weight suggestions with the OK button, b3 vs the current bot, and the C2 replay table (5m / 15m, today / month / all).
/// [main] is the last GET /api/v2/chop answer of the parent (today / all numbers of b3). Reads /api/v2/chop_report, /api/calendar?bot=b1 and /api/v2/chop_lab.
/// Writes only: the OK button (chop_apply, asks first) and "Run replay". Created only while the Why tab is open, so it polls only then. Dart NOT compiled.
class ChopWhyTab extends StatefulWidget {
  final Map<String, dynamic> main;
  const ChopWhyTab({super.key, required this.main});

  @override
  State<ChopWhyTab> createState() => _ChopWhyTabState();
}

class _ChopWhyTabState extends State<ChopWhyTab> {
  static Map<String, dynamic> _cacheRep = {};
  static Map<String, dynamic> _cacheCur = {};
  Map<String, dynamic> _rep = Map<String, dynamic>.from(_cacheRep);
  Map<String, dynamic> _cur = Map<String, dynamic>.from(_cacheCur);
  Map<String, dynamic> _lab = {};
  Map<String, dynamic> _same = {};
  String _iv = '5m', _per = 'month';
  bool _polling = false, _applying = false, _starting = false, _loaded = false;
  String _err = '';
  int _tick = 0;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool _bad(Map<String, dynamic> r) => r['state'] != null || r['error'] != null;

  Future<void> _poll({bool lab = false}) async {
    if (!mounted || _polling) return;
    _polling = true;
    try {
      final pr = context.read<AppProvider>();
      final running = _m(_lab['job'])['running'] == true;
      final doLab = lab || running || _tick % 6 == 0;
      final rep = await pr.fetchChopReport();
      final cur = _tick % 3 == 0 ? await pr.fetchChopCurrentBot() : null;
      final same = _tick % 3 == 0 ? await pr.fetchChopSame() : null;
      final lb = doLab ? await pr.fetchChopLab(_iv, _per) : null;
      _tick++;
      if (!mounted) return;
      setState(() {
        _loaded = true;
        if (_bad(rep)) {
          _err = _s(rep['state']) == 'off' ? 'The V2 data API is off.' : _s(rep['state']) == 'old' ? 'This backend has no b3 report route yet.' : 'Cannot reach the backend right now.';
        } else {
          _err = '';
          _rep = rep;
          _cacheRep = rep;
        }
        if (cur != null && !_bad(cur)) {
          _cur = cur;
          _cacheCur = cur;
        }
        if (lb != null && !_bad(lb)) _lab = lb;
        if (same != null && !_bad(same)) _same = same;
      });
    } finally {
      _polling = false;
    }
  }

  void _snack(String t) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t)));

  Future<void> _apply() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Save new weights?'),
        content: const Text('This saves the proposed Quality Score weights to chop_b3_weights.json. b3 uses them from its next decision. Paper only. The backend refuses if train and test do not agree.'),
        actions: [TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')), TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('OK, save'))],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _applying = true);
    final r = await context.read<AppProvider>().postChopApply();
    if (!mounted) return;
    setState(() => _applying = false);
    _snack(r['saved'] == true ? 'Saved ${(r['changes'] as List?)?.length ?? 0} weight change(s).' : _s(r['note']).isNotEmpty ? _s(r['note']) : 'Not saved. ${_s(r['error'])}');
    _poll();
  }

  Future<void> _runLab() async {
    if (_starting) return;
    setState(() => _starting = true);
    final r = await context.read<AppProvider>().postChopLab(_iv, _per);
    if (!mounted) return;
    setState(() => _starting = false);
    _snack(r['note'] != null ? '${r['note']}' : 'Could not start the replay.');
    _poll(lab: true);
  }

  void _pick(String iv, String per) {
    setState(() {
      _iv = iv;
      _per = per;
      _lab = {};
    });
    _poll(lab: true);
  }

  // ------------------------------------------------------------------ build
  @override
  Widget build(BuildContext context) {
    if (!_loaded && _rep.isEmpty) return const Padding(padding: EdgeInsets.all(AppSpacing.xl), child: Center(child: CircularProgressIndicator()));
    final all = _m(widget.main['all']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: AppSpacing.s), child: _note(context, _err, bad: true)),
      ..._alarm(context),
      OwlSectionLabel('Skip Ledger', note: 'all time'),
      _ledger(context, all),
      const OwlSectionLabel('Rule report'),
      ..._rules(context),
      const OwlSectionLabel('Learning'),
      ..._learning(context),
      const OwlSectionLabel('b3 vs current bot'),
      _versus(context),
      const OwlSectionLabel('Replay (C2)'),
      ..._labBlock(context),
    ]);
  }

  Widget _note(BuildContext context, String text, {bool bad = false}) {
    final p = context.palette;
    return OWLCard(edge: bad ? p.warning : null, padding: const EdgeInsets.all(AppSpacing.m), child: Text(text, style: context.type.secondary));
  }

  Widget _rowBox(Widget child) => Padding(padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.rowPadV), child: child);

  Widget _kv(BuildContext context, String k, String v, {Color? c}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: context.type.secondary)),
          Text(v, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: c)),
        ]),
      );

  // ------------------------------------------------------------------ Missed Rally alarm
  List<Widget> _alarm(BuildContext context) {
    final p = context.palette;
    final rows = _ml(_rep['missed_rallies']);
    final pct = _n(_rep['alarm_pct']);
    if (rows.isEmpty) {
      return [const OwlSectionLabel('Missed Rally alarm'), _note(context, 'No missed rally yet. The alarm rings when a skipped signal would have made ${pct == 0 ? 1 : pct}% or more.')];
    }
    return [
      OwlSectionLabel('Missed Rally alarm', note: '${rows.length}'),
      OWLCard(
        edge: p.warning,
        padding: EdgeInsets.zero,
        child: Column(children: [
          for (var i = 0; i < rows.length; i++) ...[
            if (i > 0) Divider(height: 1, color: p.border),
            _rowBox(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Text(_s(rows[i]['symbol']), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(width: 6),
                OWLStatusPill(text: _s(rows[i]['side']), color: rows[i]['side'] == 'BUY' ? p.profit : p.loss, showDot: false),
                const Spacer(),
                Text('would have made ${_usdt(_n(rows[i]['v_net']))}%', style: context.type.primary.copyWith(color: p.warning, fontWeight: FontWeight.w700)),
              ]),
              const SizedBox(height: 3),
              Text('Skipped: ${chopRuleName(_s(rows[i]['rule']))}. ${chopPlainWhy(rows[i])}', maxLines: 4, overflow: TextOverflow.ellipsis, style: context.type.secondary),
              Text('${_ist(rows[i]['candle_ts'])}  score ${_n(rows[i]['score']).toStringAsFixed(0)}  it would have ended: ${chopExitName(_s(rows[i]['v_exit']))}', style: context.type.caption),
            ])),
          ],
        ]),
      ),
    ];
  }

  // ------------------------------------------------------------------ Skip Ledger
  Widget _ledger(BuildContext context, Map<String, dynamic> all) {
    final p = context.palette;
    final rm = _n(all['rally_missed_usdt']), la = _n(all['loss_avoided_usdt']);
    final net = la - rm;
    final judged = _n(all['rally_missed_n']) + _n(all['loss_avoided_n']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _kv(context, 'Rally missed (${_n(all['rally_missed_n']).toInt()} skips)', '${_usdt(rm)} USDT', c: p.warning),
        _kv(context, 'Loss avoided (${_n(all['loss_avoided_n']).toInt()} skips)', '${_usdt(la)} USDT', c: p.profit),
        Divider(height: AppSpacing.l, color: p.border),
        _kv(context, 'Filter effect (avoided minus missed)', '${_usdt(net)} USDT', c: net >= 0 ? p.profit : p.loss),
        const SizedBox(height: 4),
        Text(
          judged == 0
              ? 'No skip has a verdict yet. A skip is judged when its stop or target is touched, or after 24 candles.'
              : net >= 0
                  ? 'So far the skips saved more than they cost.'
                  : 'So far the skips cost more than they saved. Watch the rule report below for which rule is too strict.',
          style: context.type.metadata,
        ),
        if (_n(all['skips_waiting']) > 0) Text('${_n(all['skips_waiting']).toInt()} skips are still waiting for their verdict.', style: context.type.caption),
        const SizedBox(height: 4),
        Text('What-if at full size (10 USDT), after cost. Not real trades.', style: context.type.caption),
      ]),
    );
  }

  // ------------------------------------------------------------------ rule report
  List<Widget> _rules(BuildContext context) {
    final p = context.palette;
    final rows = _ml(_rep['rules']);
    if (rows.isEmpty) return [_note(context, 'No judged decisions yet.')];
    return [
      OwlListCard(children: [
        for (final r in rows)
          _rowBox(Row(children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${r['action'] == 'TAKE' ? 'Taken' : 'Skipped'}: ${chopRuleName(_s(r['rule']))}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w600)),
                Text('${_n(r['judged']).toInt()} judged, ${_n(r['right']).toInt()} right, ${_n(r['wrong']).toInt()} wrong (${_s(r['right_pct'])}% right)', style: context.type.metadata),
              ]),
            ),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${_usdt(_n(r['usdt']))} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: _n(r['usdt']) >= 0 ? p.profit : p.loss)),
              Text(_s(r['says']), style: context.type.caption),
            ]),
          ])),
      ]),
    ];
  }

  // ------------------------------------------------------------------ learning
  List<Widget> _learning(BuildContext context) {
    final l = _m(_rep['learning']);
    if (l.isEmpty) return [_note(context, 'No learning data yet.')];
    final enough = l['enough'] == true;
    final changes = _ml(l['changes']);
    final nw = _m(l['new_weights']);
    final cw = _m(l['current_weights']);
    return [
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${_n(l['rows']).toInt()} judged decisions. ${enough ? 'Enough to look for a change.' : _s(l['note'])}', style: context.type.secondary),
          const SizedBox(height: 4),
          Text('b3 never changes itself. It proposes a change only when the first 60% and the last 40% of the data agree, at most 15% per weight. You say OK, then the file is written.', style: context.type.caption),
          if (cw.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.s),
            Text('Weights now: ${cw.entries.map((e) => '${e.key} ${_n(e.value).toStringAsFixed(0)}').join(', ')}', style: context.type.metadata),
          ],
          if (enough && changes.isEmpty) Padding(padding: const EdgeInsets.only(top: AppSpacing.s), child: Text('No change is supported by both parts yet. Keep the weights.', style: context.type.secondary)),
          for (final c in changes)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.s),
              child: Row(children: [
                Expanded(child: Text('${_s(c['part'])}: ${_s(c['old'])} -> ${_n(nw[c['part']]).toStringAsFixed(1)}', style: context.type.primary.copyWith(fontWeight: FontWeight.w600))),
                Text('train ${_usdt(_n(c['train_edge_pct']))}%  test ${_usdt(_n(c['test_edge_pct']))}%', style: context.type.caption),
              ]),
            ),
          if (enough && changes.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.m),
            OWLButton(text: 'OK, save new weights', isLoading: _applying, onPressed: _applying ? null : _apply, icon: Icons.check_rounded, isFullWidth: true),
          ],
        ]),
      ),
    ];
  }

  // ------------------------------------------------------------------ b3 vs current bot
  Widget _versus(BuildContext context) {
    final p = context.palette;
    final t = _m(widget.main['today']);
    final all = _m(widget.main['all']);
    final days = _ml(_cur['days']);
    final todayKey = _s(_cur['today']);
    Map<String, dynamic> day = {};
    for (final d in days) {
      if (_s(d['date']) == todayKey) day = d;
    }
    if (_cur.isEmpty) return _note(context, 'The current bot numbers are not loaded yet (GET /api/calendar?bot=b1).');
    String wp(num w, num n) => n == 0 ? '-' : '${(100 * w / n).toStringAsFixed(0)}%';
    Widget col(String title, String profit, String trades, String win, Color c) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(profit, style: context.type.number.copyWith(color: c)),
            Text('$trades trades, $win won', style: context.type.metadata),
          ]),
        );
    final bTradesToday = _n(t['closed']).toInt(), bTradesAll = _n(all['closed']).toInt();
    final bp = _n(t['profit_usdt']), cp = _n(day['pnl']);
    final ba = _n(all['profit_usdt']), cm = _n(_cur['month_pnl']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (bTradesAll == 0)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text('b3 has not taken any trade yet, so there is nothing to compare. A 0.00 for b3 is not a loss, it only means no trade was taken. The current bot numbers below are for reference.', style: context.type.primary),
          )
        else if (bTradesToday == 0)
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text('b3 took no trade today. 0.00 means no trade, not a loss.', style: context.type.caption),
          ),
        Text('Today', style: context.type.label),
        const SizedBox(height: 4),
        Row(children: [
          col('b3 (5m)', bTradesToday == 0 ? 'No trade' : '${_usdt(bp)} USDT', '$bTradesToday', wp(_n(t['wins']), _n(t['closed'])), bTradesToday == 0 ? p.textMuted : (bp >= 0 ? p.profit : p.loss)),
          col('Current bot', '${_usdt(cp)} USDT', '${_n(day['trades']).toInt()}', wp(_n(day['wins']), _n(day['trades'])), cp >= 0 ? p.profit : p.loss),
        ]),
        Divider(height: AppSpacing.l, color: p.border),
        Text('All b3 data vs this month of the current bot', style: context.type.label),
        const SizedBox(height: 4),
        Row(children: [
          col('b3 (all)', bTradesAll == 0 ? 'No trade' : '${_usdt(ba)} USDT', '$bTradesAll', wp(_n(all['wins']), _n(all['closed'])), bTradesAll == 0 ? p.textMuted : (ba >= 0 ? p.profit : p.loss)),
          col('Current (${_s(_cur['month'])})', '${_usdt(cm)} USDT', '${_n(_cur['month_trades']).toInt()}', wp(_n(_cur['month_wins']), _n(_cur['month_trades'])), cm >= 0 ? p.profit : p.loss),
        ]),
        const SizedBox(height: AppSpacing.s),
        Text('Not the same clock or size: b3 day = UTC day, 10 / 5 USDT trades; the current bot day starts 5:30 AM IST. For a fair test use the replay below.', style: context.type.caption),
        if (_same['lines'] is List && (_same['lines'] as List).isNotEmpty) ...[
          const SizedBox(height: AppSpacing.s),
          Text('On the same signals', style: context.type.label.copyWith(fontWeight: FontWeight.w800)),
          for (final l in (_same['lines'] as List)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('$l', style: context.type.secondary)),
          const SizedBox(height: 4),
          Text('Matched by coin + side + opened within 15 minutes of the b3 signal. Only closed Current-bot trades. Sniper trades are left out.', style: context.type.caption),
        ],
      ]),
    );
  }

  // ------------------------------------------------------------------ replay table
  List<Widget> _labBlock(BuildContext context) {
    final p = context.palette;
    final job = _m(_lab['job']);
    final res = _lab['result'];
    final running = job['running'] == true;
    Widget chip(String label, bool on, VoidCallback f) => Padding(
          padding: const EdgeInsets.only(right: 6),
          child: ChoiceChip(label: Text(label), selected: on, onSelected: (_) => f()),
        );
    final out = <Widget>[
      Wrap(children: [for (final v in const ['5m', '15m']) chip(v, _iv == v, () => _pick(v, _per))]),
      Wrap(children: [for (final v in const ['today', 'month', 'all']) chip(v, _per == v, () => _pick(_iv, v))]),
      const SizedBox(height: AppSpacing.s),
    ];
    if (running) {
      out.add(_note(context, 'Replay running: ${_n(job['done']).toInt()} of ${_n(job['total']).toInt()} coins. It can take minutes on the phone.'));
      return out;
    }
    if (res is! Map) {
      out.add(_note(context, _s(job['error']).isNotEmpty ? 'The last replay failed: ${_s(job['error'])}' : 'No saved replay for $_iv / $_per yet.'));
    } else {
      final r = _m(res);
      final vs = _ml(r['variants']);
      out.add(Text('${_n(r['coins']).toInt()} coins, ${_n(r['days']).toInt()} days. Best: ${r['best'] ?? 'none proved yet'}. Nothing is applied.', style: context.type.metadata));
      out.add(const SizedBox(height: 6));
      out.add(OwlListCard(children: [
        for (final v in vs)
          _rowBox(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Expanded(child: Text(_s(v['name']), maxLines: 2, style: context.type.primary.copyWith(fontWeight: FontWeight.w600, color: v['name'] == r['best'] ? p.profit : null))),
              Text('${_usdt(_n(_m(v['all'])['profit_usdt']))} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: _n(_m(v['all'])['profit_usdt']) >= 0 ? p.profit : p.loss)),
            ]),
            Text('${_n(_m(v['all'])['trades']).toInt()} trades, ${_s(_m(v['all'])['win_pct'])}% won, avg ${_s(_m(v['all'])['avg_net_pct'])}%  |  test ${_usdt(_n(_m(v['test'])['profit_usdt']))} USDT', style: context.type.metadata),
            Text('rally capture ${_s(v['rally_capture_pct'])}%, loss avoided ${_s(v['loss_avoided_pct'])}%  |  missed ${_usdt(_n(v['rally_missed_usdt']))}, saved ${_usdt(_n(v['loss_avoided_usdt']))}', style: context.type.caption),
            if (_s(v['verdict']).isNotEmpty) Text(_s(v['verdict']), style: context.type.caption.copyWith(color: p.textSecondary)),
          ])),
      ]));
    }
    out.add(const SizedBox(height: AppSpacing.s));
    out.add(OWLButton(text: 'Run replay ($_iv / $_per)', isLoading: _starting, onPressed: _starting ? null : _runLab, icon: Icons.play_arrow_rounded, isFullWidth: true));
    out.add(Padding(padding: const EdgeInsets.only(top: 6), child: Text('Read only: it tests stored candles and changes no setting. To use a better cut-off, change FULL_CUT / HALF_CUT in chop_score.py.', style: context.type.caption)));
    return out;
  }
}
