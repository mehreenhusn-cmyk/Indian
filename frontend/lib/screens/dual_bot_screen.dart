import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/dual_trade_chart.dart';
import '../widgets/owl_route.dart';
import 'tag_lab_screen.dart';

/// Dual Bot screen (paper only). A separate bot that reads BOTH indicators (main EMA50 chart + the Z pane with the
/// Z-EMA cloud and black candle), learns by itself when to trade and how to exit, and shows what it earned.
/// No AI key is needed, so a key limit can never stop it. It never touches the live bot.
/// Everything comes from GET /api/dual_lab (backend dual_lab.py). The screen only polls while it is open.
class DualBotScreen extends StatefulWidget {
  const DualBotScreen({super.key});

  @override
  State<DualBotScreen> createState() => _DualBotScreenState();
}

class _DualBotScreenState extends State<DualBotScreen> {
  Map<String, dynamic> _st = {};
  String _err = '';
  bool _busy = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll({String action = ''}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final q = action.isEmpty ? '' : '?action=$action';
      final res = await http.get(Uri.parse('$base/api/dual_lab$q')).timeout(const Duration(seconds: 20));
      if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is! Map) throw 'unexpected reply';
      if (mounted) {
        setState(() {
          _st = Map<String, dynamic>.from(m);
          _err = '${_st['error'] ?? ''}';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    }
  }

  Future<void> _toggle(bool on) async {
    setState(() => _busy = true);
    await _poll(action: on ? 'start' : 'stop');
    if (mounted) setState(() => _busy = false);
  }

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)} USDT';

  Widget _card(AppPalette p, {required String title, required List<Widget> children, Color? edge}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: (edge ?? p.border).withOpacity(0.6)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.6)),
        const SizedBox(height: 8),
        ...children,
      ]),
    );
  }

  Widget _kv(String k, String v, {Color? color}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(children: [
        Expanded(child: Text(k, style: context.type.secondary)),
        Text(v, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: color)),
      ]),
    );
  }

  Widget _statusCard(AppPalette p) {
    final running = _st['running'] == true;
    final enabled = _st['enabled'] != false;
    final progress = '${_st['progress'] ?? ''}';
    return _card(p, title: 'DUAL BOT (PAPER)', edge: p.accent, children: [
      Text(
          'A separate bot that reads both indicators and learns by itself when to trade and how to exit. '
          'Paper only: ${_n(_st['margin']).toStringAsFixed(0)} USDT per trade at ${_n(_st['lev']).toStringAsFixed(0)}x. '
          'No AI key is needed, so a key limit cannot stop it. Your live bot is not touched.',
          style: context.type.metadata),
      const SizedBox(height: 8),
      Row(children: [
        Icon(Icons.circle, size: 10, color: running ? p.profit : (enabled ? p.warning : p.textMuted)),
        const SizedBox(width: 6),
        Expanded(
            child: Text(
                running ? 'Running' : (enabled ? (progress.isNotEmpty ? 'Loading history...' : 'Starting... (the backend starts it by itself)') : 'Stopped'),
                style: context.type.primary)),
        OutlinedButton(
          onPressed: _busy ? null : () => _toggle(!enabled),
          child: Text(enabled ? 'Stop' : 'Start'),
        ),
      ]),
      if (progress.isNotEmpty && enabled) Padding(padding: const EdgeInsets.only(top: 6), child: Text(progress, style: context.type.metadata)),
      if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
    ]);
  }

  Widget _modelCard(AppPalette p) {
    final m = _map(_st['model']);
    final rows = '${_st['rows'] ?? 0}';
    if (m.isEmpty) {
      return _card(p, title: 'WHAT IT HAS LEARNED', children: [
        Text('Still reading history ($rows situations so far). It needs about 150 before it starts to learn.', style: context.type.secondary),
      ]);
    }
    final learned = m['mode'] == 'LEARNED';
    final v = _map(m['val']);
    return _card(p, title: 'WHAT IT HAS LEARNED', edge: learned ? p.profit : p.warning, children: [
      Text(learned ? 'LEARNED' : 'STILL EXPLORING', style: context.type.section.copyWith(color: learned ? p.profit : p.warning, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text(
          learned
              ? 'On newer data it had never seen, the signals it chose earned more than taking every signal, and more than luck gives. It now skips signals it expects to lose.'
              : 'It has not yet beaten "take every signal" on new data (checked against luck). So it takes every signal and keeps learning. This is normal at the start.',
          style: context.type.secondary),
      const SizedBox(height: 8),
      _kv('Situations remembered', rows),
      _kv('Signals it would take (new data)', '${v['taken'] ?? 0} of ${v['test'] ?? 0}'),
      _kv('Average per trade, its choice', '${_n(v['taken_avg']).toStringAsFixed(2)} ROI%'),
      _kv('Average per trade, take everything', '${_n(v['all_avg']).toStringAsFixed(2)} ROI%'),
      _kv('Luck check (best shuffle gain)', '${_n(v['luck_max']).toStringAsFixed(2)} ROI%'),
      _kv('Exit that earned most overall', '${m['best_exit'] ?? '-'}'),
    ]);
  }

  Widget _resultCard(AppPalette p) {
    final s = _map(_st['summary']);
    final closed = (s['closed'] ?? 0) as num;
    final wins = (s['wins'] ?? 0) as num;
    final pnl = _n(s['pnl']);
    final skipped = _n(s['skipped_pnl']);
    final bySrc = _map(s['by_src']);
    const names = {'MAIN': 'Main chart signal (your bot)', 'Z': 'Z black candle only', 'BOTH': 'Both on the same candle'};
    return _card(p, title: 'LIVE PAPER RESULT', children: [
      _kv('Finished trades', '$closed'),
      _kv('Win rate', closed > 0 ? '${(100 * wins / closed).toStringAsFixed(0)}%' : '-'),
      _kv('Profit / loss', _usdt(pnl), color: pnl >= 0 ? p.profit : p.loss),
      _kv('Open now', '${s['open'] ?? 0}  (${_usdt(_n(s['open_pnl']))})'),
      const SizedBox(height: 4),
      Text('Skipped signals (still followed)', style: context.type.label),
      const SizedBox(height: 2),
      Text(
          (s['skipped_done'] ?? 0) == 0
              ? 'None finished yet.'
              : '${s['skipped_done']} finished. They would have made ${_usdt(skipped)}. '
                  '${skipped < 0 ? 'So skipping them saved money.' : 'So skipping them cost profit.'}',
          style: context.type.secondary),
      if (bySrc.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('By signal type', style: context.type.label),
        const SizedBox(height: 2),
        for (final e in bySrc.entries)
          _kv('${names[e.key] ?? e.key}', '${_map(e.value)['n']} trades, ${_usdt(_n(_map(e.value)['pnl']))}',
              color: _n(_map(e.value)['pnl']) >= 0 ? p.profit : p.loss),
      ],
    ]);
  }

  Widget _insightRows(AppPalette p, List<Map<String, dynamic>> l) {
    if (l.isEmpty) return Text('Not enough history yet.', style: context.type.secondary);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final g in l)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${g['name']}', style: context.type.primary.copyWith(height: 1.3)),
              Text(
                  '${g['n']} trades. Best exit "${g['exit']}": ${_n(g['best']).toStringAsFixed(1)} ROI% per trade. '
                  'Bot exit: ${_n(g['bot']).toStringAsFixed(1)}. ${g['both_halves'] == true ? 'Positive in older and newer data.' : 'Not proven in both halves.'}',
                  style: context.type.metadata),
            ]),
          ),
      ],
    );
  }

  Widget _situationsCard(AppPalette p) {
    final ins = _map(_st['insights']);
    return _card(p, title: 'SITUATIONS (FOUND BY THE BOT, NOT TYPED BY YOU)', children: [
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: Column(children: [
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Best situations', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_insightRows(p, _maps(ins['best']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Worst situations', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_insightRows(p, _maps(ins['worst']))],
          ),
        ]),
      ),
      Text('Plain counting on old replays, fee inside. A situation is only strong if it is positive in both older and newer data.',
          style: context.type.metadata),
    ]);
  }

  // ---- Today (same day as Dashboard: 5:30 AM IST to 5:30 AM IST) ----
  Widget _todayCard(AppPalette p) {
    final t = _map(_map(_st['summary'])['today']);
    if (t.isEmpty) return const SizedBox.shrink();
    final total = _n(t['total']);
    final up = total >= 0;
    return _card(p, title: 'TODAY (5:30 AM IST TO 5:30 AM IST)', edge: up ? p.profit : p.loss, children: [
      Text(_usdt(total), style: context.type.primary.copyWith(fontWeight: FontWeight.w900, fontSize: 24, color: up ? p.profit : p.loss)),
      Text('Today PNL: closed ${_usdt(_n(t['realized']))}, open ${_usdt(_n(t['open_pnl']))}', style: context.type.metadata),
      const SizedBox(height: 8),
      _kv('Opened today', '${t['opened'] ?? 0}'),
      _kv('Closed today', '${t['closed'] ?? 0}  (${t['wins'] ?? 0} won, ${t['losses'] ?? 0} lost)'),
      _kv('Open now', '${t['open'] ?? 0}  (${t['open_long'] ?? 0} long, ${((t['open'] ?? 0) as num) - ((t['open_long'] ?? 0) as num)} short)'),
      _kv('Skipped today (still followed)', '${t['skipped'] ?? 0}'),
    ]);
  }

  // ---- Daily review: the bot trades a full day first, then looks back ----
  Widget _reviewRow(AppPalette p, Map<String, dynamic> r) {
    final prev = r['prev'];
    final again = prev is num && prev < 0;
    final net = _n(r['net']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['name']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.3)),
        Text('${r['n']} trades, ${r['won']} won. Result ${_usdt(_n(r['pnl']))}.', style: context.type.metadata),
        Text(
            'If skipped: saved ${_n(r['saved']).toStringAsFixed(2)} USDT of losses, missed ${_n(r['missed']).toStringAsFixed(2)} USDT of profit. '
            'Net ${_usdt(net)}.',
            style: context.type.metadata.copyWith(height: 1.35, fontWeight: FontWeight.w700, color: net >= 0 ? p.profit : p.loss)),
        if (prev is num) Text(again ? 'Also bad the day before (${_usdt(prev.toDouble())}).' : 'Day before it was fine (${_usdt(prev.toDouble())}).', style: context.type.metadata),
      ]),
    );
  }

  Widget _reviewCard(AppPalette p) {
    final r = _map(_st['review']);
    if (r['status'] != 'ready') {
      return _card(p, title: 'DAILY REVIEW', children: [
        Text(
            'The bot trades every signal for one full day first. The review of that day comes after 5:30 AM IST, '
            'when the day is complete. It will show which scenarios to skip and what that would have saved.',
            style: context.type.secondary),
        Text('Last full day (${r['day'] ?? '-'}): ${r['n'] ?? 0} finished trades so far. It needs 10.', style: context.type.metadata),
      ]);
    }
    final bad = _maps(r['bad']);
    final good = _maps(r['good']);
    final c = _map(r['combo']);
    return _card(p, title: 'DAILY REVIEW (${r['day']})', edge: p.accent, children: [
      Text('That day: ${r['n']} trades, ${r['won']} won, result ${_usdt(_n(r['pnl']))}.',
          style: context.type.primary.copyWith(fontWeight: FontWeight.w800, height: 1.3)),
      if (_n(r['open_left']) > 0) Text('${r['open_left']} trade(s) from that day are still open and not counted.', style: context.type.metadata),
      const SizedBox(height: 8),
      Text('Scenarios that lost (skip candidates)', style: context.type.label),
      const SizedBox(height: 4),
      if (bad.isEmpty) Text('No scenario lost clearly that day.', style: context.type.secondary),
      for (final b in bad) _reviewRow(p, b),
      if (bad.isNotEmpty)
        Text(
            'Skip all of these together: ${c['skipped']} trades skipped, the day would be ${_usdt(_n(c['with']))} instead of ${_usdt(_n(c['without']))}.',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w800, height: 1.35, color: _n(c['with']) >= _n(c['without']) ? p.profit : p.loss)),
      if (good.isNotEmpty) ...[
        const SizedBox(height: 10),
        Text('Scenarios that earned (keep)', style: context.type.label),
        const SizedBox(height: 4),
        for (final g in good)
          Text('${g['name']}: ${g['n']} trades, ${_usdt(_n(g['pnl']))}', style: context.type.metadata.copyWith(height: 1.4, color: p.profit)),
      ],
      const SizedBox(height: 8),
      Text('One day is a hint, not proof. Trust a skip only if the same scenario is bad again on the next days.', style: context.type.metadata),
    ]);
  }

  Widget _scenCard(AppPalette p) {
    final sc = _map(_st['scen']);
    final cards = _maps(sc['cards']);
    if (sc['status'] != 'ready' || cards.isEmpty) return const SizedBox.shrink();
    return _card(p, title: 'SCENARIOS (HOW OFTEN, HOW LONG, HOW MUCH)', children: [
      for (final c in cards)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                    color: (c['verdict'] == 'USE' ? p.profit : p.loss).withOpacity(0.18), borderRadius: BorderRadius.circular(6)),
                child: Text('${c['verdict']}',
                    style: context.type.metadata.copyWith(fontWeight: FontWeight.w800, color: c['verdict'] == 'USE' ? p.profit : p.loss)),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text('${c['name']}', style: context.type.primary.copyWith(height: 1.3))),
            ]),
            const SizedBox(height: 2),
            Text(
                'Seen ${c['per_day']} times a day (${c['n']} trades). Takes about ${c['mins']} min with "${c['best_exit']}". '
                'Best exit: ${_n(c['best_avg']).toStringAsFixed(1)}% per trade, ${c['best_win']}% win. '
                'Bot exit: ${_n(c['bot_avg']).toStringAsFixed(1)}% per trade, ${c['bot_win']}% win.',
                style: context.type.metadata.copyWith(height: 1.35)),
          ]),
        ),
    ]);
  }

  Color _verdictColor(AppPalette p, String v) => v == 'USE' ? p.profit : (v == 'SKIP' ? p.loss : p.textMuted);

  /// One short line: what this trade's setup did before.
  Widget _setupLine(AppPalette p, Map stp) {
    final n = (stp['n'] is num) ? (stp['n'] as num).toInt() : 0;
    final v = '${stp['verdict'] ?? ''}';
    if (n == 0) return Text('Setup: new, the bot never saw this picture before.', style: context.type.metadata);
    final avg = _n(stp['avg']);
    final word = v == 'USE' ? 'good setup' : (v == 'SKIP' ? 'bad setup' : (v == 'FEW' ? 'too few to judge' : 'not clear'));
    return Text('Setup: $n old trades, ${stp['win']}% won, avg ${avg >= 0 ? '+' : ''}${avg.toStringAsFixed(1)}%  ($word)',
        style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: _verdictColor(p, v)));
  }

  Widget _setupRows(AppPalette p, List<Map<String, dynamic>> list) {
    if (list.isEmpty) return Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('None yet.', style: context.type.metadata));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final c in list)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${c['name']}', style: context.type.primary.copyWith(height: 1.3, fontSize: 13)),
            Text(
                '${c['n']} trades, seen ${c['per_day']}x a day. Bot exit: ${c['bot_win']}% won, avg ${_n(c['bot_avg']).toStringAsFixed(1)}%. '
                'Best exit "${c['best_exit']}": ${c['best_win']}% won, avg ${_n(c['best_avg']).toStringAsFixed(1)}%, about ${c['mins']} min.',
                style: context.type.metadata.copyWith(height: 1.35, color: _verdictColor(p, '${c['verdict']}'))),
          ]),
        ),
    ]);
  }

  Widget _setupCard(AppPalette p) {
    final sb = _map(_st['setups']);
    final tot = _map(sb['totals']);
    if (sb['status'] != 'ready') {
      return _card(p, title: 'SETUPS (BOTH INDICATORS TOGETHER)', children: [
        Text(
            'Collecting. It needs about 2 days of data before it can group the trades into setups. '
            '${_n(sb['days']) > 0 ? 'So far: ${_n(sb['days']).toStringAsFixed(1)} days.' : ''}',
            style: context.type.secondary),
      ]);
    }
    return _card(p, title: 'SETUPS (BOTH INDICATORS TOGETHER)', edge: p.accent, children: [
      Text('${tot['seen']} different setups seen', style: context.type.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 15)),
      const SizedBox(height: 2),
      Text(
          '${tot['judged']} have 10+ trades and are judged: ${tot['use']} good, ${tot['skip']} bad, ${tot['unsure']} not clear. '
          '${tot['few']} have too few trades yet.',
          style: context.type.metadata.copyWith(height: 1.4)),
      Text('A setup is the full picture at the entry: who signalled, TSI vs zero, TSI vs its line, TSI histogram, Z candle vs its EMAs, '
          'Z cloud, Z vs ZSM, and price vs Z. Buy and sell with the same picture count together.',
          style: context.type.metadata.copyWith(height: 1.4)),
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: Column(children: [
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Most common setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['common']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Good setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: p.profit)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['use']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Bad setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: p.loss)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['skip']))],
          ),
        ]),
      ),
      Text('Found by counting. Good = the best exit earns in the older and the newer data. Bad = the bot exit loses in both.', style: context.type.metadata),
    ]);
  }

  Widget _lessonsCard(AppPalette p) {
    final l = _map(_st['lessons']);
    final closed = (l['closed'] ?? 0) as num;
    if (closed == 0) {
      return _card(p, title: 'LESSONS FROM MISTAKES', children: [
        Text('No finished trade yet. After each finished trade the bot marks it REAL or FAKE and remembers why.', style: context.type.secondary),
      ]);
    }
    final rep = _map(l['repeat']);
    final warned = (rep['warned'] ?? 0) as num;
    final free = (rep['not_warned'] ?? 0) as num;
    final reasons = _maps(l['top_reasons']);
    return _card(p, title: 'LESSONS FROM MISTAKES', children: [
      _kv('Finished trades', '$closed'),
      _kv('Fake signals', '${l['fake'] ?? 0}', color: p.loss),
      _kv('Real moves', '${l['real'] ?? 0}', color: p.profit),
      if (reasons.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text('Why signals turned out fake', style: context.type.label),
        for (final r in reasons) Text('${r['n']}x  ${r['reason']}', style: context.type.metadata.copyWith(height: 1.4)),
      ],
      const SizedBox(height: 6),
      Text('Old-mistake warning check', style: context.type.label),
      Text(
          warned == 0
              ? 'No trade looked like an old mistake yet.'
              : 'Looked like an old mistake: ${rep['warned_lost']} of $warned lost. '
                  'Did not look like one: ${rep['not_warned_lost']} of $free lost.',
          style: context.type.metadata.copyWith(height: 1.4)),
    ]);
  }

  Widget _tradeRow(AppPalette p, Map<String, dynamic> t, {bool short = false}) {
    final status = '${t['status']}';
    final long = (t['d'] ?? 1) > 0;
    double? net;
    String tag;
    switch (status) {
      case 'closed':
        net = t['net'] is num ? (t['net'] as num).toDouble() : null;
        tag = '${t['end'] ?? 'done'}';
        break;
      case 'open':
        net = t['live'] is num ? (t['live'] as num).toDouble() : null;
        tag = 'open';
        break;
      case 'skipped_done':
        net = t['net'] is num ? (t['net'] as num).toDouble() : null;
        tag = 'skipped, would be';
        break;
      case 'skipped':
        tag = 'skipped';
        break;
      default:
        tag = status;
    }
    final usdt = net == null ? null : net * _n(_st['margin']) / 100.0;
    final path = t['path'] is List ? (t['path'] as List).length : 0;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => showDualTradeChart(context, row: t, margin: _n(_st['margin']), lev: _n(_st['lev'])),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(long ? Icons.arrow_upward : Icons.arrow_downward, size: 16, color: long ? p.profit : p.loss),
          const SizedBox(width: 6),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${t['s']} ${t['f']}  ${long ? 'LONG' : 'SHORT'}  (${t['src']})', style: context.type.primary),
              Text('$tag. Exit: ${t['exit']}${path > 0 ? '. Stop moved $path×' : ''}', style: context.type.metadata),
              if (!short && '${t['what1'] ?? ''}'.isNotEmpty) Text('${t['what1']}', style: context.type.metadata.copyWith(height: 1.3)),
              if (!short && (t['label'] == 'real' || t['label'] == 'fake'))
                Text('${t['label'] == 'fake' ? 'FAKE' : 'REAL'}: ${t['reason'] ?? ''}',
                    style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: t['label'] == 'fake' ? p.loss : p.profit)),
              if (!short && t['side'] is List && (t['side'] as List).length == 2 && (t['side'] as List)[0] is num)
                Text('Sideways: main chart ${(t['side'] as List)[0]}%, Z pane ${(t['side'] as List)[1]}%', style: context.type.metadata),
              if (t['stp'] is Map) _setupLine(p, t['stp'] as Map),
              if (!short && t['mem'] is Map && '${(t['mem'] as Map)['text'] ?? ''}'.isNotEmpty)
                Text('${(t['mem'] as Map)['text']}', style: context.type.metadata.copyWith(height: 1.3)),
            ]),
          ),
          if (usdt != null)
            Text(_usdt(usdt), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: usdt >= 0 ? p.profit : p.loss)),
          Icon(Icons.chevron_right, size: 18, color: p.textMuted),
        ]),
      ),
    );
  }

  Widget _openCard(AppPalette p) {
    final open = _maps(_st['recent']).where((t) => '${t['status']}' == 'open').toList();
    final nMain = open.where((t) => '${t['src']}' == 'MAIN').length;
    final nZ = open.where((t) => '${t['src']}' == 'Z').length;
    final nBoth = open.where((t) => '${t['src']}' == 'BOTH').length;
    final nLong = open.where((t) => (t['d'] ?? 1) > 0).length;
    return _card(p, title: 'OPEN TRADES (LIVE)', edge: open.isEmpty ? null : p.profit, children: [
      if (open.isEmpty) Text('No open trade right now. Tap any trade below to see its chart.', style: context.type.secondary),
      if (open.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            '${open.length} open  ·  $nLong long, ${open.length - nLong} short  ·  entry from: $nMain Main, $nZ Z${nBoth > 0 ? ', $nBoth both' : ''}',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13),
          ),
        ),
      for (final t in open) _tradeRow(p, t, short: true),
      if (open.isNotEmpty) Text('Tap a trade: big chart with entry, stop and take-profit lines. Scroll and zoom like the Positions tab.', style: context.type.metadata),
    ]);
  }

  Widget _recentCard(AppPalette p) {
    final recent = _maps(_st['recent']).where((t) => '${t['status']}' != 'open').toList();
    return _card(p, title: 'LATEST SIGNALS (FINISHED AND SKIPPED)', children: [
      if (recent.isEmpty) Text('No signal yet. New ones appear after each candle closes (5m and 15m).', style: context.type.secondary),
      for (final t in recent.take(25)) _tradeRow(p, t),
    ]);
  }

  Widget _howToReadCard(AppPalette p) {
    const exits = [
      'Bot exit: TP4, or the main chart turns',
      'TP4, or the Z black candle turns',
      'All closed at TP1',
      'All closed at TP2',
      'No limit, leaves when the main chart turns',
      'No limit, leaves at the Z black candle',
      'No limit, trailing stop 1.5R',
      'No limit, trailing stop 3R',
      'Closed after 12 candles',
    ];
    return _card(p, title: 'HOW TO READ THIS', children: [
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text('Tap here to read', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
                'Every signal is a paper trade. The bot looks at both indicators, takes the trade, and checks how 9 different exits would have done. '
                'Entry and first stop are always the same: the stop is the low (buy) or high (sell) of the signal candle. '
                'Tap a trade to see it on the chart: blue triangle = in, orange steps = where the stop moved, green lines = take-profit levels, dot = out.',
                style: context.type.secondary.copyWith(height: 1.35)),
            const SizedBox(height: 8),
            Text('The 9 exits it tests', style: context.type.label),
            const SizedBox(height: 2),
            for (var k = 0; k < exits.length; k++) Text('${k + 1}. ${exits[k]}', style: context.type.metadata.copyWith(height: 1.4)),
            const SizedBox(height: 6),
            Text('R = the distance from entry to the first stop. Fee is already inside every result.', style: context.type.metadata),
          ],
        ),
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text('Dual Bot', style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _poll,
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              _statusCard(p),
              _todayCard(p),
              _openCard(p),
              _reviewCard(p),
              _setupCard(p),
              _scenCard(p),
              _lessonsCard(p),
              _modelCard(p),
              _resultCard(p),
              _situationsCard(p),
              _recentCard(p),
              _howToReadCard(p),
              OutlinedButton.icon(
                onPressed: () => Navigator.of(context).push(OwlRoute(builder: (_) => const TagLabScreen())),
                icon: const Icon(Icons.hub_outlined, size: 18),
                label: const Text('Open Tag Lab (full test on old candles)'),
              ),
              const SizedBox(height: 16),
            ],
          ),
        ),
      ),
    );
  }
}
