import 'package:flutter/material.dart';

import '../theme/app_theme.dart';

/// Doctor Verdict - plain-language "what to change" cards (hold time, profit leakage, best/worst slots).
/// Read-only: it only draws the `verdict` block the backend (doctor_verdict.py) sends. Nothing here changes the bot.
class DoctorVerdictCard extends StatelessWidget {
  final Map<String, dynamic> verdict;
  const DoctorVerdictCard({super.key, required this.verdict});

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static List<Map<String, dynamic>> _rows(dynamic v) =>
      (v is List) ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  static List<String> _studies(Map<String, dynamic> v) => (v['studies'] is List) ? (v['studies'] as List).map((e) => '$e').toList() : <String>[];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final lines = (verdict['lines'] is List) ? (verdict['lines'] as List).map((e) => '$e').toList() : <String>[];
    final enough = verdict['enough'] == true;
    final unit = '${verdict['unit'] ?? 'Rs'}';
    final lk = (verdict['leakage'] is Map) ? Map<String, dynamic>.from(verdict['leakage']) : <String, dynamic>{};
    final tables = <MapEntry<String, String>>[
      const MapEntry('hold', 'How long to hold'),
      const MapEntry('time_of_day', 'Time of day'),
      const MapEntry('entry_zone', 'SD entry zone'),
      const MapEntry('tsi_x_zone', 'TSI x SD zone'),
      const MapEntry('tsi_vs_trade', 'TSI with / against trade'),
      const MapEntry('tsi_band', 'TSI level'),
      const MapEntry('z_band', 'Z-score level'),
      const MapEntry('index', 'Index'),
      const MapEntry('side', 'CE / PE'),
      const MapEntry('timeframe', 'Timeframe'),
    ];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _box(context, enough ? p.accent : p.warning, [
        Row(children: [
          Icon(Icons.fact_check_outlined, size: 18, color: p.accent),
          const SizedBox(width: 8),
          Expanded(child: Text('Doctor Verdict', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
          Text(enough ? '${_i(verdict['n'])} trades' : 'not enough data',
              style: context.type.label.copyWith(color: enough ? p.accent : p.warning)),
        ]),
        const SizedBox(height: 10),
        for (final l in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text(l, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
          ),
      ]),
      if (_studies(verdict).isNotEmpty)
        _box(context, null, [
          Text('OTHER AI STUDIES', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.1)),
          const SizedBox(height: 8),
          for (final l in _studies(verdict))
            Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(l, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
        ]),
      if (_i(lk['known']) > 0)
        _box(context, null, [
          Text('PROFIT LEAKAGE', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.1)),
          const SizedBox(height: 8),
          _kv(context, 'Trades with peak data', '${_i(lk['known'])} of ${_i(lk['total'])}'),
          _kv(context, 'Avg peak profit', '${_d(lk['avg_peak_roi']).toStringAsFixed(1)}%'),
          _kv(context, 'Avg final result', '${_d(lk['avg_final_roi']).toStringAsFixed(1)}%'),
          _kv(context, 'Avg given back (green trades)', '${_d(lk['avg_given_back']).toStringAsFixed(1)} pts'),
          _kv(context, 'Hit TP1, still lost', '${_i(lk['tp1_then_loss_n'])} trades (${_d(lk['tp1_then_loss_rs']).toStringAsFixed(0)} $unit)'),
        ]),
      for (final t in tables)
        if (_rows(verdict[t.key]).isNotEmpty)
          _box(context, null, [
            Text(t.value.toUpperCase(), style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.1)),
            const SizedBox(height: 8),
            for (final r in _rows(verdict[t.key])) _row(context, r, unit),
          ]),
      Padding(
        padding: const EdgeInsets.fromLTRB(2, 0, 2, 10),
        child: Text(
            'Suggestions only. Each group is checked on the older 70% and the newest 30% of trades. '
            '"bad/good on both" is a lead to watch, not a guarantee. The bot is not changed.',
            style: context.type.secondary.copyWith(fontSize: 11.5)),
      ),
    ]);
  }

  Widget _box(BuildContext context, Color? accent, List<Widget> children) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: (accent ?? p.glassBorder).withOpacity(accent == null ? 1 : 0.55)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );
  }

  Widget _kv(BuildContext context, String k, String v) => Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(children: [
          Expanded(child: Text(k, style: context.type.secondary)),
          Text(v, style: context.type.secondary.copyWith(color: context.palette.textPrimary, fontWeight: FontWeight.w600)),
        ]),
      );

  Widget _row(BuildContext context, Map<String, dynamic> r, String unit) {
    final p = context.palette;
    final st = '${r['status']}';
    final c = st == 'confirmed_bad' ? p.loss : (st == 'confirmed_good' ? p.profit : p.textMuted);
    final tag = st == 'confirmed_bad' ? 'bad on both' : (st == 'confirmed_good' ? 'good on both' : (st == 'mixed' ? 'mixed' : 'few trades'));
    final net = _d(r['net']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 7),
      child: Row(children: [
        Expanded(
          flex: 5,
          child: Text('${r['label']}', style: context.type.secondary.copyWith(color: p.textPrimary)),
        ),
        Expanded(
          flex: 4,
          child: Text('${_i(r['n'])} tr · ${_d(r['win_rate']).toStringAsFixed(0)}% win',
              style: context.type.secondary.copyWith(fontSize: 12)),
        ),
        Expanded(
          flex: 3,
          child: Text('${net >= 0 ? '+' : ''}${net.toStringAsFixed(0)}',
              textAlign: TextAlign.right,
              style: context.type.secondary.copyWith(color: net >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w700)),
        ),
        const SizedBox(width: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(6)),
          child: Text(tag, style: TextStyle(fontSize: 10.5, color: c, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }
}
