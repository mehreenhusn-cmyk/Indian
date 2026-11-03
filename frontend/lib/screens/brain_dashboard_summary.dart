import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'brain_dashboard_cards.dart';

/// Part 19 (FILE 38): the ONE summary card on top of the Brain Dashboard. Read-only, real numbers from /api/v2/brain_dash only.
/// Big line = Brain net today. Under it ONE plain sentence + three small facts (30 days, open now, risk cap used).
/// The Brain and the Main bot are separate books: the Main bot number is shown on its own, never added. Dart NOT compiled.

/// One plain sentence about the state of the Brain right now (no invented numbers: only words around real counts).
String brainSummarySentence(Map<String, dynamic> r) {
  final k = bdMap(r['risk']);
  final t = bdMap(r['today']);
  final closed = (t['closed'] is num) ? (t['closed'] as num).toInt() : 0;
  if (k['kill_switch'] == true) return 'Kill switch is ON: everything is stopped.';
  if (k['hit'] == true) return 'Daily loss cap is HIT: no new Brain trade until tomorrow.';
  if (closed == 0) return 'No Brain trade closed today yet.';
  final n = bdNum(t['net_usdt']);
  if (n > 0) return 'Brain is in profit today ($closed closed trades).';
  if (n < 0) return 'Brain is in loss today ($closed closed trades).';
  return 'Brain is flat today ($closed closed trades).';
}

Widget _fact(AppPalette p, String big, String label, [Color? c]) => Expanded(
      child: Column(children: [
        Text(big, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
        const SizedBox(height: 2),
        Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );

Widget brainSummaryCard(AppPalette p, Map<String, dynamic> r) {
  final t = bdMap(r['today']);
  final pc = bdMap(r['pace30']);
  final o = bdMap(r['open']);
  final k = bdMap(r['risk']);
  final net = bdNum(t['net_usdt']);
  final bad = k['hit'] == true || k['kill_switch'] == true;
  return OWLCard(
    edge: bad ? p.loss : null,
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Brain today', style: TextStyle(fontSize: 13, color: p.textSecondary)),
      const SizedBox(height: 2),
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(bdSg(net), style: TextStyle(fontSize: 36, fontWeight: FontWeight.w800, color: bdNet(p, net))),
        const SizedBox(width: 6),
        Padding(padding: const EdgeInsets.only(bottom: 7), child: Text('USDT', style: TextStyle(fontSize: 13, color: p.textMuted))),
      ]),
      const SizedBox(height: 4),
      Text(brainSummarySentence(r), style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: bad ? p.loss : p.textPrimary)),
      const SizedBox(height: 12),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _fact(p, bdSg(pc['brain_usdt']), 'Brain ${pc['days'] ?? 0} days', bdNet(p, pc['brain_usdt'])),
        _fact(p, '${o['total'] ?? 0}', 'Open now'),
        _fact(p, '${bdNum(k['used_pct']).toStringAsFixed(0)}%', 'Risk cap used', bad ? p.loss : null),
      ]),
      const SizedBox(height: 8),
      Text('Main bot is a different book (today ${bdSg(t['bot_net_usdt'])}, ${pc['days'] ?? 0} days ${bdSg(pc['bot_usdt'])}). Never added. Details are below, tap to open.',
          style: TextStyle(fontSize: 10.5, color: p.textMuted)),
    ]),
  );
}
