import 'package:flutter/material.dart';
import '../widgets/lazy_fold.dart';
import 'capital_card.dart';
import 'sniper_selflog.dart';

/// Part 46 (FILE 55): the finished Sniper cards of Parts 12, 35 and 44 on the Sniper tab, as CLOSED folds: Small account, Self log (R17: the Risk Box moved to sniper_riskbox_fold.dart, above the fold).
/// Nothing is requested until a fold is opened (LazyFold). The Risk Box uses the first order card of the newest scan: a card that PASSES uses its own side, any other card asks the Sniper's own signal (side empty).
/// No card = a plain line, no request. Read only, paper only. Use: SniperExtras(r: r) with r = the live scan answer. Dart NOT compiled (the APK build is the proof).
class SniperExtras extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperExtras({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      LazyFold(title: 'Small account', sub: '10 USDT paper replay, one book at a time', builder: () => const CapitalCard(capital: 10)),
      const SizedBox(height: 8),
      LazyFold(title: 'Self log', sub: 'What Sniper learned, its mistakes, what changed', builder: () => const SniperSelfLog()),
    ]);
  }
}
