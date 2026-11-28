import 'package:flutter/material.dart';
import '../models/verdict_card.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';

/// Part 22 (FILE 42): the ONE answer line on top of the Study Lab. Read-only, built only from the verdict cards the backend sent.
/// Order of the answer: which studies have an EDGE (names), which are LOSING (names), then plain counts of NO EDGE / DIAGNOSIS / NOT ENOUGH DATA.
/// No EDGE at all = it says so in plain words. Nothing is invented: counts and titles come from the cards. Dart NOT compiled.

List<String> _titles(List<VerdictCard> cards, String word) => [for (final c in cards) if (VerdictStyle.clean(c.verdict) == word) c.title.isEmpty ? c.id : c.title];

String _join(List<String> t) => t.length <= 3 ? t.join(', ') : '${t.take(3).join(', ')} +${t.length - 3} more';

/// The sentence on top (also used by the colour: EDGE green, LOSING only red, else amber / grey).
String labSummaryLine(List<VerdictCard> cards) {
  if (cards.isEmpty) return 'No study verdict yet.';
  final edge = _titles(cards, 'EDGE');
  final lose = _titles(cards, 'LOSING');
  final parts = <String>[];
  parts.add(edge.isEmpty ? 'No study has a proven EDGE yet.' : 'EDGE found in: ${_join(edge)}.');
  if (lose.isNotEmpty) parts.add('LOSING: ${_join(lose)}.');
  return parts.join(' ');
}

Widget labVerdictSummary(BuildContext context, List<VerdictCard> cards) {
  final p = context.palette;
  int n(String w) => _titles(cards, w).length;
  final edge = n('EDGE');
  final lose = n('LOSING');
  final c = edge > 0 ? p.profit : lose > 0 ? p.loss : p.warning;
  Widget chip(String label, int v, Color col) => Container(
        margin: const EdgeInsets.only(right: 6, top: 6),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: col.withOpacity(0.14), borderRadius: BorderRadius.circular(8), border: Border.all(color: col.withOpacity(0.5))),
        child: Text('$label $v', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: col)),
      );
  return Container(
    width: double.infinity,
    padding: const EdgeInsets.all(AppSpacing.cardPad),
    decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: c.withOpacity(0.6))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Study Lab answer', style: TextStyle(fontSize: 12, color: p.textSecondary)),
      const SizedBox(height: 4),
      Text(labSummaryLine(cards), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
      const SizedBox(height: 4),
      Text('In plain words: ${cards.length} tests ran on past trades. ${edge == 0 ? 'None' : '$edge'} showed a real profit that also held on days it had not seen. $lose lose money after fees. ${n('NO_EDGE')} show no profit either way, ${n('NOT_ENOUGH_DATA')} have too few trades to say. Nothing here places a trade.', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
      Wrap(children: [
        chip('PROVEN PROFIT', edge, p.profit),
        chip('LOSES MONEY', lose, p.loss),
        chip('NO PROOF', n('NO_EDGE'), p.textSecondary),
        chip('INFO ONLY', n('DIAGNOSIS_ONLY'), p.accent),
        chip('TOO EARLY', n('NOT_ENOUGH_DATA'), p.warning),
      ]),
      const SizedBox(height: 6),
      Text('A result is evidence, not an order. PROVEN PROFIT (EDGE) needs 100+ trades and the same result in both halves of the data.', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
    ]),
  );
}
