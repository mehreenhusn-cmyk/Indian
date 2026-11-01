import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part L2 (Learning Progress), part 2 of 2: the cards, built from the Part L1 answer (/api/v2/brain_progress). Read-only, no state.
/// Cards: Brain today (trades / profit / loss / net / decisions), Is the Brain getting better (older vs newer half), the 5 weeks (losing trades per 10 = the mistake rate),
/// Mistakes, Fixed (a hint, not proof), Got worse, What it learned, the last days, honest note. No win-rate headline, no forecast. Dart NOT compiled.

Map<String, dynamic> lpMap(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> lpList(Object? v) => v is List ? [for (final e in v) lpMap(e)] : <Map<String, dynamic>>[];
List<String> lpLines(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
double lpNum(Object? v) => v is num ? v.toDouble() : 0.0;
String lpSg(Object? v) => '${lpNum(v) >= 0 ? '+' : ''}${lpNum(v).toStringAsFixed(2)}';
Color lpNet(AppPalette p, Object? v) => lpNum(v) > 0 ? p.profit : lpNum(v) < 0 ? p.loss : p.textMuted;

Widget _kv(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );

Widget _title(AppPalette p, String t, [String? sub]) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(t, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
      if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
      const SizedBox(height: 10),
    ]);

Widget _today(AppPalette p, Map<String, dynamic> r) {
  final t = lpMap(r['today']);
  final d = lpMap(t['decisions']);
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(p, 'Brain today', 'Closed trades of today (UTC day), net of fee and slippage'),
      Row(children: [
        _kv(p, '${t['trades'] ?? 0}', 'Trades'),
        _kv(p, '${t['profit'] ?? 0}', 'Profit trades', p.profit),
        _kv(p, '${t['loss'] ?? 0}', 'Loss trades', p.loss),
        _kv(p, lpSg(t['net_usdt']), 'Net USDT', lpNet(p, t['net_usdt'])),
      ]),
      const SizedBox(height: 10),
      Text('${t['text'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
      const SizedBox(height: 6),
      Text('Decisions today: ${d['taken'] ?? 0} taken, ${d['waited'] ?? 0} waited, ${d['skipped'] ?? 0} skipped, ${d['no_opinion'] ?? 0} no opinion.',
          style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
    ]),
  );
}

Widget _trend(AppPalette p, Map<String, dynamic> r) {
  final t = lpMap(r['trend']);
  final o = lpMap(t['older']);
  final n = lpMap(t['newer']);
  final word = '${t['word'] ?? 'NOT ENOUGH DATA'}';
  final c = word == 'IMPROVING' ? p.profit : word == 'WORSE' ? p.loss : word == 'NOT ENOUGH DATA' ? p.textMuted : p.warning;
  final has = o['avg_usdt'] != null && n['avg_usdt'] != null;
  return OWLCard(
    edge: c,
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(p, 'Is the Brain getting better?', 'Older half of all closed trades against the newer half'),
      Text(word, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: c)),
      const SizedBox(height: 8),
      if (has)
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _kv(p, lpSg(o['avg_usdt']), 'Older: USDT per trade', lpNet(p, o['avg_usdt'])),
          _kv(p, lpSg(n['avg_usdt']), 'Newer: USDT per trade', lpNet(p, n['avg_usdt'])),
          _kv(p, lpNum(o['loss_per_10']).toStringAsFixed(1), 'Older: losing per 10'),
          _kv(p, lpNum(n['loss_per_10']).toStringAsFixed(1), 'Newer: losing per 10'),
        ]),
      if (has) const SizedBox(height: 8),
      Text('${t['text'] ?? ''}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
    ]),
  );
}

Widget _weekRow(AppPalette p, Map<String, dynamic> w) {
  final n = lpNum(w['trades']).toInt();
  final k = lpNum(w['week']).toInt();
  final per10 = lpNum(w['loss_per_10']);
  final frac = (per10 / 10.0).clamp(0.0, 1.0).toDouble();
  return Padding(
    padding: const EdgeInsets.only(bottom: 10),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SizedBox(width: 70, child: Text(k == 0 ? 'This week' : '$k wk ago', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textPrimary))),
      Expanded(
        child: n == 0
            ? Text('no closed trade', style: TextStyle(fontSize: 11.5, color: p.textMuted))
            : Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                SizedBox(
                  height: 8,
                  child: Stack(children: [
                    Container(decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(4))),
                    FractionallySizedBox(
                      widthFactor: frac,
                      alignment: Alignment.centerLeft,
                      child: Container(decoration: BoxDecoration(color: p.loss, borderRadius: BorderRadius.circular(4))),
                    ),
                  ]),
                ),
                const SizedBox(height: 3),
                Text('$n trades: ${w['profit'] ?? 0} profit, ${w['loss'] ?? 0} loss, ${per10.toStringAsFixed(1)} losing per 10',
                    style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              ]),
      ),
      SizedBox(width: 62, child: Text(n == 0 ? '-' : lpSg(w['net_usdt']), textAlign: TextAlign.right, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: lpNet(p, w['net_usdt'])))),
    ]),
  );
}

Widget _weeks(AppPalette p, Map<String, dynamic> r) => OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Learning curve, week by week', 'Bar = losing trades per 10 (shorter is better). Number = net USDT of the week'),
        for (final w in lpList(r['weeks'])) _weekRow(p, w),
      ]),
    );

Widget _group(AppPalette p, String title, String sub, List<String> lines, String empty, Color c) => OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, title, sub),
        if (lines.isEmpty) Text(empty, style: TextStyle(fontSize: 12, color: p.textMuted)),
        for (final s in lines)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('\u2022 ', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: c)),
              Expanded(child: Text(s, style: TextStyle(fontSize: 12, color: p.textSecondary))),
            ]),
          ),
      ]),
    );

Widget _days(AppPalette p, Map<String, dynamic> r) {
  final days = lpList(r['days']);
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(p, 'Last days', 'Newest first, days without a closed trade are left out'),
      if (days.isEmpty) Text('No closed trade in the last 30 days.', style: TextStyle(fontSize: 12, color: p.textMuted)),
      for (final d in days.take(10))
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(children: [
            SizedBox(width: 56, child: Text('${d['day']}'.length >= 10 ? '${d['day']}'.substring(5) : '${d['day']}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textPrimary))),
            Expanded(child: Text('${d['trades'] ?? 0} trades: ${d['profit'] ?? 0} profit, ${d['loss'] ?? 0} loss', style: TextStyle(fontSize: 11.5, color: p.textMuted))),
            Text(lpSg(d['net_usdt']), style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: lpNet(p, d['net_usdt']))),
          ]),
        ),
    ]),
  );
}

List<Widget> learningProgressCards(AppPalette p, Map<String, dynamic> r) {
  final worse = lpLines(r['worse']);
  return [
    _today(p, r),
    _trend(p, r),
    _weeks(p, r),
    _group(p, 'Mistakes', 'Groups with 30+ trades that lost in BOTH halves of their history', lpLines(r['mistakes']), 'No group has lost in both halves yet, or no group has 30 trades yet.', p.loss),
    _group(p, 'Fixed (a hint, not proof)', 'Lost in the older half, positive in the newer half', lpLines(r['fixed']), 'Nothing is fixed yet. It needs more trades.', p.profit),
    if (worse.isNotEmpty) _group(p, 'Got worse', 'Positive in the older half, losing in the newer half', worse, '', p.warning),
    _group(p, 'What the Brain learned', 'Groups that won in both halves of their history', lpLines(r['learned']), 'No group has won in both halves yet.', p.profit),
    _days(p, r),
    OWLCard(
      edge: p.warning,
      child: Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
    ),
  ];
}
