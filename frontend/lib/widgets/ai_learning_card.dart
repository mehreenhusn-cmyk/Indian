import 'dart:async';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// "AI ne kya seekha": the research view of the EMA50 strategy.
///   timeline   - how much the AI has seen / validated and how many patterns are in which stage
///   WORKS / FAILS / STILL UNCERTAIN - each with sample count, validation count and an EVIDENCE
///                status (DISCOVERED / VALIDATING / CONFIRMED / STABLE / WEAKENING / REJECTED) -
///                never a fake "AI confidence %"
///   per timeframe (3m / 5m / 15m): TP1->TP4 funnel, what happens after TP1, what stalled or
///                lost had in common, higher-timeframe agreement, Top-10 gainer / loser side
/// Everything is counted by the backend (ai_learning.py / ai_shadow_lab.py). This widget only draws
/// it. These are historical associations - the AI never opens, blocks or changes a trade.
class AiLearningCard extends StatefulWidget {
  const AiLearningCard({super.key});

  @override
  State<AiLearningCard> createState() => _AiLearningCardState();
}

class _AiLearningCardState extends State<AiLearningCard> {
  Map<String, dynamic>? _d;
  bool _failed = false;
  String _tf = '3m';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 45), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool refresh = false}) async {
    final r = await context.read<AppProvider>().fetchAiLearning(refresh: refresh);
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _d = r;
        _failed = false;
        final tfs = _m(r['tfs']);
        if (!tfs.containsKey(_tf) && tfs.isNotEmpty) _tf = tfs.keys.first;
      } else if (_d == null) {
        _failed = true;
      }
    });
  }

  // ----------------------------------------------------------- helpers
  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _pc(dynamic v, {int d = 0}) => v is num ? '${v.toStringAsFixed(d)}%' : '-';
  static String _sg(dynamic v, {int d = 2}) =>
      v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%' : '-';

  Color _statusColor(AppPalette p, String s) {
    switch (s) {
      case 'STABLE':
        return p.profit;
      case 'CONFIRMED':
        return p.profit;
      case 'VALIDATING':
        return p.accent;
      case 'DISCOVERED':
        return p.warning;
      case 'WEAKENING':
        return p.warning;
      case 'REJECTED':
        return p.loss;
    }
    return p.textMuted;
  }

  String _ago(dynamic ts) {
    final t = _n(ts);
    if (t <= 0) return '-';
    final s = DateTime.now().millisecondsSinceEpoch / 1000.0 - t;
    if (s < 90) return 'abhi';
    return '${fmtSpan(s)} pehle';
  }

  // ----------------------------------------------------------- build
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    return ListView(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, 96),
      children: [
        if (d == null)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: Center(
              child: Text(_failed ? 'Learning data nahi mila - backend check karo.' : 'Load ho raha hai...',
                  style: context.type.secondary.copyWith(color: p.textMuted)),
            ),
          )
        else ...[
          _timeline(context, p, d),
          const SizedBox(height: 10),
          _answers(context, p, d),
          const SizedBox(height: 10),
          _tfSection(context, p, d),
          const SizedBox(height: 10),
          _caveats(context, p, d),
        ],
      ],
    );
  }

  Widget _box(AppPalette p, {required Widget child, Color? border}) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: (border ?? p.border).withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _chip(AppPalette p, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(
          color: c.withOpacity(0.14),
          borderRadius: BorderRadius.circular(6),
        ),
        child: Text(text, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _title(BuildContext context, String t, {String? sub}) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.section.copyWith(fontSize: 14)),
          if (sub != null) Text(sub, style: context.type.metadata),
        ]),
      );

  // ----------------------------------------------------------- 1. timeline
  Widget _timeline(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final t = _m(d['timeline']);
    final pat = _m(t['patterns']);
    const order = ['DISCOVERED', 'VALIDATING', 'CONFIRMED', 'STABLE', 'WEAKENING', 'REJECTED'];
    final signals = _i(t['signals']);
    return _box(
      p,
      border: p.purple,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: _title(context, 'AI Learning', sub: 'sirf observer - koi trade change / block nahi')),
          GestureDetector(
            onTap: () => _load(refresh: true),
            child: Icon(Icons.refresh_rounded, size: 18, color: p.textMuted),
          ),
        ]),
        Row(children: [
          _stat(context, 'Signals dekhe', '$signals'),
          _stat(context, 'Validation (naya data)', '${_i(t['validated'])}'),
          _stat(context, 'Live (rank saved)', '${_i(t['live_signals'])}'),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final s in order)
            if (_i(pat[s]) > 0) _chip(p, '${_i(pat[s])} $s', _statusColor(p, s)),
          if (order.every((s) => _i(pat[s]) == 0)) Text('Abhi koi pattern nahi mila.', style: context.type.metadata),
        ]),
        const SizedBox(height: 8),
        Text(
          'Lab: ${t['lab_phase'] ?? '-'}  |  last update: ${_ago(d['built'])}'
          '${d['busy'] == true ? '  |  rebuilding...' : ''}',
          style: context.type.metadata,
        ),
        if (signals == 0)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              'Shadow Lab ke signals aane do (replay + live). Phir yahan sab bharega.',
              style: context.type.secondary,
            ),
          ),
      ]),
    );
  }

  Widget _stat(BuildContext context, String l, String v) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(v, style: context.type.primary.copyWith(fontSize: 18, fontWeight: FontWeight.w800)),
          Text(l, style: context.type.metadata.copyWith(fontSize: 10)),
        ]),
      );

  // ----------------------------------------------------------- 2. works / fails / uncertain
  Widget _answers(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final a = _m(d['answers']);
    final works = _l(a['works']);
    final fails = _l(a['fails']);
    final unsure = _l(a['unsure']);
    final rej = _l(a['rejected']);
    return Column(children: [
      _group(context, p, 'WHAT WORKS', 'in conditions me signal baaki se behtar raha', works, p.profit,
          'Abhi koi CONFIRMED scenario nahi.'),
      const SizedBox(height: 10),
      _group(context, p, 'WHAT FAILS', 'in conditions me signal baaki se kharab raha', fails, p.loss,
          'Abhi koi CONFIRMED kharab scenario nahi.'),
      const SizedBox(height: 10),
      _group(context, p, 'STILL UNCERTAIN', 'mila hai, par naye data par pakka nahi', unsure, p.warning,
          'Kuch nahi - sab ya to confirmed hai ya reject.'),
      if (rej.isNotEmpty) ...[
        const SizedBox(height: 10),
        _group(context, p, 'REJECTED', 'purane data me dikha, naye data me nahi tika (luck tha)', rej.take(4).toList(),
            p.textMuted, ''),
      ],
    ]);
  }

  Widget _group(BuildContext context, AppPalette p, String title, String sub, List<Map<String, dynamic>> rows,
      Color color, String emptyText) {
    return _box(
      p,
      border: color,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(context, title, sub: sub),
        if (rows.isEmpty) Text(emptyText, style: context.type.secondary),
        for (final r in rows) _patternRow(context, p, r),
      ]),
    );
  }

  Widget _patternRow(BuildContext context, AppPalette p, Map<String, dynamic> r) {
    final st = (r['status'] ?? '').toString();
    final label = (r['label'] ?? '').toString().replaceAll('  +  ', '  +  ');
    final nNew = _i(r['n_new']);
    final hasEv = r['n'] != null;
    final lines = <String>[];
    if (hasEv) {
      lines.add('${_i(r['n_old'])} purane + $nNew naye signals | win ${_pc(r['win_rate'])} | avg ${_sg(r['avg'])} ROI');
      if (r['avg_new'] != null) lines.add('naye data par: ${_sg(r['avg_new'])} (purane: ${_sg(r['avg_old'])})');
      if (r['coins'] != null) lines.add('${_i(r['coins'])} coins, ${_i(r['days'])} din');
      if (r['kind'] == 'TAKE' && r['net_positive'] == false) lines.add('baaki se behtar, par abhi bhi net negative');
    } else if (r['gone'] == true) {
      lines.add('ab dobara nahi mila');
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _chip(p, (r['tf'] ?? '').toString(), p.accent),
          const SizedBox(width: 6),
          _chip(p, st, _statusColor(p, st)),
        ]),
        const SizedBox(height: 4),
        Text(label, style: context.type.primary.copyWith(fontSize: 13)),
        for (final l in lines) Text(l, style: context.type.metadata),
      ]),
    );
  }

  // ----------------------------------------------------------- 3. per timeframe
  Widget _tfSection(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final tfs = _m(d['tfs']);
    if (tfs.isEmpty) return const SizedBox.shrink();
    final e = _m(tfs[_tf]);
    final f = _m(e['funnel']);
    final reach = _l(f['reach']);
    final post = _m(f['after_tp1']);
    final ex = _m(f['excursion']);
    return _box(
      p,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(context, 'Strategy kaise chali', sub: 'har timeframe alag ginta hai, same move teeno me hota hai'),
        Row(children: [
          for (final k in tfs.keys)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: GestureDetector(
                onTap: () => setState(() => _tf = k),
                child: _chip(p, k, k == _tf ? p.accent : p.textMuted),
              ),
            ),
        ]),
        const SizedBox(height: 10),
        Text(
          '${_i(e['n'])} signals | live rule win ${_pc(e['win_pct'], d: 1)}'
          '${e['breakeven_wr'] is num ? ' | break-even ~${_pc(e['breakeven_wr'])}' : ''}'
          '${e['avg_roi'] is num ? ' | avg ${_sg(e['avg_roi'])}' : ''}',
          style: context.type.secondary,
        ),
        const SizedBox(height: 10),
        if (reach.isNotEmpty) ...[
          Text('TP funnel (kitne signal yahan tak pahunche)', style: context.type.label),
          const SizedBox(height: 4),
          for (final r in reach) _bar(context, p, 'TP${_i(r['tp'])}', _n(r['pct']), '${_pc(r['pct'], d: 1)}  (${_i(r['n'])})'),
        ],
        if (post.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text('TP1 ke baad kya hua (${_i(post['n'])} signals)', style: context.type.label),
          const SizedBox(height: 4),
          _bar(context, p, 'TP2 tak gaya', _n(post['continue_tp2']), _pc(post['continue_tp2'])),
          _bar(context, p, 'entry par wapas', _n(post['back_to_entry']), _pc(post['back_to_entry'])),
          _bar(context, p, 'baaki', _n(post['other']), _pc(post['other'])),
        ],
        if (ex.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(
            'Entry ke baad (median): sahi taraf max ${_n(ex['mfe_median']).toStringAsFixed(2)}%, '
            'ulta max ${_n(ex['mae_median']).toStringAsFixed(2)}% (80% signals me ulta <= '
            '${_n(ex['mae_p80']).toStringAsFixed(2)}%) - price move, ROI nahi.',
            style: context.type.metadata,
          ),
        ],
        ..._stalls(context, p, f),
        ..._loss(context, p, _m(e['loss'])),
        ..._table(context, p, 'Higher timeframe agree kare to?', _l(e['mtf'])),
        ..._table(context, p, 'Top-10 gainer / loser side (sirf live signals)', _l(e['market'])),
      ]),
    );
  }

  Widget _bar(BuildContext context, AppPalette p, String l, double pct, String right) {
    final w = (pct / 100.0).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(children: [
        SizedBox(width: 92, child: Text(l, style: context.type.metadata)),
        Expanded(
          child: Stack(children: [
            Container(height: 8, decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(4))),
            FractionallySizedBox(
              widthFactor: w,
              child: Container(height: 8, decoration: BoxDecoration(color: p.accent, borderRadius: BorderRadius.circular(4))),
            ),
          ]),
        ),
        const SizedBox(width: 8),
        SizedBox(width: 92, child: Text(right, textAlign: TextAlign.right, style: context.type.metadata)),
      ]),
    );
  }

  List<Widget> _stalls(BuildContext context, AppPalette p, Map<String, dynamic> f) {
    final out = <Widget>[];
    for (final s in _l(f['stalls'])) {
      final causes = _l(s['causes']);
      if (causes.isEmpty) continue;
      out.add(const SizedBox(height: 10));
      out.add(Text('TP${_i(s['from'])} -> TP${_i(s['to'])} rukne ke case (${_pc(s['stall_pct'])} ruke)', style: context.type.label));
      for (final c in causes.take(3)) out.add(_assocRow(context, p, c, 'ruka'));
    }
    return out;
  }

  List<Widget> _loss(BuildContext context, AppPalette p, Map<String, dynamic> loss) {
    if (loss['ready'] != true) return [];
    final fails = _l(loss['fails']);
    final works = _l(loss['works']);
    if (fails.isEmpty && works.isEmpty) return [];
    return [
      const SizedBox(height: 10),
      Text('Stop-loss kab zyada / kam laga (base ${_pc(loss['base'])})', style: context.type.label),
      for (final c in fails.take(3)) _assocRow(context, p, c, 'SL'),
      for (final c in works.take(2)) _assocRow(context, p, c, 'SL'),
    ];
  }

  Widget _assocRow(BuildContext context, AppPalette p, Map<String, dynamic> c, String what) {
    final st = (c['status'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _chip(p, st, _statusColor(p, st)),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            '${c['label']}: $what ${_pc(c['rate'])} (${_i(c['n_old'])} purane, ${_i(c['n_new'])} naye)',
            style: context.type.metadata.copyWith(color: p.textSecondary),
          ),
        ),
      ]),
    );
  }

  List<Widget> _table(BuildContext context, AppPalette p, String title, List<Map<String, dynamic>> rows) {
    if (rows.isEmpty) return [];
    return [
      const SizedBox(height: 10),
      Text(title, style: context.type.label),
      for (final r in rows)
        Padding(
          padding: const EdgeInsets.only(top: 3),
          child: Row(children: [
            Expanded(child: Text('${r['label']}', style: context.type.secondary.copyWith(fontSize: 12))),
            Text('${_i(r['n'])} | win ${_pc(r['win_pct'])} | ${_sg(r['avg_roi'])}', style: context.type.metadata),
          ]),
        ),
    ];
  }

  // ----------------------------------------------------------- caveats
  Widget _caveats(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final c = (d['caveats'] is List) ? (d['caveats'] as List).map((e) => e.toString()).toList() : <String>[];
    if (c.isEmpty) return const SizedBox.shrink();
    return _box(
      p,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Dhyan rakho', style: context.type.label),
        const SizedBox(height: 4),
        for (final t in c)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text('- $t', style: context.type.metadata),
          ),
      ]),
    );
  }
}
