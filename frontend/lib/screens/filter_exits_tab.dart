import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import 'filter_part_loader.dart';

/// Part 8B-2a (README_FILTER): the EXITS tab = saved summaries of Part 5A (exit lab 1: fixed exit rules, give-back, TP booking) and Part 5B (exit lab 2: curve exit, after TP4, best pairs). Read only.
/// Every PAPER trade is replayed candle by candle from its entry and each exit rule says where it would have left. CALIB = same entry, exit at the real closing candle. Change vs CALIB is money (USDT).
/// Switches: Main / Sniper (never added together), all timeframes / 5m only, horizon H0 (inside the real trade) / H1 (24 candles longer: 2 h on 5m, 6 h on 15m).
/// Blocks: model check, give-back (how much profit was handed back), TP booking, the 14 rules with verdicts, what happens after TP4, the best pairs of rules.
/// Verdicts: BETTER (gain in both halves, runners not hurt), TRADEOFF (gain but runners lose), UNSTABLE (one half only), WORSE, TOO_FEW. A BETTER is a candidate, not a rule: exit rules are NOT in the gate (entry gate only).
/// Hindsight replay: fills assumed at the level. Dart NOT compiled (the APK build is the proof).
class FilterExitsTab extends StatefulWidget {
  const FilterExitsTab({super.key});

  @override
  State<FilterExitsTab> createState() => _FilterExitsTabState();
}

class _FilterExitsTabState extends State<FilterExitsTab> {
  String _g = 'MAIN';
  String _scope = 'all';
  String _hz = 'H0';

  static const _order = {'BETTER': 0, 'TRADEOFF': 1, 'UNSTABLE': 2, 'WORSE': 3, 'TOO_FEW': 4};

  @override
  Widget build(BuildContext context) {
    return FilterPartView(ids: const ['f5a', 'f5b'], builder: (c, data, missing) => _body(c, flM(data['f5a']), flM(data['f5b']), missing));
  }

  Widget _body(BuildContext context, Map<String, dynamic> a, Map<String, dynamic> b, List<String> missing) {
    final sa = flM(flM(a[_g])[_scope]), sb = flM(flM(b[_g])[_scope]);
    final empty = (sa.isEmpty || flThin(sa)) && (sb.isEmpty || flThin(sb));
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OwlSegmented(items: const [('MAIN', 'Main'), ('SNIPER', 'Sniper')], active: _g, onPick: (k) => setState(() => _g = k)),
      OwlSegmented(items: const [('all', 'All timeframes'), ('5m', '5m only')], active: _scope, onPick: (k) => setState(() => _scope = k)),
      OwlSegmented(items: const [('H0', 'H0: inside the trade'), ('H1', 'H1: hold longer')], active: _hz, onPick: (k) => setState(() => _hz = k)),
      if (missing.isNotEmpty) flNote(context, 'Not made yet: ${missing.join(', ')}. That half is empty until the study run has made it.'),
      if (empty)
        flNote(context, 'NOT ENOUGH DATA for this scope (the exit lab needs 60+ replayed trades, and saved candles).')
      else ...[
        if (!flThin(sa) && sa.isNotEmpty) ..._model(context, sa),
        if (!flThin(sa) && sa.isNotEmpty) ..._giveback(context, flM(sa['giveback'])),
        if (!flThin(sa) && sa.isNotEmpty) ..._tp(context, flM(sa['tp_booking'])),
        ..._rules(context, flThin(sb) || sb.isEmpty ? flM(sa['rules']) : flM(sb['rules_all_14']), flThin(sb) || sb.isEmpty),
        if (!flThin(sb) && sb.isNotEmpty) ..._tp4(context, flM(sb['tp4_story'])),
        if (!flThin(sb) && sb.isNotEmpty) ..._pairs(context, flM(sb['pairs_$_hz'])),
        const SizedBox(height: AppSpacing.s),
        Text('Replay is hindsight: fills are assumed at the level, slippage and partial TPs are not replayed. Runners = the top quarter of trades by best ROI. About 105 rules are looked at per horizon, so a few look good by luck.', style: context.type.caption),
        if (flS(b['curve_definition']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(flS(b['curve_definition']), style: context.type.caption)),
      ],
    ]);
  }

  // ---------------------------------------------------------------- model check
  List<Widget> _model(BuildContext context, Map<String, dynamic> s) {
    final m = flM(s['model_check']);
    if (m.isEmpty) return [];
    return [
      OwlSectionLabel('Can the replay be trusted', note: '${flN(s['replayed_trades']).toInt()} trades'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Real net ${flUsdt(m['real_net_usdt'])} USDT, replay (CALIB) ${flUsdt(m['calib_net_usdt'])} USDT. Average gap per trade ${flN(m['avg_abs_diff_usdt']).toStringAsFixed(3)} USDT.', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(flS(m['note']), style: context.type.metadata),
        ]),
      ),
    ];
  }

  // ---------------------------------------------------------------- give-back
  List<Widget> _giveback(BuildContext context, Map<String, dynamic> g) {
    if (g.isEmpty) return [];
    final by = flM(g['by_exit']);
    return [
      const OwlSectionLabel('Profit given back', note: 'real trades'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${flN(g['good_for_a_moment (best ROI above fee)']).toInt()} of ${flN(g['trades_with_mfe']).toInt()} trades were in profit above the fee at some moment; ${flN(g['of_those_ended_net_loss']).toInt()} still ended in a loss, ${flN(g['of_those_gave_back_over_half']).toInt()} gave back over half.', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('Average best ROI ${flPct(g['avg_best_roi_pct'])}, average give-back ${flPct(g['avg_giveback_roi_pct_of_good'])}. Profit kept: ${flPct(g['profit_kept_pct'])} of the peak.', style: context.type.secondary),
          if (flThin(g)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: read as a hint only.', style: context.type.caption)),
        ]),
      ),
      if (by.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.s),
        OwlListCard(children: [for (final e in by.entries) flRow(context, e.key, '${flN(flM(e.value)['good_trades']).toInt()} good trades, ${flN(flM(e.value)['net_loss']).toInt()} lost, gave back ${flPct(flM(e.value)['avg_giveback_roi_pct'])}', flUsdt(flM(e.value)['net_usdt']))]),
      ],
    ];
  }

  // ---------------------------------------------------------------- TP booking
  List<Widget> _tp(BuildContext context, Map<String, dynamic> t) {
    if (t.isEmpty) return [];
    return [
      const OwlSectionLabel('TP booking', note: 'did price reach the target'),
      OwlListCard(children: [
        for (final k in ['tp1', 'tp4'])
          if (t[k] != null)
            flRow(
              context,
              k.toUpperCase(),
              'touched ${flN(flM(t[k])['touched']).toInt()}, not touched ${flN(flM(t[k])['not_touched']).toInt()}, touched but net not above zero ${flN(flM(t[k])['touched_but_net_not_above_zero']).toInt()}, avg net when touched ${flUsdt(flM(t[k])['touched_avg_net_usdt'])}',
              flUsdt(flM(t[k])['touched_net_usdt']),
            ),
      ]),
    ];
  }

  // ---------------------------------------------------------------- the rules
  List<Widget> _rules(BuildContext context, Map<String, dynamic> rules, bool only5a) {
    final list = <MapEntry<String, Map<String, dynamic>>>[];
    for (final e in rules.entries) {
      if (e.key.endsWith(' $_hz')) list.add(MapEntry(e.key.substring(0, e.key.length - 3), flM(e.value)));
    }
    if (list.isEmpty) return [];
    list.sort((x, y) {
      final c = (_order[flS(x.value['verdict'])] ?? 9).compareTo(_order[flS(y.value['verdict'])] ?? 9);
      return c != 0 ? c : flN(y.value['change_vs_calib_test']).compareTo(flN(x.value['change_vs_calib_test']));
    });
    return [
      OwlSectionLabel('Exit rules ($_hz)', note: only5a ? '${list.length} rules (5A)' : '${list.length} rules (5A + 5B)'),
      OwlListCard(children: [
        for (final e in list)
          flRow(
            context,
            e.key.replaceAll('_', ' '),
            'vs CALIB: TRAIN ${flUsdt(e.value['change_vs_calib_train'])} (${flN(e.value['trades_changed_train']).toInt()} changed), TEST ${flUsdt(e.value['change_vs_calib_test'])} (${flN(e.value['trades_changed_test']).toInt()}), exits earlier ${flPct(e.value['exits_earlier_pct'])}, runners ${_pair(e.value['runners_change_train_test'])}',
            flS(e.value['verdict']),
            color: flVerdictColor(context, flS(e.value['verdict'])),
          ),
      ]),
    ];
  }

  String _pair(dynamic v) => v is List && v.length == 2 ? '${flUsdt(v[0])} / ${flUsdt(v[1])}' : '-';

  // ---------------------------------------------------------------- after TP4
  List<Widget> _tp4(BuildContext context, Map<String, dynamic> s) {
    if (flN(s['touched_tp4']) == 0) return [];
    Widget r(String name, String key) => flRow(context, name, '', flUsdt(s[key]) + ' USDT');
    return [
      OwlSectionLabel('After TP4', note: '${flN(s['touched_tp4']).toInt()} trades touched TP4'),
      OwlListCard(children: [
        r('Real net', 'real_net_usdt'),
        r('Replay at the real exit (CALIB)', 'calib_net_usdt'),
        r('Leave at TP4', 'leave_at_TP4_net_usdt'),
        r('Keep, trail 25% (H1)', 'after_tp4_trail_25_H1_net_usdt'),
        r('Keep, trail 50% (H1)', 'after_tp4_trail_50_H1_net_usdt'),
        r('Keep, curve exit (H1)', 'after_tp4_curve_H1_net_usdt'),
      ]),
      if (flThin(s)) Text('NOT ENOUGH DATA: read as a hint only.', style: context.type.caption),
    ];
  }

  // ---------------------------------------------------------------- pairs
  List<Widget> _pairs(BuildContext context, Map<String, dynamic> p) {
    final top = flMl(p['top_by_train_judged_on_test']);
    if (p.isEmpty) return [];
    return [
      OwlSectionLabel('Best pairs of rules ($_hz)', note: '${flN(p['pairs_qualified_on_train']).toInt()} of ${flN(p['pairs_tried']).toInt()} qualified on TRAIN'),
      if (top.isEmpty)
        flNote(context, 'No pair gained on TRAIN without hurting the runners.')
      else
        OwlListCard(children: [
          for (final x in top)
            flRow(
              context,
              flS(x['pair']).replaceAll('_', ' ').replaceAll(' (first one to trigger)', ''),
              'first one to trigger. TRAIN ${flUsdt(x['change_vs_calib_train'])} (${flN(x['trades_changed_train']).toInt()}), TEST ${flUsdt(x['change_vs_calib_test'])} (${flN(x['trades_changed_test']).toInt()}), runners ${_pair(x['runners_change_train_test'])}',
              flS(x['verdict']),
              color: flVerdictColor(context, flS(x['verdict'])),
            ),
        ]),
    ];
  }
}
