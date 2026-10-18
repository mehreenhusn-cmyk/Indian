import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Scan Lab card (crypto Doctor, under Strategy Lab). Shows a SHORT plain answer first (which setup won, bot today, bands),
/// then up to 5 winners, and the step-by-step table is folded away. Read-only: it only reads /api/scan_lab.
class ScanLabCard extends StatefulWidget {
  const ScanLabCard({super.key});

  @override
  State<ScanLabCard> createState() => _ScanLabCardState();
}

class _ScanLabCardState extends State<ScanLabCard> {
  Map<String, dynamic> _st = {};
  String _err = '';
  bool _starting = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (_st['running'] == true) _poll();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll({String start = ''}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http
          .get(Uri.parse('$base/api/scan_lab${start.isEmpty ? '' : '?start=$start'}'))
          .timeout(const Duration(seconds: 20));
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

  Future<void> _run(String mode) async {
    setState(() => _starting = true);
    await _poll(start: mode);
    if (mounted) setState(() => _starting = false);
  }

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static String _n(double v) => (v > 0 ? '+' : '') + v.toStringAsFixed(1);

  Widget _sdTable(BuildContext context, Map<String, dynamic> t) {
    final p = context.palette;
    final rows = _maps(t['rows']);
    if (rows.isEmpty) return const SizedBox.shrink();
    Widget cell(String x, {int flex = 1, Color? c, bool bold = false, TextAlign a = TextAlign.right}) => Expanded(
        flex: flex, child: Text(x, textAlign: a, style: context.type.metadata.copyWith(color: c ?? p.textPrimary, fontWeight: bold ? FontWeight.w800 : FontWeight.w400)));
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${t['tf']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 2),
        Row(children: [
          cell('SD length', flex: 3, a: TextAlign.left, c: p.textSecondary),
          cell('trades', c: p.textSecondary),
          cell('TP4 %', c: p.textSecondary),
          cell('avg/trade', flex: 2, c: p.textSecondary),
          cell('result', flex: 2, c: p.textSecondary),
        ]),
        for (final r in rows)
          Builder(builder: (_) {
            final v = '${r['verdict']}';
            final col = v == 'better' ? p.profit : v == 'worse' ? p.loss : p.textSecondary;
            final word = v == 'bot' ? 'bot today' : v == 'better' ? 'BETTER' : v == 'worse' ? 'WORSE' : v == 'too_few' ? 'few trades' : 'not clear';
            final avg = r['avg'] == null ? '-' : _n(_d(r['avg']));
            return Row(children: [
              cell('${r['label']}', flex: 3, a: TextAlign.left, bold: v == 'bot'),
              cell('${_i(r['n'])}'),
              cell(r['tp4'] == null ? '-' : _d(r['tp4']).toStringAsFixed(0)),
              cell(avg, flex: 2, c: _d(r['avg']) > 0 ? p.profit : p.loss),
              cell(word, flex: 2, c: col, bold: v == 'better' || v == 'worse'),
            ]);
          }),
      ]),
    );
  }

  static String _word(Map<String, dynamic> s) => '${s['best_verdict']}' == 'winner' ? 'WINNER' : 'not proven';

  List<Map<String, dynamic>> _maps(dynamic v) =>
      (v is List) ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final running = _st['running'] == true;
    final sum = (_st['summary'] is Map) ? Map<String, dynamic>.from(_st['summary'] as Map) : <String, dynamic>{};
    final answer = (sum['answer'] is List) ? (sum['answer'] as List).map((e) => '$e').toList() : <String>[];
    final winners = _maps(sum['winners']);
    final steps = _maps(sum['steps']);
    final sd = (_st['sd'] is Map) ? Map<String, dynamic>.from(_st['sd'] as Map) : <String, dynamic>{};
    final sdAnswer = (sd['answer'] is List) ? (sd['answer'] as List).map((e) => '$e').toList() : <String>[];
    final sdTfs = _maps(sd['tfs']);
    final busy = running || _starting;
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
          Icon(Icons.radar, size: 18, color: p.accent),
          const SizedBox(width: 8),
          Expanded(child: Text('Scan Lab: which setup works?', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
        ]),
        Text('Tests entry line (EMA30/50, SMA30/50, mean), timeframe 3m to 2h, fixed major coins vs daily movers, and SD bands as support/resistance.',
            style: context.type.metadata),
        const SizedBox(height: 8),
        Wrap(spacing: 8, children: [
          OutlinedButton(
            onPressed: busy ? null : () => _run('quick'),
            child: Text(running && _st['mode'] == 'quick' ? 'Running...' : 'Quick (majors 15m-2h)'),
          ),
          OutlinedButton(
            onPressed: busy ? null : () => _run('full'),
            child: Text(running && _st['mode'] == 'full' ? 'Running...' : 'Full (slow)'),
          ),
          OutlinedButton(
            onPressed: busy ? null : () => _run('sd'),
            child: Text(running && _st['mode'] == 'sd' ? 'Running...' : 'SD length test (200 vs 100)'),
          ),
        ]),
        if (running) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
          const SizedBox(height: 4),
          Text('${_st['progress'] ?? ''}  (you can leave this screen)', style: context.type.metadata),
        ] else if ('${_st['progress'] ?? ''}'.isNotEmpty && '${_st['progress']}' != 'done' && '${_st['progress']}' != 'starting...') ...[
          const SizedBox(height: 6),
          Text('${_st['progress']}', style: context.type.metadata),
        ],
        if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
        if (answer.isEmpty && sdAnswer.isEmpty && !running)
          Padding(padding: const EdgeInsets.only(top: 10), child: Text('No result yet. Tap Quick or the SD length test.', style: context.type.secondary)),
        if (answer.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final l in answer)
            Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(l, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
        ],
        if (winners.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('WINNERS (after fees, both older and newer data)', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.0)),
          const SizedBox(height: 4),
          for (final w in winners)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${w['title']}', style: context.type.primary),
                Text('${w['group']} ${w['tf']}  |  ${_i(w['n'])} trades  |  avg ${_n(_d(w['avg']))} per trade  |  win ${_d(w['win']).toStringAsFixed(0)}%',
                    style: context.type.secondary.copyWith(color: p.profit)),
                Text('older ${_n(_d(w['avg_old']))}, newer ${_n(_d(w['avg_new']))}', style: context.type.metadata),
              ]),
            ),
        ],
        if (steps.isNotEmpty)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('Step by step (details)', style: context.type.secondary),
              children: [
                for (final s in steps)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${s['group']} ${s['tf']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
                      Text(
                          s['base_avg'] == null
                              ? 'Bot today: not enough trades'
                              : 'Bot today: ${_i(s['base_n'])} trades, avg ${_n(_d(s['base_avg']))} per trade',
                          style: context.type.secondary),
                      if (s['best'] != null)
                        Text('Best row: ${s['best']}  |  ${_i(s['best_n'])} trades, avg ${_n(_d(s['best_avg']))}  |  ${'${s['best_verdict']}' == 'winner' ? 'WINNER' : 'not proven'}',
                            style: context.type.metadata),
                    ]),
                  ),
              ],
            ),
          ),
        if (sdAnswer.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('SD LENGTH TEST (majors): 200 candles today vs 150 / 100 / 50, with and without the SD0 rule',
              style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.0)),
          const SizedBox(height: 6),
          for (final l in sdAnswer)
            Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(l, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
          for (final t in sdTfs) _sdTable(context, t),
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('SD length: each timeframe (details)', style: context.type.secondary),
              children: [
                for (final t in sdTfs)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${t['tf']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
                      for (final line in ((t['lines'] is List) ? (t['lines'] as List) : const []))
                        Padding(padding: const EdgeInsets.only(top: 3), child: Text('$line', style: context.type.metadata)),
                    ]),
                  ),
              ],
            ),
          ),
        ],
        if (answer.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
                'ROI points after fees, from a replay (no slippage). A winner must be positive in both the older and the newer data. '
                'Many rows are tested on the same data, so try a winner on paper first. Full report: ~/owl_data/scan_lab.txt',
                style: context.type.metadata),
          ),
      ]),
    );
  }
}
