import 'package:flutter/material.dart';

import 'sniper_learn_cards.dart';

/// R32b (Part 7): the A/B TEST card of the Sniper tab. It reads the "ab" block of GET /api/v2/sniper_exitlearn (same answer as the booking card, no new fetch).
/// The Sniper learns by trading: half of its paper trades keep the plain lines (A = control), half use one exit rule (B = break-even, trail or time exit). Numbers are R per closed trade, paper only.
/// The file v2_ab_off in the data folder switches new B trades off. Dart NOT compiled (the APK build is the proof).
class SniperAbCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperAbCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'A/B EXIT TEST', headline: bad);
    final t = lcMap(r!['ab']);
    if (t.isEmpty) return const LearnCard(title: 'A/B EXIT TEST', headline: 'This backend does not have the A/B test yet. Install the newest backend and restart it.');
    final v = '${t['verdict'] ?? ''}';
    final arms = lcMap(t['arms']);
    final a = lcMap(arms['A']);
    final b = lcMap(arms['B']);
    final rules = lcMap(t['rules']);
    String arm(String n, Map<String, dynamic> m) {
      final x = lcD(m['mean_r']);
      return '$n: ${lcI(m['n']) ?? 0} trades${x == null ? '' : ', ${lcSg(x, 2)} R each'}${lcD(m['win_pct']) == null ? '' : ', ${lcD(m['win_pct'])!.toStringAsFixed(0)}% won'}';
    }

    return LearnCard(
      title: 'A/B EXIT TEST',
      word: t['switch_off'] == true ? 'OFF' : (v == 'B_BETTER' ? 'B WINS' : (v == 'A_BETTER' ? 'A WINS' : (v == 'NOT_CLEAR' ? 'NOT CLEAR' : 'COLLECTING'))),
      tone: v == 'B_BETTER' ? 'good' : 'wait',
      headline: '${t['text'] ?? ''}',
      lines: [
        arm('A (plain 1R / 2R lines)', a),
        arm('B (exit rules)', b),
        for (final e in rules.entries.take(5)) arm('  ${e.key}', lcMap(e.value)),
      ],
      note: 'Paper only. Needs 20 closed trades in each arm before a winner is named. Break-even, trail and time exits are tested here, never on real orders.',
    );
  }
}
