import 'package:flutter/material.dart';

import 'sniper_learn_cards.dart';

/// R32a (Part 6): the TP/SL COMBO card of the Sniper tab. It reads the "tpsl" block of GET /api/v2/sniper_exitlearn (the same answer the booking card uses, so no new fetch).
/// Question it answers: which STOP line + PROFIT line together (in R of the trade's own stop) kept more money on UNSEEN days than the fixed 1R stop / 2R profit, per market state.
/// Numbers are R per trade after fees. Paper LEARN lane only; real orders never use it. The file v2_tpsl_off in the data folder switches it off. Dart NOT compiled (the APK build is the proof).
String _combo(String n) {
  final m = RegExp(r'^tp([\d.]+)_sl([\d.]+)$').firstMatch(n);
  return m == null ? n : 'profit ${m.group(1)}R, stop ${m.group(2)}R';
}

class SniperTpslCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperTpslCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'STOP + PROFIT LINES', headline: bad);
    final t = lcMap(r!['tpsl']);
    if (t.isEmpty) return const LearnCard(title: 'STOP + PROFIT LINES', headline: 'This backend does not have the combo learner yet. Install the newest backend and restart it.');
    final st = '${t['state'] ?? ''}';
    final cmp = lcMap(t['compare']);
    final base = lcD(cmp['default_mean_r']);
    final got = lcD(cmp['choice_mean_r']);
    final n = lcI(cmp['test_trades']);
    final rules = lcMap(t['rules']);
    final reasons = t['reasons'] is List ? [for (final x in t['reasons'] as List) '$x'] : <String>[];
    final off = t['switch_off'] == true;
    final changed = [for (final e in rules.entries) if ('${e.value}' != '${t['default']}') '${e.key}: ${_combo('${e.value}')}'];
    return LearnCard(
      title: 'STOP + PROFIT LINES',
      word: off ? 'OFF' : (st == 'LEARNED_TPSL' ? 'LEARNED' : (st == 'EXPLORE_TPSL' ? 'EXPLORING' : 'NOT YET')),
      tone: !off && st == 'LEARNED_TPSL' ? 'good' : 'wait',
      headline: base == null || got == null
          ? (reasons.isNotEmpty ? reasons.first : 'No unseen-days test yet.')
          : 'Unseen days: learned lines ${lcSg(got)} R vs fixed 1R / 2R ${lcSg(base)} R each${n == null ? '' : ' ($n trades)'}',
      lines: [
        if (changed.isEmpty && base != null) 'No market state has a steady better pair yet: the fixed 1R stop / 2R profit stays.',
        for (final c in changed.take(3)) c,
        if (reasons.length > 0 && base != null) reasons.first,
      ],
      note: off ? 'Switched off (file v2_tpsl_off). The paper LEARN lane keeps the default lines.' : 'Paper only. A pair must win in both halves of the older days AND on unseen days before the paper LEARN lane uses it.',
    );
  }
}
