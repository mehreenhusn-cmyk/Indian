import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';

/// "Brain" view inside the Dual Bot screen (paper only, analysis only). Shows what the Smart Brain thinks about the Dual Bot setups:
/// clean score, agree / disagree, measured win chance of look-alike old trades, bad hours, repeat losses, a watch list and a trust meter.
/// Everything comes from GET /api/smart_brain (backend smart_brain.py). It only reads; it never places a trade and never touches Dual Bot.
class SmartBrainView extends StatefulWidget {
  const SmartBrainView({super.key});

  @override
  State<SmartBrainView> createState() => _SmartBrainViewState();
}

class _SmartBrainViewState extends State<SmartBrainView> {
  // Last good reply is kept for the whole app session, so re-opening the tab shows data at once.
  static Map<String, dynamic> _cache = {};
  Map<String, dynamic> _st = Map<String, dynamic>.from(_cache);
  String _err = '';
  bool _busy = false;
  bool _all = false;
  Timer? _timer;
  Timer? _retry;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _retry?.cancel();
    super.dispose();
  }

  Future<void> _poll({String action = ''}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final q = action.isEmpty ? '' : '?action=$action';
      final res = await http.get(Uri.parse('$base/api/smart_brain$q')).timeout(const Duration(seconds: 20));
      if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is! Map) throw 'unexpected reply';
      if (mounted) {
        setState(() {
          _st = Map<String, dynamic>.from(m);
          _cache = _st;
          _err = '${_st['error'] ?? ''}';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    }
    if (mounted && _st.isEmpty) {
      _retry?.cancel();
      _retry = Timer(const Duration(seconds: 3), () => _poll());
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
  static String _coin(dynamic s) => '$s'.replaceAll('USDT', '');

  Widget _card(AppPalette p, {required String title, required List<Widget> children, Color? edge}) =>
      OwlSectionCard(title: title, edge: edge, children: children);

  Widget _chip(String text, Color c) => OwlChip(text, c);

  Color _cleanColor(AppPalette p, num v) => v >= 70 ? p.profit : (v >= 40 ? p.warning : p.loss);
  Color _divColor(AppPalette p, num v) => v <= 14 ? p.profit : (v <= 42 ? p.warning : p.loss);
  Color _vColor(AppPalette p, String v) => v == 'like' ? p.profit : (v == 'dislike' ? p.loss : p.warning);

  /// One live setup in a few words: big clean number, coin, side and the Brain's one-line opinion.
  Widget _miniSetup(AppPalette p, String tag, Map<String, dynamic> s, Color c) {
    final buy = _n(s['d']) > 0;
    final clean = _n(s['clean']);
    return Container(
      margin: const EdgeInsets.only(top: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: c.withOpacity(0.07), border: Border.all(color: c.withOpacity(0.35)), borderRadius: BorderRadius.circular(12)),
      child: Row(children: [
        Column(children: [
          Text(clean.toStringAsFixed(0), style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, color: _cleanColor(p, clean), height: 1.0)),
          Text('clean', style: context.type.metadata),
        ]),
        const SizedBox(width: 12),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Wrap(spacing: 6, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
              _chip(tag, c),
              Text(_coin(s['s']), style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
              _chip(buy ? 'BUY' : 'SELL', buy ? p.profit : p.loss),
              Text('${s['f'] ?? ''}', style: context.type.metadata),
            ]),
            const SizedBox(height: 3),
            Text('${s['text'] ?? ''}', style: context.type.secondary),
            Text('${s['prob_text'] ?? ''}', style: context.type.metadata),
          ]),
        ),
      ]),
    );
  }

  /// Top card: what the Brain thinks about the live Dual Bot setups, in one headline plus the best and the worst one.
  Widget _nowCard(AppPalette p) {
    final n = _map(_st['now']);
    if (n.isEmpty) return const SizedBox.shrink();
    final mood = '${n['mood'] ?? ''}';
    final c = mood == 'like' ? p.profit : (mood == 'dislike' ? p.loss : (mood == 'collecting' ? p.textMuted : p.warning));
    final best = _map(n['best']);
    final worst = _map(n['worst']);
    return _card(p, title: 'WHAT THE BRAIN THINKS RIGHT NOW', edge: c, children: [
      Text('${n['headline'] ?? ''}', style: context.type.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 15, height: 1.3)),
      if (best.isNotEmpty) _miniSetup(p, 'BEST', best, _vColor(p, '${best['verdict']}')),
      if (worst.isNotEmpty) _miniSetup(p, 'WORST', worst, _vColor(p, '${worst['verdict']}')),
      const SizedBox(height: 6),
      Text('Green = the Brain likes it, yellow = not sure, red = it dislikes it. Paper only: the Brain never places a trade.', style: context.type.metadata),
    ]);
  }

  Widget _bar(AppPalette p, String label, num v, num need, Color c) {
    final f = need <= 0 ? 0.0 : (v / need).clamp(0.0, 1.0).toDouble();
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('$label: ${v.toStringAsFixed(0)} of ${need.toStringAsFixed(0)}', style: context.type.secondary),
        const SizedBox(height: 3),
        ClipRRect(borderRadius: BorderRadius.circular(6), child: LinearProgressIndicator(value: f, minHeight: 6, color: c, backgroundColor: p.border.withOpacity(0.4))),
      ]),
    );
  }

  /// "What is it learning": how much data it has read, where the data is thin, which coins the scan covers, what comes next.
  Widget _learnCard(AppPalette p) {
    final l = _map(_map(_st['now'])['learning']);
    if (l.isEmpty) return const SizedBox.shrink();
    final thin = (l['thin'] is List) ? (l['thin'] as List).map((e) => '$e').toList() : <String>[];
    final coins = (l['scan_list'] is List) ? (l['scan_list'] as List).map((e) => '$e').toList() : <String>[];
    final scanN = _n(l['scan_n']);
    return _card(p, title: 'WHAT IT IS LEARNING', children: [
      _bar(p, 'Old setups read', _n(l['rows']), _n(l['need_rows']), p.accent),
      _bar(p, 'Unseen trades judged (for trust)', _n(l['judged']), _n(l['need_judged']), p.warning),
      Text('Where it has too little data', style: context.type.label),
      const SizedBox(height: 3),
      if (thin.isEmpty) Text('Nothing thin right now.', style: context.type.metadata),
      for (final t in thin) Text('- $t', style: context.type.metadata),
      const SizedBox(height: 8),
      Text(scanN <= 0 ? 'Scan: waiting for the first scan.' : 'Scan: looking at ${scanN.toStringAsFixed(0)} coins every 5 minutes (${coins.join(', ')}${scanN > coins.length ? ', ...' : ''}).',
          style: context.type.secondary),
      const SizedBox(height: 6),
      Text('${l['next'] ?? ''}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
    ]);
  }

  Widget _statusCard(AppPalette p) {
    final state = '${_st['state'] ?? ''}';
    final enabled = _st['enabled'] != false;
    final text = _st.isEmpty ? (_err.isEmpty ? 'Connecting...' : 'Cannot reach the backend') : '${_st['state_text'] ?? ''}';
    final dot = state == 'ready' ? p.profit : (state == 'stopped' ? p.textMuted : p.warning);
    return _card(p, title: 'SMART BRAIN (PAPER)', edge: p.accent, children: [
      Text(
          'The Brain reads what Dual Bot learned and scores every setup: is it clean or dirty, do Main and Z agree, and how did similar old trades end. '
          'It only reads and explains. It places no trades and never touches Dual Bot.',
          style: context.type.metadata),
      const SizedBox(height: 8),
      Row(children: [
        Icon(Icons.circle, size: 10, color: dot),
        const SizedBox(width: 6),
        Expanded(child: Text(text, style: context.type.primary)),
        OutlinedButton(onPressed: _busy ? null : () => _toggle(!enabled), child: Text(enabled ? 'Stop' : 'Start')),
      ]),
      if (_st.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Old setups read: ${_n(_st['rows']).toStringAsFixed(0)}', style: context.type.metadata)),
      if (_st.isNotEmpty) _trustLine(p),
      if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
    ]);
  }

  /// One line + thin bar: how many unseen trades the Brain has judged, out of the number it needs (100).
  Widget _trustLine(AppPalette p) {
    final t = _map(_st['trust']);
    final need = _n(t['need']) <= 0 ? 100.0 : _n(t['need']);
    final judged = _n(t['judged']);
    final left = (need - judged).clamp(0.0, need).toInt();
    final done = left == 0;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(done ? 'Trust test: ${judged.toStringAsFixed(0)} of ${need.toStringAsFixed(0)} trades judged. Enough data, the meter can now decide.'
                  : 'Trust test: ${judged.toStringAsFixed(0)} of ${need.toStringAsFixed(0)} trades judged ($left to go). At ${need.toStringAsFixed(0)} the meter can decide.',
            style: context.type.metadata),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: (judged / need).clamp(0.0, 1.0).toDouble(), minHeight: 5, color: done ? p.profit : p.accent, backgroundColor: p.border.withOpacity(0.4)),
        ),
      ]),
    );
  }

  Widget _trustCard(AppPalette p) {
    final t = _map(_st['trust']);
    if (t.isEmpty) return const SizedBox.shrink();
    final v = '${t['verdict'] ?? 'learning'}';
    final c = v == 'earned' ? p.profit : (v == 'not_yet' ? p.loss : p.warning);
    final label = v == 'earned' ? 'TRUST EARNED' : (v == 'not_yet' ? 'NOT TRUSTED YET' : 'STILL LEARNING');
    final judged = _n(t['judged']);
    final need = _n(t['need']) <= 0 ? 100.0 : _n(t['need']);
    return _card(p, title: 'TRUST METER', edge: c, children: [
      _chip(label, c),
      const SizedBox(height: 8),
      Text('${t['text'] ?? ''}', style: context.type.primary),
      const SizedBox(height: 8),
      ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: LinearProgressIndicator(value: (judged / need).clamp(0.0, 1.0).toDouble(), minHeight: 6, color: c, backgroundColor: p.border.withOpacity(0.4)),
      ),
      if (t['picks_avg'] != null) ...[
        const SizedBox(height: 8),
        Text('Brain picks: ${_n(t['picks']).toStringAsFixed(0)} trades, ${_n(t['picks_win']).toStringAsFixed(0)}% won, ${_n(t['picks_avg']).toStringAsFixed(1)}% per trade.', style: context.type.secondary),
        Text('Take everything: ${_n(t['judged']).toStringAsFixed(0)} trades, ${_n(t['all_win']).toStringAsFixed(0)}% won, ${_n(t['all_avg']).toStringAsFixed(1)}% per trade.', style: context.type.secondary),
      ],
      const SizedBox(height: 6),
      Text('Trust is only given when the Brain beats "take every signal" on trades it had not seen. Until then it only explains.', style: context.type.metadata),
    ]);
  }

  /// "Is it luck?": the Brain's picks against many random picks of the same size.
  Widget _luckCard(AppPalette p) {
    final l = _map(_st['luck']);
    if (l.isEmpty) return const SizedBox.shrink();
    final v = '${l['verdict'] ?? 'learning'}';
    final c = v == 'solid' ? p.profit : (v == 'maybe' ? p.warning : (v == 'luck' ? p.loss : p.textMuted));
    final label = v == 'solid' ? 'LOOKS REAL' : (v == 'maybe' ? 'MAYBE REAL' : (v == 'luck' ? 'COULD BE LUCK' : 'NOT ENOUGH DATA'));
    final d = _map(_st['drift']);
    return _card(p, title: 'IS IT SKILL OR LUCK?', edge: c, children: [
      _chip(label, c),
      const SizedBox(height: 8),
      Text('${l['text'] ?? ''}', style: context.type.primary),
      const SizedBox(height: 6),
      Text('The test picks the same number of trades at random 1000 times and checks how often chance alone does as well as the Brain.', style: context.type.metadata),
      if (d.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('Newest ${_n(d['recent_n']).toStringAsFixed(0)} setups: ${_n(d['recent_win']).toStringAsFixed(0)}% won. Older ${_n(d['old_n']).toStringAsFixed(0)}: ${_n(d['old_win']).toStringAsFixed(0)}% won.', style: context.type.secondary),
        Text('Newer trades count more in every probability (an old trade counts half after ${_n(d['half_life']).toStringAsFixed(0)} newer setups).', style: context.type.metadata),
      ],
    ]);
  }

  /// Exit learner (shadow only): for open trades it says "hold" or "exit looks fine" from past trades. It never closes anything.
  Widget _exitCard(AppPalette p) {
    final x = _map(_st['exit']);
    if (x.isEmpty) return const SizedBox.shrink();
    final open = _maps(x['open']);
    final stages = _maps(x['stages']);
    final sc = _map(x['score']);
    final ready = '${x['status']}' == 'ready';
    Color advColor(String a) => a == 'HOLD' ? p.profit : (a == 'EXIT_OK' ? p.warning : p.textMuted);
    String advWord(String a) => a == 'HOLD' ? 'HOLD' : (a == 'EXIT_OK' ? 'EXIT IS FINE' : (a == 'WAIT' ? 'WAITING' : 'NO OPINION'));
    return _card(p, title: 'WHEN TO EXIT (LEARNING ONLY)', edge: ready ? null : p.textMuted, children: [
      Text('${x['text'] ?? ''}', style: context.type.secondary),
      if (open.isNotEmpty) ...[
        const SizedBox(height: 8),
        for (final o in open)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: Text('${_coin(o['s'])} ${o['f']} ${_n(o['d']) > 0 ? 'BUY' : 'SELL'}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
                if (o['live'] is num) Text('${_n(o['live']) >= 0 ? '+' : ''}${_n(o['live']).toStringAsFixed(1)}%', style: context.type.secondary.copyWith(color: _n(o['live']) >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w700)),
                const SizedBox(width: 6),
                _chip(advWord('${o['adv']}'), advColor('${o['adv']}')),
              ]),
              const SizedBox(height: 2),
              Text('${o['text'] ?? ''}', style: context.type.metadata),
            ]),
          ),
      ] else if (ready)
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('No open Dual Bot trade right now.', style: context.type.metadata)),
      if (stages.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('How past trades finished, by how far the stop trailed:', style: context.type.metadata),
        for (final s in stages)
          Text('${_n(s['stage']).toInt() == 0 ? 'Any trade' : (_n(s['stage']).toInt() >= 4 ? 'Stop moved 4+ times' : 'Stop moved ${_n(s['stage']).toInt()}+ times')}: ${_n(s['n']).toInt()} trades, ${_n(s['win']).toInt()}% won, average ${_n(s['avg']) >= 0 ? '+' : ''}${_n(s['avg']).toStringAsFixed(1)}%', style: context.type.secondary),
      ],
      const SizedBox(height: 6),
      Text('${sc['text'] ?? ''}', style: context.type.metadata),
      Text('It does not close or change any trade. It only gives an opinion and checks later if it was right.', style: context.type.metadata),
    ]);
  }

  /// "What if the bot had listened?": same finished trades, three paper stories. Shadow only, nothing changes in the bot.
  Widget _followCard(AppPalette p) {
    final f = _map(_st['follow']);
    if (f.isEmpty) return const SizedBox.shrink();
    final st = _maps(f['stories']);
    final ready = '${f['status']}' == 'ready';
    String sg(num v, int d) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';
    return _card(p, title: 'WHAT IF THE BOT HAD LISTENED?', edge: ready ? null : p.textMuted, children: [
      Text('${f['text'] ?? ''}', style: context.type.primary),
      if (st.isNotEmpty) ...[
        const SizedBox(height: 8),
        for (final s in st)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${s['name']}', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
                  Text('${_n(s['n']).toInt()} trades, ${_n(s['win']).toInt()}% won, worst drop ${_n(s['drop']).toStringAsFixed(0)}', style: context.type.metadata),
                ]),
              ),
              Text(sg(_n(s['total']), 0), style: context.type.primary.copyWith(color: _n(s['total']) >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w800, fontSize: 17)),
            ]),
          ),
      ],
      const SizedBox(height: 4),
      Text('Numbers are ROI points of margin, fee inside. Each trade is judged using only older memory. Report only: the bot is not changed.', style: context.type.metadata),
    ]);
  }

  Widget _riskLine(AppPalette p, String label, String a, String b) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(children: [
        Expanded(flex: 5, child: Text(label, style: context.type.secondary)),
        Expanded(flex: 3, child: Text(a, textAlign: TextAlign.right, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
        Expanded(flex: 3, child: Text(b, textAlign: TextAlign.right, style: context.type.secondary)),
      ]),
    );
  }

  /// Risk numbers of the Brain's frozen picks next to "all signals": biggest drop, risk-adjusted gain, worst 5% trades, worst-case range.
  Widget _riskCard(AppPalette p) {
    final r = _map(_st['risk']);
    if (r.isEmpty) return const SizedBox.shrink();
    final pk = _map(r['picks']);
    final al = _map(r['all']);
    final w = _map(r['worst']);
    String usdt(dynamic v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}' : '--';
    String num2(dynamic v) => v is num ? v.toStringAsFixed(2) : '--';
    return _card(p, title: 'RISK (PAPER BOOK)', children: [
      if (pk.isEmpty) Text('${r['text'] ?? ''}', style: context.type.secondary),
      if (pk.isNotEmpty) ...[
        _riskLine(p, '', 'Brain picks', 'All signals'),
        _riskLine(p, 'Finished trades', _n(pk['n']).toStringAsFixed(0), al.isEmpty ? '--' : _n(al['n']).toStringAsFixed(0)),
        _riskLine(p, 'Total (USDT)', usdt(pk['total']), usdt(al['total'])),
        _riskLine(p, 'Biggest drop (USDT)', num2(pk['max_dd']), num2(al['max_dd'])),
        _riskLine(p, 'Worst 5% trades, average', usdt(pk['cvar5']), usdt(al['cvar5'])),
        _riskLine(p, 'Gain per unit of risk', num2(pk['sharpe']), num2(al['sharpe'])),
        _riskLine(p, 'Same, only downside risk', num2(pk['sortino']), num2(al['sortino'])),
        const SizedBox(height: 4),
        Text('Ratios are per trade. Higher is better, a small biggest drop is better. "--" means there were no losses or too few trades.', style: context.type.metadata),
      ],
      if (w.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('WORST-CASE RANGE', style: context.type.label),
        const SizedBox(height: 3),
        Text('${w['text'] ?? ''}', style: context.type.secondary),
        Text('Typical shuffle: ${num2(w['median'])} USDT. Plan for the bad case, not the typical one.', style: context.type.metadata),
      ],
    ]);
  }

  Widget _bookRow(AppPalette p, Map<String, dynamic> b) {
    final done = '${b['status']}' == 'closed' || '${b['status']}' == 'skipped_done';
    final net = b['net'] is num ? _n(b['net']) : (b['live'] is num ? _n(b['live']) : null);
    final buy = _n(b['d']) > 0;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(children: [
        Expanded(
            child: Wrap(spacing: 6, runSpacing: 2, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(_coin(b['s']), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          _chip(buy ? 'BUY' : 'SELL', buy ? p.profit : p.loss),
          Text('${b['mode'] == 'paper' ? 'paper' : 'shadow'} · clean ${_n(b['clean']).toStringAsFixed(0)} · ${_n(b['win_pct']).toStringAsFixed(0)}% of ${_n(b['n']).toStringAsFixed(0)}', style: context.type.metadata),
        ])),
        Text(net == null ? 'waiting' : '${done ? '' : 'open '}${net >= 0 ? '+' : ''}${net.toStringAsFixed(1)}%',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: net == null ? p.textMuted : (net >= 0 ? p.profit : p.loss))),
      ]),
    );
  }

  Widget _bookCard(AppPalette p) {
    final b = _map(_st['book']);
    if (b.isEmpty) {
      return _card(p, title: "BRAIN'S OWN PAPER BOOK", children: [
        Text('Starts when the Brain has read enough old setups. From then on it freezes every setup it would have picked, at signal time, and tracks the result.', style: context.type.metadata),
      ]);
    }
    final pk = _map(b['picks']);
    final al = _map(b['all']);
    final trusted = '${_map(_st['trust'])['verdict']}' == 'earned';
    String line(Map<String, dynamic> m) =>
        '${_n(m['closed']).toStringAsFixed(0)} done, ${_n(m['closed']) > 0 ? (100 * _n(m['wins']) / _n(m['closed'])).toStringAsFixed(0) : '0'}% won, ${_n(m['pnl']) >= 0 ? '+' : ''}${_n(m['pnl']).toStringAsFixed(2)} USDT';
    final recent = _maps(b['recent']);
    return _card(p, title: "BRAIN'S OWN PAPER BOOK", edge: trusted ? p.profit : null, children: [
      Text(
          trusted
              ? 'Trust is earned, so new picks are PAPER picks. Still paper money only.'
              : 'Trust is not earned yet, so every pick is a SHADOW note: what would have happened if I followed the Brain. No real or paper money is used by the Brain.',
          style: context.type.metadata),
      const SizedBox(height: 8),
      Text('Brain picks: ${line(pk)}', style: context.type.primary),
      Text('All signals: ${line(al)}', style: context.type.secondary),
      Text('Only signals after the book started are counted, and a pick is never changed afterwards.', style: context.type.metadata),
      const SizedBox(height: 8),
      if (recent.isEmpty) Text('No picks yet.', style: context.type.secondary),
      for (final r in recent) _bookRow(p, r),
    ]);
  }

  Widget _setupRow(AppPalette p, Map<String, dynamic> s) {
    final buy = _n(s['d']) > 0;
    final clean = _n(s['clean']);
    final div = _n(s['div']);
    final prob = _map(s['prob']);
    final good = (s['good'] is List) ? (s['good'] as List).map((e) => '$e').toList() : <String>[];
    final bad = (s['bad'] is List) ? (s['bad'] as List).map((e) => '$e').toList() : <String>[];
    final status = '${s['status'] ?? ''}';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(border: Border.all(color: p.border.withOpacity(0.5)), borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          Text(_coin(s['s']), style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
          _chip(buy ? 'BUY' : 'SELL', buy ? p.profit : p.loss),
          Text('${s['f'] ?? ''}  ${s['src'] ?? ''}${status.isEmpty ? '' : '  ·  $status'}', style: context.type.metadata),
        ]),
        if ('${s['verdict_text'] ?? ''}'.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text('${s['verdict_text']}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700, color: _vColor(p, '${s['verdict']}'))),
          ),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 4, children: [
          _chip('Clean ${clean.toStringAsFixed(0)}/100', _cleanColor(p, clean)),
          _chip('${div <= 14 ? 'Agree' : (div <= 42 ? 'Mixed' : 'Disagree')} (${div.toStringAsFixed(0)})', _divColor(p, div)),
          if (prob.isNotEmpty) _chip('${_n(prob['win_pct']).toStringAsFixed(0)}% won of ${_n(prob['n']).toStringAsFixed(0)}', _n(prob['win_pct']) >= 55 ? p.profit : (_n(prob['win_pct']) >= 45 ? p.warning : p.loss)),
        ]),
        const SizedBox(height: 6),
        Text('${s['prob_text'] ?? ''}', style: context.type.secondary),
        Text('${s['div_label'] ?? ''}', style: context.type.metadata),
        for (final g in good) Text('+ $g', style: context.type.metadata.copyWith(color: p.profit)),
        for (final b in bad) Text('- $b', style: context.type.metadata.copyWith(color: p.loss)),
      ]),
    );
  }

  Widget _signalsCard(AppPalette p) {
    final list = _maps(_st['signals']);
    final shown = _all ? list : list.take(6).toList();
    return _card(p, title: 'RIGHT NOW: DUAL BOT SETUPS', children: [
      if (list.isEmpty) Text('No setups to score yet. Dual Bot is still collecting.', style: context.type.metadata),
      for (final s in shown) _setupRow(p, s),
      if (list.length > 6) TextButton(onPressed: () => setState(() => _all = !_all), child: Text(_all ? 'Show less' : 'Show all ${list.length}')),
    ]);
  }

  Widget _watchCard(AppPalette p) {
    final list = _maps(_st['watch']);
    return _card(p, title: 'WATCH LIST (NO SIGNAL YET)', children: [
      Text('Coins that look like a good setup right now even though no signal fired. A watch list only: nothing is traded.', style: context.type.metadata),
      const SizedBox(height: 8),
      if (list.isEmpty) Text('Nothing strong right now.', style: context.type.secondary),
      for (final s in list) _setupRow(p, s),
    ]);
  }

  Widget _lines(AppPalette p, List<Map<String, dynamic>> l, Color c, String empty) {
    if (l.isEmpty) return Text(empty, style: context.type.metadata);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final x in l)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${x['text']}', style: context.type.primary),
              Text('${_n(x['n']).toStringAsFixed(0)} old trades, ${_n(x['win_pct']).toStringAsFixed(0)}% won, ${_n(x['avg']).toStringAsFixed(1)}% per trade', style: context.type.metadata.copyWith(color: c)),
            ]),
          ),
      ],
    );
  }

  Widget _patternsCard(AppPalette p) {
    return _card(p, title: 'WHAT IT FOUND IN THE OLD TRADES', children: [
      Text('REPEAT LOSSES (avoid)', style: context.type.label.copyWith(color: p.loss)),
      const SizedBox(height: 4),
      _lines(p, _maps(_st['repeat_loss']), p.loss, 'None found yet. A mix is named only when old and new trades agree.'),
      const SizedBox(height: 8),
      Text('GOOD MIXES', style: context.type.label.copyWith(color: p.profit)),
      const SizedBox(height: 4),
      _lines(p, _maps(_st['patterns']), p.profit, 'None found yet.'),
    ]);
  }

  Widget _hoursCard(AppPalette p) {
    final hrs = _maps(_st['hours']);
    final sp = _map(_st['speed']);
    return _card(p, title: 'TIME OF DAY AND SPEED', children: [
      if (hrs.isEmpty) Text('Not enough old trades per time block yet.', style: context.type.metadata),
      for (final h in hrs)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Expanded(child: Text('${h['hour']}', style: context.type.secondary)),
            Text('${_n(h['win_pct']).toStringAsFixed(0)}% won of ${_n(h['n']).toStringAsFixed(0)}',
                style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: h['bad'] == true ? p.loss : (h['good'] == true ? p.profit : null))),
            if (h['bad'] == true) Padding(padding: const EdgeInsets.only(left: 6), child: _chip('bad hours', p.loss)),
          ]),
        ),
      if (sp.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('Winners usually finish in about ${_n(sp['median']).toStringAsFixed(0)} candles; ${_n(sp['fast_pct']).toStringAsFixed(0)}% of winners are fast (6 candles or less).', style: context.type.secondary),
      ],
    ]);
  }

  Widget _bandsCard(AppPalette p) {
    final b = _maps(_st['bands']);
    if (b.isEmpty) return const SizedBox.shrink();
    return _card(p, title: 'DOES THE CLEAN SCORE MEAN ANYTHING?', children: [
      Text('Real result of old trades per score band. If Clean does not win more than Dirty, the score is not useful yet.', style: context.type.metadata),
      const SizedBox(height: 6),
      for (final x in b)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Row(children: [
            Expanded(child: Text('${x['band']}', style: context.type.secondary)),
            Text(x['win_pct'] == null ? 'not enough data' : '${_n(x['win_pct']).toStringAsFixed(0)}% won of ${_n(x['n']).toStringAsFixed(0)}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          ]),
        ),
    ]);
  }

  Widget _howCard(AppPalette p) {
    return _card(p, title: 'HOW TO READ THIS', children: [
      for (final g in _maps(_map(_st['now'])['guide']))
        Padding(
          padding: const EdgeInsets.only(bottom: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(Icons.circle, size: 10, color: '${g['color']}' == 'green' ? p.profit : ('${g['color']}' == 'yellow' ? p.warning : p.loss)),
            const SizedBox(width: 6),
            Expanded(child: Text('${g['band']} ${g['name']}: ${g['meaning']}', style: context.type.secondary)),
          ]),
        ),
      Text('Clean score: 100 = both panes trending and everything points the same way. Low = sideways market or warning signs.', style: context.type.secondary),
      const SizedBox(height: 4),
      Text('Agree / Disagree: do the Main chart, the Z pane and TSI point the same way?', style: context.type.secondary),
      const SizedBox(height: 4),
      Text('"62% won of 40": of the 40 most similar old trades, 62% won. It is a measured number, not a promise. With too few similar trades it says "not enough data".', style: context.type.secondary),
      const SizedBox(height: 4),
      Text('Paper only. The Brain explains and scores. It has not earned the right to trade yet.', style: context.type.metadata),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _nowCard(p),
      _learnCard(p),
      _signalsCard(p),
      _statusCard(p),
      _trustCard(p),
      _luckCard(p),
      _exitCard(p),
      _followCard(p),
      _bookCard(p),
      _riskCard(p),
      _watchCard(p),
      _patternsCard(p),
      _hoursCard(p),
      _bandsCard(p),
      _howCard(p),
    ]);
  }
}
