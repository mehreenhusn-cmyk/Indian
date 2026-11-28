import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import 'filter_part_loader.dart';

/// Part 8B-2a (README_FILTER): the FILTERS tab = the saved summary of Part 4 (filter lab). Read only. Every filter is tested ALONE as "BLOCK a trade when ...".
/// Trades are split by TIME: the first 60% = TRAIN (cut-offs are picked here), the last 40% = TEST (only judges). Switches: Main / Sniper (never added together) and all timeframes / 5m only.
/// Blocks: baseline, verdict counts, PASS (candidates for the gate), HELPS BUT LOSES MOVES, FAILED ON TEST (looked good on TRAIN only), the best cut-off per number, the STACK of filters, and PROTECT (buckets that earn the most: never block).
/// NET GAIN = money saved by blocking. MOVES LOST = 3%+ rallies / dumps that a trade caught before but no trade catches after. LUCK % = how often a random block of the same size saves as much on TEST (low = good).
/// A PASS is a CANDIDATE, not a rule: the gate (Part 7) builds its rules from these by itself. Dart NOT compiled (the APK build is the proof).
class FilterFiltersTab extends StatefulWidget {
  const FilterFiltersTab({super.key});

  @override
  State<FilterFiltersTab> createState() => _FilterFiltersTabState();
}

class _FilterFiltersTabState extends State<FilterFiltersTab> {
  String _g = 'MAIN';
  String _scope = 'all';

  @override
  Widget build(BuildContext context) {
    return FilterPartView(ids: const ['f4'], builder: (c, data, missing) => _body(c, flM(data['f4'])));
  }

  Widget _body(BuildContext context, Map<String, dynamic> d) {
    final p = context.palette;
    final sc = flM(flM(d[_g])[_scope]);
    final movesOn = flS(d['moves_check']) == 'ON';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OwlSegmented(items: const [('MAIN', 'Main'), ('SNIPER', 'Sniper')], active: _g, onPick: (k) => setState(() => _g = k)),
      OwlSegmented(items: const [('all', 'All timeframes'), ('5m', '5m only')], active: _scope, onPick: (k) => setState(() => _scope = k)),
      if (flS(d['split']).isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.s), child: Text('${flS(d['split'])}. Cut-offs are picked on TRAIN only.', style: context.type.caption)),
      if (!movesOn && flS(d['moves_check']).isNotEmpty) flNote(context, flS(d['moves_check']), bad: true),
      if (sc.isEmpty || flThin(sc))
        flNote(context, sc.isEmpty ? 'No numbers for this scope.' : 'NOT ENOUGH DATA: ${flN(sc['trades']).toInt()} trades, the lab needs ${flN(sc['need']).toInt()}+ in a scope.')
      else ...[
        const OwlSectionLabel('Baseline'),
        _baseline(context, sc),
        OwlSectionLabel('Filters tried', note: '${flN(sc['filters_tried']).toInt()}'),
        _verdicts(context, flM(sc['verdict_counts'])),
        const OwlSectionLabel('PASS = candidates', note: 'gain in both halves, no big move lost'),
        if (flMl(sc['PASS']).isEmpty) flNote(context, 'No filter passed. That is a normal answer: then the gate has nothing to use.') else OwlListCard(children: [for (final j in flMl(sc['PASS'])) _row(context, j)]),
        if (flMl(sc['HELPS_BUT_LOSES_MOVES']).isNotEmpty) flFold(context, 'HELPS BUT LOSES MOVES', 'saves money, but cuts real rallies / dumps', [for (final j in flMl(sc['HELPS_BUT_LOSES_MOVES'])) _row(context, j)]),
        if (flMl(sc['FAILS_TEST_examples']).isNotEmpty) flFold(context, 'FAILED ON TEST', 'looked good on TRAIN only (this is what luck looks like)', [for (final j in flMl(sc['FAILS_TEST_examples'])) _row(context, j, verdict: true)]),
        ..._cutoffs(context, flMl(sc['cutoffs_per_number'])),
        ..._stack(context, flM(sc['stack'])),
        ..._protect(context, flMl(sc['PROTECT_never_block'])),
        const SizedBox(height: AppSpacing.s),
        Text('Hindsight numbers: a live filter sees each signal once. About ${flN(sc['filters_tried']).toInt()} filters are tried, so a few look good by luck: trust LUCK % and both halves, not one big number.', style: context.type.caption.copyWith(color: p.textMuted)),
      ],
    ]);
  }

  // ---------------------------------------------------------------- baseline
  Widget _baseline(BuildContext context, Map<String, dynamic> sc) {
    final b = flM(sc['baseline']), bm = flM(sc['baseline_moves_3pct_plus']);
    Widget half(String name, String key, int n) {
      final c = flM(b[key]), m = flM(bm[key]);
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Row(children: [
          SizedBox(width: 56, child: Text(name, style: context.type.label.copyWith(fontWeight: FontWeight.w700))),
          Expanded(child: Text('$n trades, fake ${flPct(c['fake_pct'])}, won ${flPct(c['win_pct'])}, caught ${flN(m['moves_caught']).toInt()} moves (${flN(m['big_caught_5pct_plus']).toInt()} big)', style: context.type.metadata)),
          Text(flUsdt(c['net_usdt']), style: context.type.secondary),
        ]),
      );
    }
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${flN(sc['trades']).toInt()} paper trades, ${flS(sc['train_from_utc'])} to ${flS(sc['test_to_utc'])} (UTC). TEST starts ${flS(sc['split_utc'])}.', style: context.type.secondary),
        const SizedBox(height: AppSpacing.s),
        half('TRAIN', 'train', flN(sc['train_trades']).toInt()),
        half('TEST', 'test', flN(sc['test_trades']).toInt()),
      ]),
    );
  }

  Widget _verdicts(BuildContext context, Map<String, dynamic> vc) {
    if (vc.isEmpty) return const SizedBox.shrink();
    return OwlListCard(children: [for (final e in vc.entries) flRow(context, e.key.replaceAll('_', ' '), '', '${e.value}', color: flVerdictColor(context, e.key))]);
  }

  // ---------------------------------------------------------------- one filter row
  Widget _row(BuildContext context, Map<String, dynamic> j, {bool verdict = false}) {
    final p = context.palette;
    final tr = flM(j['train']), te = flM(j['test']);
    final luck = j['luck_random_as_good_pct'];
    final gain = flN(te['net_gain']);
    final sub = 'TRAIN ${flUsdt(tr['net_gain'])} (${flN(tr['blocked']).toInt()} blocked), TEST ${flUsdt(te['net_gain'])} (${flN(te['blocked']).toInt()}), cut ${flN(te['losers_cut']).toInt()} losers / ${flN(te['winners_cut']).toInt()} winners, moves lost ${flN(te['moves_lost']).toInt()}${flHas(luck) ? ', luck ${flN(luck).toStringAsFixed(0)}%' : ''}';
    return flRow(context, flS(j['filter']).replaceFirst('BLOCK ', 'Block '), sub, verdict ? flS(j['verdict']).replaceAll('_', ' ') : '${flUsdt(gain)} USDT', color: verdict ? flVerdictColor(context, flS(j['verdict'])) : (gain >= 0 ? p.profit : p.loss));
  }

  // ---------------------------------------------------------------- best cut-off per number
  List<Widget> _cutoffs(BuildContext context, List<Map<String, dynamic>> list) {
    if (list.isEmpty) return [];
    return [
      flFold(context, 'BEST CUT-OFF PER NUMBER', '${list.length} numbers (cut picked on TRAIN, judged on TEST)', [
        for (final j in list)
          j.containsKey('train')
              ? _row(context, j, verdict: true)
              : flRow(context, flS(j['filter']).replaceFirst('BLOCK ', 'Block '), j['cuts_tried'] != null ? '${flN(j['cuts_tried']).toInt()} cuts tried on TRAIN' : '${flN(j['numbers_on_train']).toInt()} numbers on TRAIN', flS(j['verdict']).replaceAll('_', ' '), color: flVerdictColor(context, flS(j['verdict']))),
      ]),
    ];
  }

  // ---------------------------------------------------------------- stack
  List<Widget> _stack(BuildContext context, Map<String, dynamic> s) {
    if (s.isEmpty) return [];
    final steps = flMl(s['steps']);
    final head = const OwlSectionLabel('Stack of filters', note: 'added on TRAIN, judged on TEST');
    if (steps.isEmpty) return [head, flNote(context, flS(s['result']).isEmpty ? 'No stack.' : flS(s['result']))];
    final te = flM(s['test']);
    final luck = s['luck_random_as_good_pct'];
    return [
      head,
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${steps.length} filters together: ${flS(s['verdict']).replaceAll('_', ' ')}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: flVerdictColor(context, flS(s['verdict'])))),
          const SizedBox(height: 4),
          Text('TEST: blocks ${flN(te['blocked']).toInt()} trades, saves ${flUsdt(te['net_gain'])} USDT, moves lost ${flN(te['moves_lost']).toInt()}${flHas(luck) ? ', luck ${flN(luck).toStringAsFixed(0)}%' : ''}.', style: context.type.secondary),
        ]),
      ),
      const SizedBox(height: AppSpacing.s),
      OwlListCard(children: [for (final x in steps) flRow(context, flS(x['added']).replaceFirst('BLOCK ', 'Block '), 'TRAIN after: ${flUsdt(x['train_net_gain_after'])}', 'TEST ${flUsdt(x['test_net_gain_after'])}')]),
    ];
  }

  // ---------------------------------------------------------------- protect
  List<Widget> _protect(BuildContext context, List<Map<String, dynamic>> list) {
    if (list.isEmpty) return [];
    return [
      flFold(context, 'PROTECT: NEVER BLOCK', 'these buckets earn the most in both halves', [
        for (final x in list) flRow(context, flS(x['bucket']), 'TRAIN ${flN(x['trades_train']).toInt()} trades ${flUsdt(x['net_train'])}, TEST ${flN(x['trades_test']).toInt()} trades ${flUsdt(x['net_test'])}', 'keep', color: context.palette.profit),
      ]),
    ];
  }
}
