import 'package:flutter/material.dart';
import '../widgets/brain_why_card.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R18: text sizes follow the app text scale (nothing below 11, section title 16). Part M3 part 2 of 2, reworked in Part 20 (FILE 39): the DETAIL of the Brain Dashboard, built from /api/v2/brain_dash. Read-only, no state.
/// The ONE summary on top is brain_dashboard_summary.dart (Part 19). Here every detail block is a closed fold with a one-line summary
/// in its title row; tap to open. The Daily risk fold opens by itself when the cap is hit or the kill switch is on.
/// brain_dash has NO coin-wise numbers (backend sends none), so nothing per coin is shown here: no invented data. Dart NOT compiled.

Map<String, dynamic> bdMap(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> bdList(Object? v) => v is List ? [for (final e in v) bdMap(e)] : <Map<String, dynamic>>[];
double bdNum(Object? v) => v is num ? v.toDouble() : 0.0;
String bdSg(Object? v) => '${bdNum(v) >= 0 ? '+' : ''}${bdNum(v).toStringAsFixed(2)}';
Color bdNet(AppPalette p, Object? v) => bdNum(v) > 0 ? p.profit : bdNum(v) < 0 ? p.loss : p.textMuted;

Widget _kv(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );

/// A closed fold: title + one-line summary always visible, detail inside. [edge] colours the rim, [open] opens it at start.
Widget _fold(AppPalette p, String title, String sub, Widget detail, {Color? edge, bool open = false}) => OWLCard(
      edge: edge,
      padding: EdgeInsets.zero,
      child: Builder(builder: (ctx) => Theme(
        data: Theme.of(ctx).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          initiallyExpanded: open,
          tilePadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 2),
          childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 14),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          iconColor: p.textMuted,
          collapsedIconColor: p.textMuted,
          title: Text(title, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600, color: p.textPrimary)),
          subtitle: Text(sub, style: TextStyle(fontSize: 12, color: p.textMuted)),
          children: [detail],
        ),
      )),
    );

Widget _todayDetail(AppPalette p, Map<String, dynamic> r) {
  final t = bdMap(r['today']);
  final why = bdMap(r['why']);
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Text('${bdSg(t['pct_of_capital'])}% of ${bdNum(r['capital_usdt']).toStringAsFixed(0)} USDT guard capital, ${t['closed'] ?? 0} closed trades',
        style: TextStyle(fontSize: 12, color: bdNet(p, t['net_usdt']))),
    const SizedBox(height: 10),
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _kv(p, bdSg(t['gross_usdt']), 'Gross', bdNet(p, t['gross_usdt'])),
      _kv(p, bdSg(t['fees_usdt']), 'Fees', p.loss),
      _kv(p, bdSg(t['slippage_usdt']), 'Slippage', p.loss),
      _kv(p, bdSg(t['net_usdt']), 'Final net', bdNet(p, t['net_usdt'])),
    ]),
    const SizedBox(height: 10),
    Text('Why: ${why['word'] ?? ''}. ${why['text'] ?? ''}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
  ]);
}

Widget _half(AppPalette p, String name, String big, String sub, Color c) => Expanded(
      child: Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(name, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 6),
          Text(big, style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: c)),
          Text('USDT', style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 4),
          Text(sub, style: TextStyle(fontSize: 11, color: p.textSecondary)),
        ]),
      ),
    );

Widget _paceDetail(AppPalette p, Map<String, dynamic> r) {
  final pc = bdMap(r['pace30']);
  final t = bdMap(r['today']);
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _half(p, 'Brain, ${pc['days'] ?? 0} days', bdSg(pc['brain_usdt']), '${pc['brain_trades'] ?? 0} trades', bdNet(p, pc['brain_usdt'])),
      const SizedBox(width: 10),
      _half(p, 'Main bot, ${pc['days'] ?? 0} days', bdSg(pc['bot_usdt']), '${pc['bot_trades'] ?? 0} trades, today ${bdSg(t['bot_net_usdt'])}', bdNet(p, pc['bot_usdt'])),
    ]),
    const SizedBox(height: 6),
    Text('Different trades, two separate numbers, never added.', style: TextStyle(fontSize: 11, color: p.textMuted)),
  ]);
}

Widget _openDetail(AppPalette p, Map<String, dynamic> r) {
  final o = bdMap(r['open']);
  final d = bdMap(r['decisions']);
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Text('Open positions (Brain trades not closed yet)', style: TextStyle(fontSize: 12, color: p.textMuted)),
    const SizedBox(height: 6),
    Row(children: [_kv(p, '${o['total'] ?? 0}', 'Open now'), _kv(p, '${o['long'] ?? 0}', 'Long', p.profit), _kv(p, '${o['short'] ?? 0}', 'Short', p.loss)]),
    const SizedBox(height: 12),
    Text('Today signals (what the Brain decided today)', style: TextStyle(fontSize: 12, color: p.textMuted)),
    const SizedBox(height: 6),
    Row(children: [
      _kv(p, '${d['taken'] ?? 0}', 'Taken', p.profit),
      _kv(p, '${d['waited'] ?? 0}', 'Waited'),
      _kv(p, '${d['skipped'] ?? 0}', 'Skipped'),
      _kv(p, '${d['no_opinion'] ?? 0}', 'No opinion'),
    ]),
  ]);
}

Widget _riskDetail(AppPalette p, Map<String, dynamic> r) {
  final k = bdMap(r['risk']);
  final pct = bdNum(k['used_pct']);
  final hit = k['hit'] == true;
  final c = hit ? p.loss : pct >= 50 ? p.warning : p.profit;
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Text('Daily loss cap of the guard: ${bdNum(k['cap_pct']).toStringAsFixed(1)}% of ${bdNum(k['capital_usdt']).toStringAsFixed(0)} USDT', style: TextStyle(fontSize: 12, color: p.textMuted)),
    const SizedBox(height: 8),
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
    Text(hit ? 'The cap is HIT: no new trade until tomorrow.' : 'Only a net loss of today uses the cap. A profit day uses 0.', style: TextStyle(fontSize: 12, color: hit ? p.loss : p.textSecondary)),
    Text('Kill switch: ${k['kill_switch'] == true ? 'ON (everything stopped)' : 'off'}', style: TextStyle(fontSize: 12, color: k['kill_switch'] == true ? p.loss : p.textSecondary)),
  ]);
}

Widget _recentDetail(AppPalette p, List<Map<String, dynamic>> days) {
  if (days.isEmpty) return Text('No closed trade in the last days.', style: TextStyle(fontSize: 12, color: p.textMuted));
  return SizedBox(
    height: 84,
    child: ListView(scrollDirection: Axis.horizontal, children: [
      for (final d in days)
        Container(
          width: 80,
          margin: const EdgeInsets.only(right: 8),
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${d['day']}'.length >= 10 ? '${d['day']}'.substring(5) : '${d['day']}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            Text(bdSg(d['brain_usdt']), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: bdNet(p, d['brain_usdt']))),
            Text('Main ${bdSg(d['bot_usdt'])}', style: TextStyle(fontSize: 11, color: bdNet(p, d['bot_usdt']))),
          ]),
        ),
    ]),
  );
}

Widget _allTimeDetail(AppPalette p, Map<String, dynamic> r) {
  final a = bdMap(r['all_time']);
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _kv(p, bdSg(a['net_usdt']), 'Brain net, all time (USDT)', bdNet(p, a['net_usdt'])),
      _kv(p, '${a['closed'] ?? 0}', 'Closed trades, all time'),
    ]),
    const SizedBox(height: 10),
    Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textSecondary)),
  ]);
}

/// The detail folds (all closed, except Daily risk when it is a problem). Put the summary card above these.
List<Widget> brainDashboardCards(AppPalette p, Map<String, dynamic> r) {
  final t = bdMap(r['today']);
  final pc = bdMap(r['pace30']);
  final o = bdMap(r['open']);
  final d = bdMap(r['decisions']);
  final k = bdMap(r['risk']);
  final a = bdMap(r['all_time']);
  final days = bdList(r['recent']);
  final bad = k['hit'] == true || k['kill_switch'] == true;
  return [
    BrainWhyCard(source: '${r['source'] ?? 'PAPER'}'),
    const SizedBox(height: 8),
    _fold(p, 'Today detail', 'Gross ${bdSg(t['gross_usdt'])}, fees ${bdSg(t['fees_usdt'])}, net ${bdSg(t['net_usdt'])} USDT', _todayDetail(p, r)),
    _fold(p, 'Brain vs Main bot', '${pc['days'] ?? 0} days: Brain ${bdSg(pc['brain_usdt'])}, Main bot ${bdSg(pc['bot_usdt'])}', _paceDetail(p, r)),
    _fold(p, 'Open and signals', '${o['total'] ?? 0} open, ${d['taken'] ?? 0} taken today', _openDetail(p, r)),
    _fold(p, 'Daily risk limit', 'Used ${bdNum(k['used_pct']).toStringAsFixed(1)}% of the daily cap${bad ? ' (STOPPED)' : ''}', _riskDetail(p, r), edge: bad ? p.loss : null, open: bad),
    _fold(p, 'Recent days', days.isEmpty ? 'No closed trade in the last days' : 'Last ${days.length} days, oldest first', _recentDetail(p, days)),
    _fold(p, 'All time and note', 'Brain net ${bdSg(a['net_usdt'])} USDT, ${a['closed'] ?? 0} closed', _allTimeDetail(p, r)),
  ];
}
