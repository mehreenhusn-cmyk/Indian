import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_active.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/indicator_lab_cards.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_route.dart';
import '../widgets/purpose_strip.dart';
import '../widgets/report_download_card.dart';
import 'lab_test_detail_screen.dart';

/// R13: the STUDY LAB RESULTS BOARD. One card per test (all studies of the V2 Lab backend: indicators, Brain, exit, Dual split, skipped signals, wick, volatility, scalp, money lost), EDGE first.
/// Data = GET /api/v2/lab_results (read only). Summary strip on top (counts over ALL tests), then a verdict chip row and a study chip row. Tests that still need data are ONE folded line (chip NEED DATA).
/// Long lists show 25 cards and a "show more" button, so the phone never builds hundreds of cards. Read only: a verdict is evidence, not an order. Dart NOT compiled (the APK build is the proof).
class IndicatorLabScreen extends StatefulWidget {
  /// Part 13b: embedded = the board is the BODY of the Study Lab tab (no own Scaffold / app bar).
  final bool embedded;
  const IndicatorLabScreen({super.key, this.embedded = false});

  @override
  State<IndicatorLabScreen> createState() => _IndicatorLabScreenState();
}

class _IndicatorLabScreenState extends State<IndicatorLabScreen> {
  static const _page = 25;
  static const _verdicts = {'All tested': 'ALL', 'EDGE': 'EDGE', 'LOSING': 'LOSING', 'Candidate': 'DIAGNOSIS_ONLY', 'Need data': 'NOT_ENOUGH_DATA', 'No edge': 'NO_EDGE'};
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _verdict = 'ALL';
  String _family = 'ALL';
  int _shown = _page;
  final _lg = LastGood();

  @override
  void initState() {
    super.initState();
    _r = ScreenCache.get('lab_results'); // Part 14: the last good board at once, refresh quietly
    if (_r != null) {
      _lg.take(_r, false);
      _lg.at = ScreenCache.when('lab_results');
      _busy = false;
    }
    _load();
  }

  static bool _bad(Map<String, dynamic>? r) => r == null || r['state'] == 'error' || r['state'] == 'old' || r['results'] is! List;

  Future<void> _load() async {
    if (_r == null) setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchLabResults();
    if (!mounted) return;
    setState(() {
      _lg.take(r, _bad(r)); // a failed refresh keeps the last good board
      _r = _lg.data;
      _busy = false;
    });
    if (!_bad(r)) ScreenCache.put('lab_results', r);
  }

  String _problem(Map<String, dynamic> r) {
    if (r['enabled'] == false || r['state'] == 'off') return 'The V2 data API or the Sniper is switched off (file v2_api_enabled must exist, v2_sniper_off must not). Then pull down.';
    if (r['state'] == 'old') return 'This backend has no lab results route yet. Install the newest backend zip, restart it, then pull down.';
    return 'Cannot reach the backend right now. Pull down to try again.';
  }

  /// R14b: the full detail page of one test; the other tests of the same study (family) ride along for the "other tests" list.
  void _openDetail(LabTest t, List<LabTest> all) {
    Navigator.of(context).push(OwlRoute(builder: (_) => LabTestDetailScreen(test: t, siblings: [for (final s in all) if (s.family == t.family && s.id != t.id) s])));
  }

  void _pick({String? verdict, String? family}) => setState(() {
        _verdict = verdict ?? _verdict;
        _family = family ?? _family;
        _shown = _page;
      });

  List<Widget> _body(List<LabTest> all) {
    final p = context.palette;
    final by = <String, int>{};
    for (final t in all) {
      by[t.verdict] = (by[t.verdict] ?? 0) + 1;
    }
    final decided = all.where((t) => !t.needsData).toList();
    // the verdict chip decides the list; ALL = every test that has an answer (need-data tests are one chip, UI rule 4)
    final byV = _verdict == 'ALL' ? decided : all.where((t) => t.verdict == _verdict).toList();
    final fam = <String, int>{};
    for (final t in byV) {
      fam[t.family] = (fam[t.family] ?? 0) + 1;
    }
    final list = (_family == 'ALL' ? byV : byV.where((t) => t.family == _family).toList())
      ..sort((a, b) => LabTest.rank(a.verdict).compareTo(LabTest.rank(b.verdict)));
    final vCounts = <String, int>{'ALL': decided.length, for (final e in by.entries) e.key: e.value};
    final famOpts = <String, String>{'All studies': 'ALL', for (final k in kLabFamilies.keys) if (fam.containsKey(k)) labFamily(k): k};
    final summary = _r?['summary'];
    final line = summary is Map && summary['line'] != null ? '${summary['line']}' : '${all.length} tests';
    final shown = list.length < _shown ? list.length : _shown;
    return [
      UpdatedLine(lg: _lg, onRetry: _load, summary: line),
      LabSummaryStrip(byVerdict: by, onTap: (k) => _pick(verdict: k, family: 'ALL')), // Part 9: big tiles, tap = filter
      const SizedBox(height: AppSpacing.cardGap),
      const PurposeStrip(
        why: 'Every study printed its own table, so no one could compare them.',
        what: 'One row per test: EDGE, CANDIDATE (looked good, not proven), need data, no edge, losing. EDGE needs 30+ cases and the same sign in both halves.',
      ),
      const SizedBox(height: AppSpacing.cardGap),
      LabChipRow(options: _verdicts, counts: vCounts, selected: _verdict, onSelect: (k) => _pick(verdict: k, family: 'ALL')),
      const SizedBox(height: 6),
      LabChipRow(options: famOpts, counts: {'ALL': byV.length, ...fam}, selected: _family, onSelect: (k) => _pick(family: k)),
      const SizedBox(height: AppSpacing.cardGap),
      if (list.isEmpty)
        Container(
          padding: const EdgeInsets.all(AppSpacing.cardPad),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
          child: Text(all.isEmpty ? (_r?['note'] ?? 'No study result yet. The first run starts about 10 minutes after the backend starts.').toString() : 'No test matches this filter.', style: context.type.secondary),
        ),
      for (final t in list.take(shown)) LabTestCard(key: ValueKey(t.id), t: t, onOpen: () => _openDetail(t, all)),
      if (list.length > shown)
        OWLPressable(
          onTap: () => setState(() => _shown += _page),
          pressedScale: 0.985,
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 12),
            alignment: Alignment.center,
            decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
            child: Text('Show ${list.length - shown > _page ? _page : list.length - shown} more (${list.length - shown} hidden)', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
          ),
        ),
      Padding(padding: const EdgeInsets.only(top: AppSpacing.l), child: Text('Paper only. A verdict is evidence, not an order: no test here changes a trade.', style: context.type.metadata)),
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
        children: [
          ..._body(LabTest.listFrom(r['results'])),
          const SizedBox(height: AppSpacing.l),
          // Part 20: ONE text report of every test on this board (verdict, n, win %, R each, lift, halves). Share or Copy it to any AI.
          const ReportDownloadCard(
            title: 'Study Lab results report',
            description: 'One text file with every test on this board: what was tested, EDGE / candidate / need data / no edge / losing, with the numbers. Use Share or Copy and send it to any AI.',
            textPath: '/api/v2/lab_report',
            savePath: '/api/v2/lab_report_save',
            fileName: 'owl_study_results_report.txt',
          ),
        ],
      );
    }
    if (widget.embedded) return OWLRefresh(onRefresh: _load, child: content);
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('Study results', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
      body: OWLRefresh(onRefresh: _load, child: content),
    );
  }
}
