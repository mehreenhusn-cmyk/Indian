import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/equity_line.dart';
import '../widgets/owl_card.dart';

/// Part X2 (Day calendar + comparison), part 2 of 2: the cards of ONE chosen day, from the Part X1 answer (/api/v2/brain_compare). Read-only, no state.
/// Cards: three-arm comparison (Owl Brain / Current Bot / Take-All), money split (gross, fees, slippage, net), decision counts, worst dip + losing streak, equity line, plain sentences, honest note.
/// Take-All is a SIMULATION on saved candles; the Brain and the Current Bot are different trades, so this is NOT a same-signal test (said on the screen). Dart NOT compiled.

Map<String, dynamic> dcMap(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> dcList(Object? v) => v is List ? [for (final e in v) dcMap(e)] : <Map<String, dynamic>>[];
double dcNum(Object? v) => v is num ? v.toDouble() : 0.0;
String dcSg(Object? v) => '${dcNum(v) >= 0 ? '+' : ''}${dcNum(v).toStringAsFixed(2)}';
Color dcNet(AppPalette p, Object? v) => dcNum(v) > 0 ? p.profit : dcNum(v) < 0 ? p.loss : p.textMuted;

Widget _col(AppPalette p, String name, Map<String, dynamic> a, String sub) => Expanded(
      child: Column(children: [
        Text(name, textAlign: TextAlign.center, style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
        const SizedBox(height: 4),
        Text(dcSg(a['net_usdt']), style: TextStyle(fontSize: 19, fontWeight: FontWeight.w800, color: dcNet(p, a['net_usdt']))),
        Text('${dcSg(a['pct_of_capital'])}%', style: TextStyle(fontSize: 11, color: dcNet(p, a['net_usdt']))),
        Text(sub, textAlign: TextAlign.center, style: TextStyle(fontSize: 10, color: p.textMuted)),
      ]),
    );

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

List<Widget> dayCompareCards(AppPalette p, Map<String, dynamic> r) {
  final b = dcMap(r['brain']);
  final bot = dcMap(r['current_bot']);
  final ta = dcMap(r['take_all']);
  final b2 = dcMap(r['brain_bt02']);
  final dec = dcMap(b['decisions']);
  final dd = dcMap(b['drawdown']);
  final st = dcMap(b['streak']);
  final pts = [for (final e in dcList(b['equity'])) dcNum(e['v'])];
  final total = dcNum(dec['total']);
  String pc(Object? n) => total <= 0 ? '' : ' (${(dcNum(n) / total * 100).toStringAsFixed(0)}%)';
  return [
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Performance comparison (net, USDT)', 'Three separate numbers, never added'),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _col(p, 'Owl Brain', b, '${b['closed'] ?? 0} closed'),
          _col(p, 'Current Bot', bot, '${bot['closed'] ?? 0} closed'),
          _col(p, 'Take-All (simulated)', ta, '${ta['taken'] ?? 0} ideas'),
        ]),
        const SizedBox(height: 10),
        Text('Same Brain, two exits (Part E5)', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: p.textSecondary)),
        const SizedBox(height: 6),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _col(p, 'PAPER (BT-01, then BT-03 manager)', b, '${b['closed'] ?? 0} closed'),
          _col(p, 'BT-02 (SHADOW) Brain decides exit', b2, '${b2['closed'] ?? 0} closed'),
        ]),
        const SizedBox(height: 8),
        for (final s in (r['lines'] is List ? (r['lines'] as List) : const []))
          Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('$s', style: TextStyle(fontSize: 12, color: p.textSecondary))),
      ]),
    ),
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Owl Brain money split', 'USDT, after fee and slippage'),
        Row(children: [
          _kv(p, dcSg(b['gross_usdt']), 'Gross', dcNet(p, b['gross_usdt'])),
          _kv(p, dcSg(b['fees_usdt']), 'Fees', p.loss),
          _kv(p, dcSg(b['slippage_usdt']), 'Slippage', p.loss),
          _kv(p, dcSg(b['net_usdt']), 'Net', dcNet(p, b['net_usdt'])),
        ]),
      ]),
    ),
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'What the Brain did today', 'All saved decisions of the day'),
        Row(children: [
          _kv(p, '${b['closed'] ?? 0}', 'Closed trades'),
          _kv(p, '${dec['taken'] ?? 0}${pc(dec['taken'])}', 'Taken'),
          _kv(p, '${dec['waited'] ?? 0}${pc(dec['waited'])}', 'Waited'),
          _kv(p, '${dec['skipped'] ?? 0}${pc(dec['skipped'])}', 'Skipped'),
          _kv(p, '${dec['no_opinion'] ?? 0}${pc(dec['no_opinion'])}', 'No opinion'),
        ]),
      ]),
    ),
    OWLCard(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _kv(p, '-${dcNum(dd['max_usdt']).toStringAsFixed(2)}', 'Worst dip (USDT)', p.warning),
        _kv(p, '${st['longest'] ?? 0}', 'Longest losing streak (now ${st['current'] ?? 0})'),
      ]),
    ),
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Equity curve (USDT)', 'Owl Brain, running net after each closed trade'),
        if (pts.length < 2) Text('No closed trade on this day.', style: TextStyle(fontSize: 12.5, color: p.textMuted)) else EquityLine(values: pts, line: p.accent, grid: p.border),
      ]),
    ),
    OWLCard(
      edge: p.warning,
      child: Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
    ),
  ];
}
