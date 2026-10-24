import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
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
                running ? 'Running' : (enabled ? 'Starting... (the backend starts it by itself)' : 'Stopped'),
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

  Widget _tradeRow(AppPalette p, Map<String, dynamic> t) {
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
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Icon(long ? Icons.arrow_upward : Icons.arrow_downward, size: 16, color: long ? p.profit : p.loss),
        const SizedBox(width: 6),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${t['s']} ${t['f']}  ${long ? 'LONG' : 'SHORT'}  (${t['src']})', style: context.type.primary),
            Text('$tag. Exit: ${t['exit']}', style: context.type.metadata),
          ]),
        ),
        if (usdt != null)
          Text(_usdt(usdt), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: usdt >= 0 ? p.profit : p.loss)),
      ]),
    );
  }

  Widget _recentCard(AppPalette p) {
    final recent = _maps(_st['recent']);
    return _card(p, title: 'LATEST SIGNALS', children: [
      if (recent.isEmpty) Text('No signal yet. New ones appear after each candle closes (5m and 15m).', style: context.type.secondary),
      for (final t in recent.take(25)) _tradeRow(p, t),
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
              _modelCard(p),
              _resultCard(p),
              _situationsCard(p),
              _recentCard(p),
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
