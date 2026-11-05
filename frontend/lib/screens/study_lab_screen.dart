import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_route.dart';
import 'indicator_lab_screen.dart';
import 'lab_hub_screen.dart';

/// Part 13b (owner: "gather all the backtests, show the result in ONE place"): the Study Lab tab IS the Results Board now.
/// One flat list of every test (indicators Z-SMA / SD bands / pairs / combos, Brain, exit, Dual split, skipped signals, wick, volatility, scalp, money lost),
/// sorted EDGE, CANDIDATE, need data, no edge, losing; filters by verdict and by study; tap a row = the reasons, tap again = full detail.
/// Nothing was deleted: the old study screens (verdict cards per study, playbook, decision map, old studies) are one tap away under "Studies and tools" in the top bar.
/// Read only: a verdict is evidence, not an order. Dart NOT compiled.
class StudyLabScreen extends StatelessWidget {
  const StudyLabScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        toolbarHeight: 48, // P-F: a lower title bar, more room for the list
        title: Text('Study Lab', style: context.type.section.copyWith(fontSize: 20, fontWeight: FontWeight.w700)),
        actions: [
          OWLPressable(
            pressedScale: 0.97,
            onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => const LabHubScreen())),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              child: Center(child: Text('Studies and tools', style: context.type.primary.copyWith(color: p.accent, fontWeight: FontWeight.w700))),
            ),
          ),
        ],
      ),
      // P-F: pinned line that names the source of every row below (the board is read only).
      body: const Column(children: [
        OwlSummaryLine(source: 'Results board', note: 'Read only. A verdict is evidence, not an order.'),
        Expanded(child: IndicatorLabScreen(embedded: true)),
      ]),
    );
  }
}
