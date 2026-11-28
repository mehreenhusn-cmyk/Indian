import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import '../widgets/indicator_lab_cards.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_route.dart';
import '../widgets/purpose_strip.dart';
import 'lab_decision_map_screen.dart';

/// R15: the INDICATOR PLAYBOOK. One map: SD bands, Z-SMA, EMA cloud, TSI x Trending, Sideways, High vol. Each cell = one verdict word (tap = its tests).
/// Under the map: "what the data says" in plain lines, and the best SD-band lookback per volatility regime.
/// Data = GET /api/v2/lab_results (the board's data, read only) + GET /api/v2/sniper_modes (only for the confirmed lookback; if it fails the page still works).
/// Nothing new is measured here: the map only groups tests that already have their own unseen-days proof (see lab_decision_map_screen.dart). Advice only, paper only.
/// Dart NOT compiled (the APK build is the proof).
class LabPlaybookScreen extends StatefulWidget {
  const LabPlaybookScreen({super.key});

  @override
  State<LabPlaybookScreen> createState() => _LabPlaybookScreenState();
}

class _LabPlaybookScreenState extends State<LabPlaybookScreen> {
  static const _short = {'EDGE': 'EDGE', 'LOSING': 'LOSING', 'DIAGNOSIS_ONLY': 'MAYBE', 'NO_EDGE': 'NO EDGE', 'NOT_ENOUGH_DATA': 'WAIT'};
  static const _regimes = ['LOW', 'MEDIUM', 'HIGH', 'EXTREME'];
  static const _labelW = 74.0;
  Map<String, dynamic>? _r;
  Map<String, dynamic>? _modes;
  bool _busy = true;
  final _lg = LastGood();

  @override
  void initState() {
    super.initState();
    _load();
  }

  static bool _bad(Map<String, dynamic>? r) => r == null || r['state'] == 'error' || r['state'] == 'old' || r['results'] is! List;

  Future<void> _load() async {
    setState(() => _busy = true);
    final pr = context.read<AppProvider>();
    final res = await Future.wait<Map<String, dynamic>>([pr.fetchLabResults(), pr.fetchSniperModes()]);
    if (!mounted) return;
    setState(() {
      _lg.take(res[0], _bad(res[0]));
      _r = _lg.data;
      _modes = res[1];
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['enabled'] == false || r['state'] == 'off') return 'The V2 data API or the Sniper is switched off (file v2_api_enabled must exist, v2_sniper_off must not). Then pull down.';
    if (r['state'] == 'old') return 'This backend has no lab results route yet. Install the newest backend zip, restart it, then pull down.';
    return 'Cannot reach the backend right now. Pull down to try again.';
  }

  Widget _card(Widget child) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: child,
    );
  }

  Widget _cell(PlayCell c) {
    final p = context.palette;
    final v = c.verdict;
    final col = v == null ? p.textMuted : VerdictStyle.of(p, v).color;
    final box = Container(
      margin: const EdgeInsets.all(2),
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: col.withOpacity(v == null ? 0.04 : 0.14),
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
        border: Border.all(color: col.withOpacity(0.4), width: 0.8),
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Text(v == null ? '-' : (_short[v] ?? ''), style: context.type.label.copyWith(color: col, fontWeight: FontWeight.w800, fontSize: 11)),
        Text(v == null ? 'no test' : '${c.tests.length} tests', style: context.type.metadata),
      ]),
    );
    if (v == null) return box;
    return OWLPressable(
      onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => LabDecisionMapScreen(cell: c))),
      pressedScale: 0.96,
      child: box,
    );
  }

  Widget _map(Map<String, PlayCell> grid) {
    final p = context.palette;
    return _card(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        const SizedBox(width: _labelW),
        for (final s in kPlayStates) Expanded(child: Center(child: Text(s, style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: p.textSecondary)))),
      ]),
      const SizedBox(height: 4),
      for (final i in kPlayIndicators)
        Row(children: [
          SizedBox(width: _labelW, child: Text(i, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700, color: p.textPrimary))),
          for (final s in kPlayStates) Expanded(child: _cell(grid['$i|$s']!)),
        ]),
      const SizedBox(height: 6),
      Text('EDGE = proven on unseen days. MAYBE = looked good, not proven. WAIT = not enough cases yet. Tap a cell to see its tests.', style: context.type.metadata),
    ]));
  }

  /// "What the data says": one group per word (max 4 lines each), the line = the cell name + the headline of the test that gave the word.
  Widget _says(Map<String, PlayCell> grid) {
    final p = context.palette;
    final groups = <String, List<String>>{'EDGE': [], 'LOSING': [], 'DIAGNOSIS_ONLY': []};
    for (final c in grid.values) {
      final v = c.verdict;
      final b = c.best;
      if (v == null || b == null || !groups.containsKey(v)) continue;
      groups[v]!.add('${c.indicator} in ${c.state}: ${b.headline.isNotEmpty ? b.headline : b.title}');
    }
    final names = {'EDGE': 'Pays', 'LOSING': 'Loses money', 'DIAGNOSIS_ONLY': 'Not proven'};
    final rows = <Widget>[];
    for (final e in groups.entries) {
      if (e.value.isEmpty) continue;
      final col = VerdictStyle.of(p, e.key).color;
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(names[e.key]!, style: context.type.metadata.copyWith(color: col, fontWeight: FontWeight.w800)),
          for (final line in e.value.take(4)) Padding(padding: const EdgeInsets.only(top: 2), child: Text(line, style: context.type.secondary.copyWith(color: p.textPrimary))),
          if (e.value.length > 4) Text('+${e.value.length - 4} more: tap the cells above', style: context.type.metadata),
        ]),
      ));
    }
    return _card(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('What the data says', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
      if (rows.isEmpty)
        Padding(padding: const EdgeInsets.only(top: 6), child: Text('Nothing is proven and nothing is losing yet. The tests still wait for more cases. The map fills by itself.', style: context.type.secondary))
      else
        ...rows,
    ]));
  }

  /// Best SD-band lookback per volatility regime: every tested lookback with its word, then the confirmed one from the weekly tuning (needs 2 runs that agree).
  Widget _lookback(List<LabTest> all) {
    final p = context.palette;
    final lb = _modes?['lookback'];
    final use = lb is Map && lb['use'] is Map ? lb['use'] as Map : const {};
    final def = lb is Map && lb['default'] != null ? '${lb['default']}' : '';
    final by = <String, List<LabTest>>{};
    for (final t in all) {
      if (t.family == 'regime') (by[t.context.toUpperCase()] ??= <LabTest>[]).add(t);
    }
    final keys = [..._regimes.where(by.containsKey), ...by.keys.where((k) => !_regimes.contains(k))];
    final lookRe = RegExp(r'lookback (\d+)');
    final rows = <Widget>[];
    for (final k in keys) {
      final tests = [...by[k]!]..sort((a, b) => LabTest.rank(a.verdict).compareTo(LabTest.rank(b.verdict)));
      final conf = use[k];
      rows.add(Padding(
        padding: const EdgeInsets.only(top: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(k, style: context.type.secondary.copyWith(fontWeight: FontWeight.w800, color: p.textPrimary)),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (final t in tests)
              Builder(builder: (_) {
                final col = VerdictStyle.of(p, t.verdict).color;
                final m = lookRe.firstMatch(t.title.toLowerCase());
                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(color: col.withOpacity(0.12), borderRadius: BorderRadius.circular(AppSpacing.radiusPill)),
                  child: Text('${m == null ? t.title : m.group(1)}: ${_short[t.verdict] ?? ''}', style: context.type.metadata.copyWith(color: col, fontWeight: FontWeight.w700)),
                );
              }),
          ]),
          Text(conf != null ? 'Confirmed lookback: $conf' : 'No lookback confirmed yet (needs 2 weekly runs that agree)', style: context.type.metadata),
        ]),
      ));
    }
    return _card(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Best lookback per volatility', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
      Text(def.isEmpty ? 'SD band lookback tested per volatility regime.' : 'Default lookback: $def. Each chip = a tested lookback and its word.', style: context.type.metadata),
      if (rows.isEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('No volatility test yet.', style: context.type.secondary)) else ...rows,
    ]));
  }

  List<Widget> _body(List<LabTest> all) {
    final grid = playGrid(all);
    final onMap = grid.values.where((c) => c.tests.isNotEmpty).length;
    final unmapped = playUnmapped(all);
    return [
      UpdatedLine(lg: _lg, onRetry: _load, summary: '$onMap of ${grid.length} cells have tests'),
      const SizedBox(height: AppSpacing.cardGap),
      const PurposeStrip(
        why: 'One test at a time does not show which indicator to use in which market.',
        what: 'Four indicators in three market states, one word each. Built from the Study results, nothing new measured.',
      ),
      const SizedBox(height: AppSpacing.cardGap),
      _map(grid),
      _says(grid),
      _lookback(all),
      Text(
        'A pair or combo counts under every indicator it has. ${unmapped == 0 ? '' : '$unmapped indicator tests name no market state, so they are not on the map (see Study results). '}Paper only: a word here is evidence, not an order.',
        style: context.type.metadata,
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    Widget content;
    if (_busy && r == null) {
      content = LoadSpinner(onRetry: _load);
    } else if (_bad(r) || r == null) {
      content = ListView(padding: const EdgeInsets.all(AppSpacing.screenPad), children: [
        Container(
          padding: const EdgeInsets.all(AppSpacing.cardPad),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.warning.withOpacity(0.5))),
          child: Text(_problem(r ?? <String, dynamic>{'state': 'error'}), style: context.type.secondary.copyWith(color: p.textPrimary)),
        ),
      ]);
    } else {
      content = ListView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        padding: const EdgeInsets.fromLTRB(AppSpacing.screenPad, AppSpacing.s, AppSpacing.screenPad, AppSpacing.huge),
        children: _body(LabTest.listFrom(r['results'])),
      );
    }
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('Indicator playbook', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
      body: OWLRefresh(onRefresh: _load, child: content),
    );
  }
}
