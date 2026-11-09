import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_route.dart';
import '../widgets/owl_text_tabs.dart';
import 'filter_lab_screen.dart';
import 'indicator_lab_screen.dart';
import 'lab_hub_screen.dart';

/// Part 13b (owner: "gather all the backtests, show the result in ONE place"): the Study Lab tab IS the Results Board now.
/// One flat list of every test (indicators Z-SMA / SD bands / pairs / combos, Brain, exit, Dual split, skipped signals, wick, volatility, scalp, money lost),
/// sorted EDGE, CANDIDATE, need data, no edge, losing; filters by verdict and by study; tap a row = the reasons, tap again = full detail.
/// Nothing was deleted: the old study screens (verdict cards per study, playbook, decision map, old studies) are one tap away under "Studies and tools" in the top bar.
/// Part 8A-2 (README_FILTER): two tabs under the title: "Results" (the board above, unchanged) and "Filter Lab" (fake-signal study + Part 7 gate, filter_lab_screen.dart).
/// Only the tab that is showing is built, so the Filter Lab polls the backend only while it is open.
/// Read only: a verdict is evidence, not an order. Dart NOT compiled.
class StudyLabScreen extends StatefulWidget {
  const StudyLabScreen({super.key});

  @override
  State<StudyLabScreen> createState() => _StudyLabScreenState();
}

class _StudyLabScreenState extends State<StudyLabScreen> {
  int _tab = 0;

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
      body: Column(children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
          child: OwlTextTabs(names: const ['Results', 'Filter Lab'], index: _tab, onChanged: (i) => setState(() => _tab = i)),
        ),
        // P-F: pinned line that names the source of every row below (the board is read only).
        if (_tab == 0) const OwlSummaryLine(source: 'Results board', note: 'Read only. A verdict is evidence, not an order.'),
        Expanded(child: _tab == 0 ? const IndicatorLabScreen(embedded: true) : const FilterLabScreen()),
      ]),
    );
  }
}
