import '../theme/app_active.dart';
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Strategy Lab card (crypto Doctor, top). Shows ONE table: each scenario (wider SL, hold till opposite signal, TSI/Z, Bollinger,
/// EMA bands ...) against the bot today. Read-only: it only reads /api/variant_lab. Nothing here changes the bot.
class VariantLabCard extends StatefulWidget {
  const VariantLabCard({super.key});

  @override
  State<VariantLabCard> createState() => _VariantLabCardState();
}

class _VariantLabCardState extends State<VariantLabCard> {
  Map<String, dynamic> _st = {};
  String _tf = '15m';
  String _err = '';
  bool _starting = false;
  Timer? _timer;

  static const _tfs = ['3m', '5m', '15m'];

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = AppActive.every(const Duration(seconds: 15), () { // Part 7b: 6 s -> 15 s, none in the background
      if (_st['running'] == true) _poll();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll({bool start = false}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http.get(Uri.parse('$base/api/variant_lab${start ? '?start=1&days=14' : ''}')).timeout(const Duration(seconds: 20));
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

  Future<void> _run() async {
    setState(() => _starting = true);
    await _poll(start: true);
    if (mounted) setState(() => _starting = false);
  }

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static String _s(double v, {bool sign = false}) => (sign && v > 0 ? '+' : '') + v.toStringAsFixed(0);

  Map<String, dynamic> get _res {
    final t = _st['tfs'];
    if (t is Map && t[_tf] is Map) return Map<String, dynamic>.from(t[_tf] as Map);
    return <String, dynamic>{};
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final running = _st['running'] == true;
    final res = _res;
    final done = res['state'] == 'done' && res['ok'] == true;
    final answer = (res['answer'] is List) ? (res['answer'] as List).map((e) => '$e').toList() : <String>[];
    final rows = (res['rows'] is List) ? (res['rows'] as List).whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
    const groups = ['Exit and stop-loss', 'Indicators (skip signals)', 'Bollinger (skip signals)', 'CVD (order flow)', 'Bands', 'Mixes', 'Outside suggestion (4 points)'];
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.accent.withOpacity(0.55)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.science_outlined, size: 18, color: p.accent),
          const SizedBox(width: 8),
          Expanded(child: Text('Strategy Lab: what if?', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
          TextButton(
            onPressed: running || _starting ? null : _run,
            child: Text(running ? 'Running...' : (done ? 'Run again' : 'Run tests')),
          ),
        ]),
        Text('Same signals as the bot, replayed on the last ${_i(_st['days'] == null ? 14 : _st['days'])} days. Each line is compared with the bot today.',
            style: context.type.metadata),
        const SizedBox(height: 8),
        Wrap(spacing: 8, children: [
          for (final tf in _tfs)
            ChoiceChip(label: Text(tf), selected: _tf == tf, onSelected: (_) => setState(() => _tf = tf)),
        ]),
        if (running) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
          const SizedBox(height: 4),
          Text('${_st['progress'] ?? ''}  (a few minutes, you can leave this screen)', style: context.type.metadata),
        ],
        if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
        if (!done && !running && answer.isEmpty)
          Padding(padding: const EdgeInsets.only(top: 10), child: Text('No result for $_tf yet. Tap "Run tests".', style: context.type.secondary)),
        if (answer.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final l in answer) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(l, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
        ],
        if (done && rows.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text('SCOREBOARD', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.0)),
          const SizedBox(height: 4),
          Text(_score(rows, null), style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
          if (rows.any((r) => r['group'] == 'Outside suggestion (4 points)'))
            Text("Kimi's ideas: " + _score(rows.where((r) => r['group'] == 'Outside suggestion (4 points)').toList(), null),
                style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
          const SizedBox(height: 12),
          Text('TOP 3 IDEAS (best vs the bot today)', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.0)),
          const SizedBox(height: 4),
          for (final r in ([...rows]..sort((a, b) => _d(b['vs_bot']).compareTo(_d(a['vs_bot'])))).take(3)) _row(context, r),
          Text(rows.any((r) => r['verdict'] == 'better') ? 'At least one idea beat the bot in both older and newer data.' : 'None of them is proven yet. Do not change the bot because of these.',
              style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
        ],
        if (done) ...[
          const SizedBox(height: 12),
          Text('COMPARISON TABLE: normal bot vs every scenario', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.0)),
          const SizedBox(height: 2),
          Text('taken = trades it took, ignored = signals it skipped. net = ROI points after fees. vs bot = how much better (+) or worse (-) than the normal bot.', style: context.type.metadata),
          const SizedBox(height: 6),
          _table(context, res, rows, groups),
        ],
        if (done)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(
                'Numbers are ROI points after fees, from a replay (no slippage). BETTER = beat the bot in both the older and the newer data. '
                'Many tests on the same data can still show a lucky winner, so try it on paper first.',
                style: context.type.metadata),
          ),
      ]),
    );
  }

  static String _score(List<Map<String, dynamic>> rows, String? g) {
    int c(String k) => rows.where((r) => '${r['verdict']}' == k).length;
    return '${rows.length} ideas tested: ${c('better')} better than the bot, ${c('worse')} worse, ${c('unclear')} not clear, ${c('not_enough')} too few trades.';
  }

  Widget _table(BuildContext context, Map<String, dynamic> res, List<Map<String, dynamic>> rows, List<String> groups) {
    final p = context.palette;
    final bot = (res['bot'] is Map) ? Map<String, dynamic>.from(res['bot'] as Map) : <String, dynamic>{};
    Widget cell(String x, {int flex = 1, Color? c, bool bold = false, TextAlign a = TextAlign.right}) => Expanded(
        flex: flex, child: Text(x, textAlign: a, style: context.type.metadata.copyWith(color: c ?? p.textPrimary, fontWeight: bold ? FontWeight.w800 : FontWeight.w400, fontSize: 11)));
    Widget line(String name, String trades, String skip, String net, String win, String vs, String word, Color col, {bool bold = false, Color? vsCol}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            cell(name, flex: 6, a: TextAlign.left, bold: bold),
            cell(trades, flex: 2),
            cell(skip, flex: 2),
            cell(net, flex: 2, c: vsCol),
            cell(win, flex: 2),
            cell(vs, flex: 2, c: vsCol, bold: true),
            cell(word, flex: 3, c: col, bold: true),
          ]),
        );
    final out = <Widget>[
      line('Scenario', 'taken', 'ignored', 'net', 'win', 'vs bot', 'result', p.textSecondary, vsCol: p.textSecondary),
      const Divider(height: 6),
      line('NORMAL BOT', '${_i(res['n'])}', '0', _s(_d(bot['net'])), '${_d(bot['win']).toStringAsFixed(0)}%', '-', 'bot', p.textSecondary, bold: true, vsCol: p.textPrimary),
    ];
    for (final g in groups) {
      final gr = rows.where((r) => r['group'] == g).toList();
      if (gr.isEmpty) continue;
      out.add(Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 2),
        child: Text(g.toUpperCase(), style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.8, color: p.textSecondary)),
      ));
      for (final r in gr) {
        final v = '${r['verdict']}';
        final vs = _d(r['vs_bot']);
        final col = v == 'better' ? p.profit : v == 'worse' ? p.loss : p.textSecondary;
        final word = v == 'better' ? 'BETTER' : v == 'worse' ? 'WORSE' : v == 'unclear' ? 'not clear' : 'few data';
        out.add(line('${r['title']}', '${_i(r['taken'])}', '${(_i(res['n']) - _i(r['taken'])).clamp(0, 1 << 30)}', _s(_d(r['net'])), '${_d(r['win']).toStringAsFixed(0)}%', _s(vs, sign: true), word, col,
            vsCol: vs > 0 ? p.profit : (vs < 0 ? p.loss : p.textSecondary)));
      }
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: out);
  }

  Widget _row(BuildContext context, Map<String, dynamic> r) {
    final p = context.palette;
    final v = '${r['verdict']}';
    final col = v == 'better' ? p.profit : v == 'worse' ? p.loss : p.textSecondary;
    final label = v == 'better' ? 'BETTER' : v == 'worse' ? 'WORSE' : v == 'unclear' ? 'not clear' : 'not enough data';
    final vs = _d(r['vs_bot']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${r['title']}', style: context.type.primary)),
          Text(label, style: context.type.label.copyWith(color: col, fontWeight: FontWeight.w800)),
        ]),
        Text(
          'trades ${_i(r['taken'])} of ${_i(_res['n'])}  |  net ${_s(_d(r['net']))}  |  win ${_d(r['win']).toStringAsFixed(0)}%  |  vs bot ${_s(vs, sign: true)}',
          style: context.type.secondary.copyWith(color: vs > 0 ? p.profit : (vs < 0 ? p.loss : p.textSecondary)),
        ),
        Text('got better on ${_s(_d(r['saved']))}, got worse on ${_s(_d(r['missed']))}', style: context.type.metadata),
      ]),
    );
  }

}
