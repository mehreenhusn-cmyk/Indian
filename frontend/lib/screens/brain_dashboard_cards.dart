import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part M3 (Brain Dashboard), part 2 of 2: the cards, built from the Part M3 answer (/api/v2/brain_dash). Read-only, no state.
/// Ideas from mock pictures 11 and 15, with REAL numbers only: Today net (gross / fees / slippage), Brain 30 days next to Current Bot 30 days (two numbers, never added),
/// open positions, today signals, daily loss cap bar, recent days strip, all-time Brain net, the Brain's own sentence. No account balance is shown (none is real). Dart NOT compiled.

Map<String, dynamic> bdMap(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> bdList(Object? v) => v is List ? [for (final e in v) bdMap(e)] : <Map<String, dynamic>>[];
double bdNum(Object? v) => v is num ? v.toDouble() : 0.0;
String bdSg(Object? v) => '${bdNum(v) >= 0 ? '+' : ''}${bdNum(v).toStringAsFixed(2)}';
Color bdNet(AppPalette p, Object? v) => bdNum(v) > 0 ? p.profit : bdNum(v) < 0 ? p.loss : p.textMuted;

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

Widget _todayCard(AppPalette p, Map<String, dynamic> r) {
  final t = bdMap(r['today']);
  final why = bdMap(r['why']);
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Today Net P&L (Owl Brain)', style: TextStyle(fontSize: 13, color: p.textSecondary)),
      const SizedBox(height: 4),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(bdSg(t['net_usdt']), style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800, color: bdNet(p, t['net_usdt']))),
        const SizedBox(width: 6),
        Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('USDT', style: TextStyle(fontSize: 13, color: p.textMuted))),
      ]),
      Text('${bdSg(t['pct_of_capital'])}% of ${bdNum(r['capital_usdt']).toStringAsFixed(0)} USDT guard capital, ${t['closed'] ?? 0} closed trades', style: TextStyle(fontSize: 11.5, color: bdNet(p, t['net_usdt']))),
      const SizedBox(height: 12),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _kv(p, bdSg(t['gross_usdt']), 'Gross', bdNet(p, t['gross_usdt'])),
        _kv(p, bdSg(t['fees_usdt']), 'Fees', p.loss),
        _kv(p, bdSg(t['slippage_usdt']), 'Slippage', p.loss),
        _kv(p, bdSg(t['net_usdt']), 'Final net', bdNet(p, t['net_usdt'])),
      ]),
      const SizedBox(height: 12),
      Text('Why: ${why['word'] ?? ''}. ${why['text'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
    ]),
  );
}

Widget _half(AppPalette p, String name, String big, String sub, Color c) => Expanded(
      child: OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(name, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 6),
          Text(big, style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: c)),
          Text('USDT', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
          const SizedBox(height: 4),
          Text(sub, style: TextStyle(fontSize: 10.5, color: p.textSecondary)),
        ]),
      ),
    );

Widget _paceRow(AppPalette p, Map<String, dynamic> r) {
  final pc = bdMap(r['pace30']);
  final t = bdMap(r['today']);
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _half(p, 'Brain, ${pc['days'] ?? 0} days', bdSg(pc['brain_usdt']), '${pc['brain_trades'] ?? 0} trades', bdNet(p, pc['brain_usdt'])),
      const SizedBox(width: 10),
      _half(p, 'Current Bot, ${pc['days'] ?? 0} days', bdSg(pc['bot_usdt']), '${pc['bot_trades'] ?? 0} trades, today ${bdSg(t['bot_net_usdt'])}', bdNet(p, pc['bot_usdt'])),
    ]),
    const SizedBox(height: 4),
    Text('Different trades, two separate numbers, never added.', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
  ]);
}

Widget _openAndSignals(AppPalette p, Map<String, dynamic> r) {
  final o = bdMap(r['open']);
  final d = bdMap(r['decisions']);
  return Column(children: [
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Open positions', 'Brain trades that are not closed yet'),
        Row(children: [
          _kv(p, '${o['total'] ?? 0}', 'Open now'),
          _kv(p, '${o['long'] ?? 0}', 'Long', p.profit),
          _kv(p, '${o['short'] ?? 0}', 'Short', p.loss),
        ]),
      ]),
    ),
    const SizedBox(height: 10),
    OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, 'Today signals', 'What the Brain decided today'),
        Row(children: [
          _kv(p, '${d['taken'] ?? 0}', 'Taken', p.profit),
          _kv(p, '${d['waited'] ?? 0}', 'Waited'),
          _kv(p, '${d['skipped'] ?? 0}', 'Skipped'),
          _kv(p, '${d['no_opinion'] ?? 0}', 'No opinion'),
        ]),
      ]),
    ),
  ]);
}

Widget _riskCard(AppPalette p, Map<String, dynamic> r) {
  final k = bdMap(r['risk']);
  final pct = bdNum(k['used_pct']);
  final hit = k['hit'] == true;
  final c = hit ? p.loss : pct >= 50 ? p.warning : p.profit;
  return OWLCard(
    edge: hit || k['kill_switch'] == true ? p.loss : null,
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(p, 'Daily risk limit', 'Daily loss cap of the guard: ${bdNum(k['cap_pct']).toStringAsFixed(1)}% of ${bdNum(k['capital_usdt']).toStringAsFixed(0)} USDT'),
      Row(children: [
        Text('Used ${bdNum(k['used_usdt']).toStringAsFixed(2)} / ${bdNum(k['cap_usdt']).toStringAsFixed(2)} USDT', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
        const Spacer(),
        Text('${pct.toStringAsFixed(1)}%', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: c)),
      ]),
      const SizedBox(height: 8),
      ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: LinearProgressIndicator(value: (pct / 100.0).clamp(0.0, 1.0).toDouble(), minHeight: 10, backgroundColor: p.border, valueColor: AlwaysStoppedAnimation<Color>(c)),
      ),
      const SizedBox(height: 8),
      Text(hit ? 'The cap is HIT: no new trade until tomorrow.' : 'Only a net loss of today uses the cap. A profit day uses 0.', style: TextStyle(fontSize: 11.5, color: hit ? p.loss : p.textSecondary)),
      Text('Kill switch: ${k['kill_switch'] == true ? 'ON (everything stopped)' : 'off'}', style: TextStyle(fontSize: 11.5, color: k['kill_switch'] == true ? p.loss : p.textSecondary)),
    ]),
  );
}

Widget _recent(AppPalette p, Map<String, dynamic> r) {
  final days = bdList(r['recent']);
  return OWLCard(
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _title(p, 'Recent performance', 'Last days, Brain net (Current Bot small), oldest first'),
      if (days.isEmpty) Text('No closed trade in the last days.', style: TextStyle(fontSize: 12, color: p.textMuted)),
      if (days.isNotEmpty)
        SizedBox(
          height: 74,
          child: ListView(scrollDirection: Axis.horizontal, children: [
            for (final d in days)
              Container(
                width: 70,
                margin: const EdgeInsets.only(right: 8),
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${d['day']}'.length >= 10 ? '${d['day']}'.substring(5) : '${d['day']}', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
                  const SizedBox(height: 4),
                  Text(bdSg(d['brain_usdt']), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: bdNet(p, d['brain_usdt']))),
                  Text('Bot ${bdSg(d['bot_usdt'])}', style: TextStyle(fontSize: 9.5, color: bdNet(p, d['bot_usdt']))),
                ]),
              ),
          ]),
        ),
    ]),
  );
}

Widget _allTime(AppPalette p, Map<String, dynamic> r) {
  final a = bdMap(r['all_time']);
  return OWLCard(
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _kv(p, bdSg(a['net_usdt']), 'Brain net, all time (USDT)', bdNet(p, a['net_usdt'])),
      _kv(p, '${a['closed'] ?? 0}', 'Closed trades, all time'),
    ]),
  );
}

List<Widget> brainDashboardCards(AppPalette p, Map<String, dynamic> r) => [
      _todayCard(p, r),
      _paceRow(p, r),
      _openAndSignals(p, r),
      _riskCard(p, r),
      _recent(p, r),
      _allTime(p, r),
      OWLCard(edge: p.warning, child: Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
    ];
