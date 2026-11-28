import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/indicator_lab_cards.dart';
import '../widgets/owl_route.dart';
import 'lab_test_detail_screen.dart';

/// R15: the DECISION MAP logic + the page of ONE map cell.
/// Map = 4 indicators (SD bands, Z-SMA, EMA cloud, TSI) x 3 market states (Trending, Sideways, High vol). Every cell is built from the tests the Study Lab
/// already has (GET /api/v2/lab_results, R9 to R12). Nothing new is measured here: a cell only GROUPS existing tests, so every verdict keeps its own unseen-days proof.
/// A test lands in a cell by its words (family, title, context, id). A pair / combo counts under every indicator it contains. A test with no market state in its words is not on the map.
/// Read only: a verdict is evidence, never an order. Dart NOT compiled (the APK build is the proof).
const List<String> kPlayIndicators = ['SD bands', 'Z-SMA', 'EMA cloud', 'TSI'];
const List<String> kPlayStates = ['Trending', 'Sideways', 'High vol'];

final RegExp _reSd = RegExp(r'sd[ _-]?band|(^|[^a-z])sd([^a-z]|$)');
final RegExp _reZ = RegExp(r'z[ _-]?sma|zsma|z[ _-]?score|(^|[^a-z])z([^a-z]|$)');
final RegExp _reEma = RegExp(r'(^|[^a-z])(ema|cloud)');
final RegExp _reTsi = RegExp(r'tsi');
final RegExp _reSide = RegExp(r'sideways|range|chop|flat|consolidat');
final RegExp _reTrend = RegExp(r'trend');
final RegExp _reHigh = RegExp(r'(^|[^a-z])(high|extreme)([^a-z]|$)');

String _text(LabTest t) => '${t.id} ${t.title} ${t.context}'.toLowerCase();

/// Which indicators a test is about (the study families say it directly; pairs and combos are read by their words).
List<String> playIndicators(LabTest t) {
  final x = _text(t);
  switch (t.family) {
    case 'sd_bands':
    case 'regime':
      return const ['SD bands'];
    case 'zsma':
      return const ['Z-SMA'];
    case 'pairs':
    case 'combos':
      return [
        if (_reSd.hasMatch(x)) 'SD bands',
        if (_reZ.hasMatch(x)) 'Z-SMA',
        if (_reEma.hasMatch(x)) 'EMA cloud',
        if (_reTsi.hasMatch(x)) 'TSI',
      ];
  }
  return const <String>[];
}

/// Which market states a test names (empty = the test does not say, so it is not on the map).
List<String> playStates(LabTest t) {
  final x = _text(t);
  return [
    if (_reTrend.hasMatch(x)) 'Trending',
    if (_reSide.hasMatch(x)) 'Sideways',
    if (_reHigh.hasMatch(x)) 'High vol',
  ];
}

/// One cell of the map: the tests of one indicator in one market state.
class PlayCell {
  final String indicator, state;
  final List<LabTest> tests;
  const PlayCell(this.indicator, this.state, this.tests);

  List<LabTest> get decided => [for (final t in tests) if (!t.needsData) t];

  /// The strongest word of the cell: EDGE, then LOSING, DIAGNOSIS_ONLY, NO_EDGE. Only when every test still waits for data: NOT_ENOUGH_DATA. No test at all: null.
  String? get verdict {
    if (tests.isEmpty) return null;
    final d = decided;
    if (d.isEmpty) return 'NOT_ENOUGH_DATA';
    final v = [for (final t in d) t.verdict]..sort((a, b) => LabTest.rank(a).compareTo(LabTest.rank(b)));
    return v.first;
  }

  /// The test that gave the cell its word (same word: the one with more cases).
  LabTest? get best {
    final d = decided;
    if (d.isEmpty) return null;
    final s = [...d]..sort((a, b) {
        final c = LabTest.rank(a.verdict).compareTo(LabTest.rank(b.verdict));
        return c != 0 ? c : b.n.compareTo(a.n);
      });
    return s.first;
  }
}

/// All 12 cells, keyed "indicator|state" (a cell with no test is still there, with an empty list).
Map<String, PlayCell> playGrid(List<LabTest> all) {
  final m = <String, List<LabTest>>{};
  for (final t in all) {
    final st = playStates(t);
    if (st.isEmpty) continue;
    for (final i in playIndicators(t)) {
      for (final s in st) {
        (m['$i|$s'] ??= <LabTest>[]).add(t);
      }
    }
  }
  return {
    for (final i in kPlayIndicators)
      for (final s in kPlayStates) '$i|$s': PlayCell(i, s, m['$i|$s'] ?? <LabTest>[]),
  };
}

/// How many indicator tests say no market state (shown as one honest line under the map).
int playUnmapped(List<LabTest> all) => all.where((t) => t.family != 'regime' && playIndicators(t).isNotEmpty && playStates(t).isEmpty).length;

/// The page of one cell: its tests, EDGE first. A card opens the full detail page of R14b.
class LabDecisionMapScreen extends StatelessWidget {
  final PlayCell cell;
  const LabDecisionMapScreen({super.key, required this.cell});

  void _open(BuildContext context, LabTest t, List<LabTest> list) {
    Navigator.of(context).push(OwlRoute(builder: (_) => LabTestDetailScreen(test: t, siblings: [for (final s in list) if (s.id != t.id) s])));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final list = [...cell.tests]..sort((a, b) => LabTest.rank(a.verdict).compareTo(LabTest.rank(b.verdict)));
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('${cell.indicator} · ${cell.state}', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
      body: ListView(
        physics: const BouncingScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.screenPad, AppSpacing.s, AppSpacing.screenPad, AppSpacing.huge),
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
            child: Text('${list.length} tests in this cell. The cell word is the strongest one. Tap a card, then Open full detail.', style: context.type.metadata),
          ),
          for (final t in list) LabTestCard(key: ValueKey(t.id), t: t, onOpen: () => _open(context, t, list)),
          Padding(padding: const EdgeInsets.only(top: AppSpacing.l), child: Text('Paper only. A verdict is evidence, not an order: no test here changes a trade.', style: context.type.metadata)),
        ],
      ),
    );
  }
}
