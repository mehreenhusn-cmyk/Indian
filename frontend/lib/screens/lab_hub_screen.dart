import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/verdict_card.dart';
import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import '../widgets/load_state.dart';
import '../widgets/lazy_fold.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_route.dart';
import '../widgets/purpose_strip.dart';
import '../widgets/stat_tile.dart';
import '../widgets/verdict_badge.dart';
import '../widgets/verdict_carousel.dart';
import '../widgets/verdict_header_card.dart';
import 'brain_health_screen.dart';
import 'brain_learning_screen.dart';
import 'brain_ready_screen.dart';
import 'lab_hub_summary.dart';
import 'brain_studies_screen.dart';
import 'data_explorer_screen.dart';
import 'day_compare_screen.dart';
import 'exit_study_screen.dart';
import 'ledger_screen.dart';
import 'learning_progress_screen.dart';
import 'prepump_screen.dart';
import 'radar_screen.dart';
import 'results_screen.dart';
import 'scalp_lab_screen.dart';
import 'setup_screen.dart';
import 'study_verdicts.dart';
import 'tag_lab_screen.dart';
import 'wickstudy_screen.dart';

/// Round 8: STUDY LAB HUB (tab 4 of the plan). Answer first: the verdict carousel on top, then groups of studies.
/// Data = GET /api/v2/verdicts (read-only). Every study card opens its OLD screen unchanged; this file only adds the front door.
/// Needs-data cards are folded into ONE line (UI rule 4) and open into WHAT is missing / HOW MUCH / WHEN / WHAT TO DO.
/// Dart NOT compiled (the APK build is the proof).
class LabHubScreen extends StatefulWidget {
  const LabHubScreen({super.key});

  @override
  State<LabHubScreen> createState() => _LabHubScreenState();
}

/// One row of a group: [id] is the verdict-card id ('' = a study without a card), [owns] = that screen has its own Scaffold + app bar.
class _Item {
  final String id, title;
  final bool owns;
  final Widget Function() screen;
  const _Item(this.id, this.title, this.screen, {this.owns = false});
}

class _LabHubScreenState extends State<LabHubScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  bool _showNeed = false;

  // Where every study lives (README6 section 13, tab 4). zone / squeeze / limits share one screen with 3 tabs.
  static final Map<String, List<_Item>> _groups = {
    'IDEAS ON OLD CANDLES': [
      _Item('tag_lab', 'Tag Lab', () => const TagLabScreen(), owns: true),
      _Item('setup_finder', 'Setup Finder', () => const SetupScreen()),
      _Item('scalp_lab', 'Scalp Lab', () => const ScalpLabScreen()),
    ],
    'STOPS, WICKS, ZONES': [
      _Item('stopwick', 'Stop-wick study', () => const WickStudyScreen()),
      _Item('zone', 'Zone study', () => const BrainStudiesScreen(), owns: true),
      _Item('squeeze', 'Squeeze study', () => const BrainStudiesScreen(), owns: true),
      _Item('limits', 'Limits study', () => const BrainStudiesScreen(), owns: true),
    ],
    'WHAT THE BRAIN IS LEARNING': [
      _Item('playbook', 'Indicator Playbook', () => const BrainLearningScreen(), owns: true),
      _Item('exit_study', 'Exit Study', () => const ExitStudyScreen()),
      _Item('knowledge_ledger', 'Knowledge Ledger', () => const LedgerScreen()),
      _Item('', 'Data Explorer', () => const DataExplorerScreen()),
    ],
    'RESULTS AND WATCHLISTS': [
      _Item('results', 'Bot results', () => const ResultsScreen()),
      _Item('day_compare', 'Day Compare', () => const DayCompareScreen()),
      _Item('radar', 'Radar outcomes', () => const RadarScreen()),
      _Item('pump_dump', 'Pump / Dump study', () => const PrepumpScreen()),
    ],
    'BRAIN READINESS': [
      _Item('brain_health', 'Brain Health', () => const BrainHealthScreen()),
      _Item('brain_ready', 'Brain Ready check', () => const BrainReadyScreen()),
      _Item('learning_progress', 'Learning Progress', () => const LearningProgressScreen()),
    ],
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchVerdicts();
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  _Item? _itemOf(String id) {
    for (final g in _groups.values) {
      for (final i in g) {
        if (i.id == id) return i;
      }
    }
    return null;
  }

  /// A screen that owns its Scaffold is pushed as it is (no second header); every other screen gets one plain app bar.
  void _open(_Item it) {
    final p = context.palette;
    Navigator.of(context).push(OwlRoute(
      builder: (_) => it.owns
          ? it.screen()
          : Scaffold(
              backgroundColor: p.bg,
              appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text(it.title, style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
              body: it.screen(),
            ),
    ));
  }

  void _openCard(VerdictCard c) {
    final it = _itemOf(c.id);
    if (it != null) _open(it);
  }

  String _problem(Map<String, dynamic> r) {
    if (r['state'] == 'off') return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down.';
    if (r['state'] == 'old') return 'This backend has no verdict route yet. Install the newest backend zip, restart it, then pull down.';
    return 'Cannot reach the backend right now. Pull down to try again.';
  }

  Widget _label(String t) => Padding(
        padding: const EdgeInsets.only(left: 4, top: AppSpacing.l, bottom: AppSpacing.s),
        child: Text(t, style: context.type.label.copyWith(color: context.palette.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
      );

  Widget _row(_Item it, VerdictCard? c) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: OWLPressable(
        onTap: () => _open(it),
        pressedScale: 0.985,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
          child: Row(
            children: [
              Expanded(child: Text(it.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
              if (c != null) ...[const SizedBox(width: 8), VerdictBadge(verdict: c.verdict, compact: true)],
              const SizedBox(width: 4),
              Icon(Icons.chevron_right_rounded, size: 20, color: p.textMuted),
            ],
          ),
        ),
      ),
    );
  }

  List<Widget> _body(List<VerdictCard> cards) {
    final byId = {for (final c in cards) c.id: c};
    final decided = cards.where((c) => !c.needsData).toList();
    final need = cards.where((c) => c.needsData).toList();
    int count(String w) => cards.where((c) => VerdictStyle.clean(c.verdict) == w).length;
    final tested = count('NO_EDGE') + count('DIAGNOSIS_ONLY');
    final p = context.palette;
    return [
      labVerdictSummary(context, cards),
      const SizedBox(height: AppSpacing.cardGap),
      const PurposeStrip(
        why: 'Backtests printed raw tables with no answer.',
        what: 'One verdict per study. EDGE needs 100+ cases and the same sign in both halves.',
      ),
      const SizedBox(height: AppSpacing.cardGap),
      Row(children: [
        Expanded(child: StatTile(label: 'EDGE', value: '${count('EDGE')}', tone: count('EDGE') > 0 ? 'good' : '')),
        const SizedBox(width: 8),
        Expanded(child: StatTile(label: 'LOSING', value: '${count('LOSING')}', tone: count('LOSING') > 0 ? 'bad' : '')),
        const SizedBox(width: 8),
        Expanded(child: StatTile(label: 'TESTED', value: '$tested', sub: 'no proof')),
        const SizedBox(width: 8),
        Expanded(child: StatTile(label: 'NEED DATA', value: '${need.length}', tone: need.isNotEmpty ? 'warn' : '')),
      ]),
      const SizedBox(height: AppSpacing.cardGap),
      LazyFold(title: 'Old studies: does Sniper use them?', sub: 'One line per old backtest finding', builder: () => const StudyVerdicts()),
      _label('VERDICTS'),
      VerdictCarousel(cards: decided, onOpen: _openCard),
      if (need.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.cardGap),
        OWLPressable(
          onTap: () => setState(() => _showNeed = !_showNeed),
          pressedScale: 0.985,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(color: p.warning.withOpacity(0.10), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.warning.withOpacity(0.40))),
            child: Row(children: [
              Icon(Icons.hourglass_empty_rounded, size: 16, color: p.warning),
              const SizedBox(width: 8),
              Expanded(child: Text('${need.length} studies need more data: what is missing and what to do', style: context.type.secondary.copyWith(color: p.textPrimary))),
              Icon(_showNeed ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
            ]),
          ),
        ),
        if (_showNeed)
          for (final c in need) Padding(padding: const EdgeInsets.only(top: AppSpacing.cardGap), child: VerdictHeaderCard(card: c, onTap: _itemOf(c.id) == null ? null : () => _openCard(c))),
      ],
      for (final g in _groups.entries) ...[
        _label(g.key),
        for (final it in g.value) _row(it, byId[it.id]),
      ],
      if (_r?['made_utc'] != null) Padding(padding: const EdgeInsets.only(top: AppSpacing.l), child: Text('Made ${_r!['made_utc']} UTC. Read-only: a verdict is evidence, not an order.', style: context.type.metadata)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final bad = r == null || r['state'] != null || r['ready'] != true;
    Widget content;
    if (_busy && r == null) {
      content = LoadSpinner(onRetry: _load);
    } else if (bad) {
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
        children: _body(VerdictCard.listFrom(r?['cards'])),
      );
    }
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('Study Lab', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
      body: OWLRefresh(onRefresh: _load, child: content),
    );
  }
}
