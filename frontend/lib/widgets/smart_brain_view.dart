import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// "Brain" view inside the Dual Bot screen (paper only, analysis only). Shows what the Smart Brain thinks about the Dual Bot setups:
/// clean score, agree / disagree, measured win chance of look-alike old trades, bad hours, repeat losses, a watch list and a trust meter.
/// Everything comes from GET /api/smart_brain (backend smart_brain.py). It only reads; it never places a trade and never touches Dual Bot.
class SmartBrainView extends StatefulWidget {
  const SmartBrainView({super.key});

  @override
  State<SmartBrainView> createState() => _SmartBrainViewState();
}

class _SmartBrainViewState extends State<SmartBrainView> {
  Map<String, dynamic> _st = {};
  String _err = '';
  bool _busy = false;
  bool _all = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _poll());
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
      final res = await http.get(Uri.parse('$base/api/smart_brain$q')).timeout(const Duration(seconds: 20));
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
  static String _coin(dynamic s) => '$s'.replaceAll('USDT', '');

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

  Widget _chip(String text, Color c) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(10), border: Border.all(color: c.withOpacity(0.5))),
      child: Text(text, style: context.type.metadata.copyWith(color: c, fontWeight: FontWeight.w700)),
    );
  }

  Color _cleanColor(AppPalette p, num v) => v >= 70 ? p.profit : (v >= 40 ? p.warning : p.loss);
  Color _divColor(AppPalette p, num v) => v <= 14 ? p.profit : (v <= 42 ? p.warning : p.loss);

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
      if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
    ]);
  }

  Widget _trustCard(AppPalette p) {
    final t = _map(_st['trust']);
    if (t.isEmpty) return const SizedBox.shrink();
    final v = '${t['verdict'] ?? 'learning'}';
    final c = v == 'earned' ? p.profit : (v == 'not_yet' ? p.loss : p.warning);
    final label = v == 'earned' ? 'TRUST EARNED' : (v == 'not_yet' ? 'NOT TRUSTED YET' : 'STILL LEARNING');
    final judged = _n(t['judged']);
    final need = _n(t['need']) <= 0 ? 30.0 : _n(t['need']);
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
      _statusCard(p),
      _trustCard(p),
      _bookCard(p),
      _signalsCard(p),
      _watchCard(p),
      _patternsCard(p),
      _hoursCard(p),
      _bandsCard(p),
      _howCard(p),
    ]);
  }
}
