import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import 'filter_part_loader.dart';

/// Part 8B-1 (README_FILTER): the FAKES tab = the saved summary of Part 2 (fake signals; it holds the Part 1 numbers too). Read only.
/// MAIN and SNIPER are never added together: one switch picks the group. Blocks: headline per timeframe (owner question 1 and 2), exits (SL vs OPPOSITE ...),
/// time of day (question 4), losing trades before the first winner (question 4), standouts, and every bucket table (closed by default).
/// FAKE = net loss AND best ROI never covered the round-trip fee. GAVE_BACK = net loss but it was good for a moment. A standout is a QUESTION for the filter lab, never a rule.
/// Dart NOT compiled (the APK build is the proof).
class FilterFakesTab extends StatefulWidget {
  const FilterFakesTab({super.key});

  @override
  State<FilterFakesTab> createState() => _FilterFakesTabState();
}

class _FilterFakesTabState extends State<FilterFakesTab> {
  String _g = 'MAIN';

  @override
  Widget build(BuildContext context) {
    return FilterPartView(ids: const ['f2'], builder: (c, data, missing) => _body(c, flM(data['f2'])));
  }

  Widget _body(BuildContext context, Map<String, dynamic> d) {
    final g = flM(d[_g]);
    final head = flM(g['headline']);
    final all = flM(head['all']);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OwlSegmented(items: const [('MAIN', 'Main'), ('SNIPER', 'Sniper')], active: _g, onPick: (k) => setState(() => _g = k)),
      if (flS(d['fake_definition']).isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.s), child: Text(flS(d['fake_definition']), style: context.type.caption)),
      if (flN(all['trades']) == 0)
        flNote(context, 'No ${_g == 'MAIN' ? 'Main' : 'Sniper'} paper trades in the summary.')
      else ...[
        const OwlSectionLabel('How many, how many fake'),
        _headCard(context, all, flM(head['by_timeframe'])),
        ..._exits(context, flM(g['exits'])),
        ..._time(context, flM(g['time'])),
        ..._before(context, flM(g['before_first_winner'])),
        ..._standouts(context, flM(g['standouts'])),
        ..._tables(context, flM(g['tables'])),
      ],
    ]);
  }

  // ---------------------------------------------------------------- headline
  Widget _headCard(BuildContext context, Map<String, dynamic> all, Map<String, dynamic> tfs) {
    final p = context.palette;
    final net = flN(all['net_usdt']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${flN(all['trades']).toInt()} trades: ${flPct(all['fake_pct'])} fake, ${flPct(all['win_pct'])} won.', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Text('Net ${flUsdt(net)} USDT. Lost money ${flPct(all['loss_pct'])} of the time (fake + gave back).', style: context.type.secondary.copyWith(color: net >= 0 ? p.profit : p.loss)),
        if (tfs.isNotEmpty) ...[
          Padding(padding: const EdgeInsets.symmetric(vertical: AppSpacing.s), child: Divider(height: 1, color: p.border)),
          for (final e in tfs.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Row(children: [
                SizedBox(width: 64, child: Text(e.key, style: context.type.label.copyWith(fontWeight: FontWeight.w700))),
                Expanded(child: Text('${flN(flM(e.value)['trades']).toInt()} trades, fake ${flPct(flM(e.value)['fake_pct'])}${flThin(flM(e.value)) ? '  (few trades)' : ''}', style: context.type.metadata)),
                Text(flUsdt(flM(e.value)['net_usdt']), style: context.type.secondary),
              ]),
            ),
        ],
      ]),
    );
  }

  // ---------------------------------------------------------------- exits
  List<Widget> _exits(BuildContext context, Map<String, dynamic> ex) {
    if (ex.isEmpty) return [];
    final p = context.palette;
    return [
      const OwlSectionLabel('How the trades ended', note: 'SL vs opposite signal ...'),
      OwlListCard(children: [
        for (final e in ex.entries)
          flRow(
            context,
            e.key,
            '${flN(flM(e.value)['trades']).toInt()} trades, fake ${flPct(flM(e.value)['fake_pct'])}, best ${flPct(flM(e.value)['avg_best_roi_pct'])} ROI, gave back ${flPct(flM(e.value)['avg_giveback_roi_pct'])}, held ${flS(flM(e.value)['avg_hold'])}',
            flUsdt(flM(e.value)['net_usdt']),
            color: flN(flM(e.value)['net_usdt']) >= 0 ? p.profit : p.loss,
          ),
      ]),
    ];
  }

  // ---------------------------------------------------------------- time
  List<Widget> _time(BuildContext context, Map<String, dynamic> t) {
    final sess = flM(t['per_session']);
    final hours = flM(t['per_hour']);
    if (sess.isEmpty && hours.isEmpty) return [];
    Widget row(MapEntry<String, dynamic> e) {
      final b = flM(e.value);
      return flRow(context, e.key, '${flN(b['trades']).toInt()} trades, won ${flPct(b['win_pct'])}${flThin(b) ? ', few trades' : ''}', 'fake ${flPct(b['fake_pct'])}');
    }
    return [
      OwlSectionLabel('Time of day', note: 'UTC day = 5:30 AM IST'),
      if (sess.isNotEmpty) OwlListCard(children: [for (final e in sess.entries) row(e)]),
      if (hours.isNotEmpty) ...[const SizedBox(height: AppSpacing.s), flFold(context, 'PER HOUR', '${hours.length} hours with trades', [for (final e in hours.entries) row(e)])],
    ];
  }

  // ---------------------------------------------------------------- before the first winner
  List<Widget> _before(BuildContext context, Map<String, dynamic> b) {
    if (flN(b['coin_days']) == 0) return [];
    final dist = flM(b['losing_trades_before_first_winner']);
    return [
      const OwlSectionLabel('Fakes before the real move'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(
            '${flN(b['coin_days']).toInt()} coin-days: ${flN(b['coin_days_with_a_winner']).toInt()} had a winner, ${flN(b['coin_days_with_no_winner']).toInt()} had none.',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 4),
          Text(
            flHas(b['avg_losing_before_first_winner'])
                ? 'Before the first winner a coin lost ${flN(b['avg_losing_before_first_winner']).toStringAsFixed(2)} trades on average (${flN(b['avg_fakes_before_first_winner']).toStringAsFixed(2)} of them fake).'
                : 'Not enough coin-days with a winner.',
            style: context.type.secondary,
          ),
          if (dist.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Losers before the first winner: ${dist.entries.map((e) => '${e.key}: ${e.value}').join('   ')}', style: context.type.metadata)),
          if (flThin(b)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: read this as a hint only.', style: context.type.caption)),
        ]),
      ),
    ];
  }

  // ---------------------------------------------------------------- standouts
  List<Widget> _standouts(BuildContext context, Map<String, dynamic> s) {
    final hi = flMl(s['highest_fake_pct']), lo = flMl(s['lowest_fake_pct']);
    if (hi.isEmpty && lo.isEmpty) return [];
    final p = context.palette;
    Widget row(Map<String, dynamic> x) {
      final st = x['stable_both_halves'];
      final stable = st == true ? 'stable in both halves' : (st == false ? 'NOT stable' : 'stability unknown');
      final pts = flN(x['vs_all_pts']);
      return flRow(context, '${flS(x['table'])}: ${flS(x['bucket'])}', '${flN(x['trades']).toInt()} trades, fake ${flPct(x['fake_pct'])}, $stable', '${pts >= 0 ? '+' : ''}${pts.toStringAsFixed(1)} pts', color: pts > 0 ? p.loss : p.profit);
    }
    return [
      OwlSectionLabel('Standouts', note: 'all trades fake ${flPct(s['all_fake_pct'])}'),
      if (hi.isNotEmpty) flFold(context, 'MOST FAKE', 'highest fake % (30+ trades)', [for (final x in hi) row(x)]),
      if (lo.isNotEmpty) flFold(context, 'LEAST FAKE', 'lowest fake % (30+ trades)', [for (final x in lo) row(x)]),
      if (flS(s['warning']).isNotEmpty) Text(flS(s['warning']), style: context.type.caption),
    ];
  }

  // ---------------------------------------------------------------- every bucket table
  List<Widget> _tables(BuildContext context, Map<String, dynamic> tb) {
    if (tb.isEmpty) return [];
    return [
      OwlSectionLabel('All tables', note: '${tb.length}'),
      for (final t in tb.entries)
        flFold(context, t.key.toUpperCase(), '${flM(t.value).length} buckets', [
          for (final b in flM(t.value).entries)
            flRow(context, b.key, '${flN(flM(b.value)['trades']).toInt()} trades, won ${flPct(flM(b.value)['win_pct'])}, net ${flUsdt(flM(b.value)['net_usdt'])}${flThin(flM(b.value)) ? ', few trades' : ''}', flM(b.value).containsKey('fake_pct') ? 'fake ${flPct(flM(b.value)['fake_pct'])}' : 'n/a'),
        ]),
    ];
  }
}
