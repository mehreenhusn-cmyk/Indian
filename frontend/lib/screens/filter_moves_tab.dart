import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import 'filter_part_loader.dart';

/// Part 8B-1 (README_FILTER): the MOVES tab = saved summaries of Part 3A (rallies and dumps found in the saved 5m candles, zigzag) and Part 3B (which of them the bots caught, caught late, missed or traded the wrong way). Read only.
/// Two switches: size tier (3%+, 5%+, 10%+) and group (Main / Sniper, never added together). Blocks: what the moves look like (3A), caught or missed (3B), why Main missed, catch rate per move feature, the b3 overlay.
/// The zigzag definition (where a move ends) is shown as text: it is a definition, not a trading rule. Dart NOT compiled (the APK build is the proof).
class FilterMovesTab extends StatefulWidget {
  const FilterMovesTab({super.key});

  @override
  State<FilterMovesTab> createState() => _FilterMovesTabState();
}

class _FilterMovesTabState extends State<FilterMovesTab> {
  String _tier = '3%+';
  String _g = 'MAIN';

  static const _catNames = {
    'ALREADY_IN': 'Already in when it started',
    'EARLY': 'Caught early (first third)',
    'MID': 'Caught mid (second third)',
    'LATE': 'Caught late (last third)',
    'WRONG_WAY': 'Traded the wrong way',
    'MISSED_COIN_TRADED': 'Missed (coin traded, not this move)',
    'MISSED_NOT_TRADED': 'Missed (coin not traded that day)',
  };

  @override
  Widget build(BuildContext context) {
    return FilterPartView(ids: const ['f3a', 'f3b'], builder: (c, data, missing) => _body(c, flM(data['f3a']), flM(data['f3b']), missing));
  }

  Widget _body(BuildContext context, Map<String, dynamic> a, Map<String, dynamic> b, List<String> missing) {
    final tiers = flM(a['tiers']).keys.toList();
    if (tiers.isNotEmpty && !tiers.contains(_tier)) _tier = tiers.first;
    final t3a = flM(flM(a['tiers'])[_tier]);
    final g3b = flM(flM(flM(b[_g])['tiers'])[_tier]);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (tiers.isNotEmpty) OwlSegmented(items: [for (final t in tiers) (t, t)], active: _tier, onPick: (k) => setState(() => _tier = k)),
      OwlSegmented(items: const [('MAIN', 'Main'), ('SNIPER', 'Sniper')], active: _g, onPick: (k) => setState(() => _g = k)),
      if (missing.isNotEmpty) flNote(context, 'Not made yet: ${missing.join(', ')}. That half is empty until the study run has made it.'),
      if (flM(a['definition']).isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.s),
          child: Text('A move ends when price falls back by ${flS(flM(a['definition'])['leg_ends_when_price_falls_back_by'])}. This is a definition of where a move ends, not a trading rule.', style: context.type.caption),
        ),
      if (t3a.isNotEmpty) ..._looks(context, t3a),
      if (g3b.isNotEmpty) ..._caught(context, g3b, b),
    ]);
  }

  // ---------------------------------------------------------------- 3A: what moves look like
  List<Widget> _looks(BuildContext context, Map<String, dynamic> t) {
    final kinds = flM(t['by_coin_day_kind']);
    final lists = flM(t['list_side_vs_move_direction']);
    Widget dist(String title, dynamic v) {
      final m = flM(v);
      return flFold(context, title, m.entries.map((e) => '${e.key}: ${e.value}').take(3).join('  ') + (m.length > 3 ? ' ...' : ''), [for (final e in m.entries) flRow(context, e.key, '', '${e.value} moves')]);
    }
    return [
      OwlSectionLabel('What the $_tier moves look like', note: '3A'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${flN(t['moves']).toInt()} moves: ${flN(t['rallies']).toInt()} rallies, ${flN(t['dumps']).toInt()} dumps.', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('Average size ${flHas(t['avg_size_pct']) ? '${flN(t['avg_size_pct']).toStringAsFixed(2)}%' : '-'}, average length ${flS(t['avg_duration'])}. ${flN(t['still_running_at_day_end']).toInt()} were still running at day end.', style: context.type.secondary),
          Text('${flN(t['coin_days_with_a_move']).toInt()} of ${flN(t['coin_days']).toInt()} coin-days had one.', style: context.type.metadata),
          if (flThin(t)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: read as a hint only.', style: context.type.caption)),
        ]),
      ),
      if (kinds.isNotEmpty) ...[
        const SizedBox(height: AppSpacing.s),
        OwlListCard(children: [
          for (final e in kinds.entries)
            flRow(context, e.key, '${flN(flM(e.value)['coin_days']).toInt()} coin-days, ${flN(flM(e.value)['moves']).toInt()} moves, ${flPct(flM(e.value)['share_of_coin_days_with_a_move_pct'])} had a move', '${flS(flM(e.value)['moves_per_coin_day'])} per day'),
        ]),
        Text('IN_LIST = coin in that day\'s top-5 gainers / losers. CONTROL = normal coins. Compare the two, not with zero.', style: context.type.caption),
      ],
      const SizedBox(height: AppSpacing.s),
      dist('START SESSION (UTC)', t['start_session']),
      dist('START HOUR', t['start_hour']),
      dist('LENGTH', t['duration']),
      dist('SPEED', t['speed']),
      dist('START OF THE MOVE (share in first 3 candles)', t['start_of_move']),
      dist('% FROM DAY OPEN WHEN IT STARTED (with the move)', t['start_pump_with_move']),
      dist('NTH MOVE OF THE COIN-DAY', t['nth_move_of_coin_day']),
      if (lists.isNotEmpty) dist('GAINER / LOSER LIST vs DIRECTION', lists),
    ];
  }

  // ---------------------------------------------------------------- 3B: caught or missed
  List<Widget> _caught(BuildContext context, Map<String, dynamic> g, Map<String, dynamic> b) {
    final p = context.palette;
    final all = flM(g['all']);
    final who = _g == 'MAIN' ? 'Main' : 'Sniper';
    final why = flM(g['why_missed']);
    final feat = flM(g['catch_rate_by_move_feature']);
    final b3 = flM(flM(b['b3'])[_tier]);
    Widget cat(String k) {
      final n = flN(all[k]).toInt();
      return flRow(context, _catNames[k] ?? k, '', '$n', color: k.startsWith('MISSED') || k == 'WRONG_WAY' ? (n > 0 ? p.warning : null) : null);
    }
    Widget dir(String title, Map<String, dynamic> x) =>
        flRow(context, title, '${flN(x['moves']).toInt()} moves, caught ${flN(x['caught']).toInt()}, early ${flPct(x['early_catch_rate_pct'])}${flThin(x) ? ', few moves' : ''}', flPct(x['catch_rate_pct']));
    return [
      OwlSectionLabel('Did $who catch them', note: '3B'),
      if (flN(all['moves']) == 0)
        flNote(context, 'No $_tier moves on coin-days the bots traded.')
      else ...[
        OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Caught ${flN(all['caught']).toInt()} of ${flN(all['moves']).toInt()} moves (${flPct(all['catch_rate_pct'])}). Early: ${flPct(all['early_catch_rate_pct'])}.', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(
              'Of the move\'s price travel the first trade got ${flHas(all['capture_median_pct']) ? '${flN(all['capture_median_pct']).toStringAsFixed(0)}% (median)' : 'n/a'}. Catching trades made ${flUsdt(all['net_usdt_of_catching_trades'])} USDT in total.',
              style: context.type.secondary,
            ),
            Text('Average size caught ${flHas(all['avg_size_pct_caught']) ? '${flN(all['avg_size_pct_caught']).toStringAsFixed(2)}%' : '-'}, missed ${flHas(all['avg_size_pct_missed']) ? '${flN(all['avg_size_pct_missed']).toStringAsFixed(2)}%' : '-'}.', style: context.type.metadata),
            if (flThin(all)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: read as a hint only.', style: context.type.caption)),
          ]),
        ),
        const SizedBox(height: AppSpacing.s),
        OwlListCard(children: [for (final k in _catNames.keys) cat(k)]),
        const SizedBox(height: AppSpacing.s),
        OwlListCard(children: [dir('Rallies', flM(g['rally'])), dir('Dumps', flM(g['dump']))]),
        Text('A catching trade is not proof the filter is fine: it can still have lost money. Capture = price % the earliest trade made / move size.', style: context.type.caption),
      ],
      if (why.isNotEmpty) ...[
        const OwlSectionLabel('Why Main missed'),
        OwlListCard(children: [
          flRow(context, 'Signal was skipped', 'a same-direction signal came and was not taken', '${flN(why['SIGNAL_SKIPPED']).toInt()}'),
          flRow(context, 'Signal opened by another bot', '', '${flN(why['SIGNAL_OPENED_OTHER_BOT']).toInt()}'),
          flRow(context, 'No signal at all', '', '${flN(why['NO_SIGNAL']).toInt()}'),
        ]),
        if (flM(why['top_skip_reasons']).isNotEmpty) flFold(context, 'SKIP REASONS', 'top ${flM(why['top_skip_reasons']).length} reasons', [for (final e in flM(why['top_skip_reasons']).entries) flRow(context, e.key, '', '${e.value}')]),
      ],
      if (feat.isNotEmpty) ...[
        const OwlSectionLabel('Catch rate by move feature', note: 'smallest tier'),
        for (final t in feat.entries)
          flFold(context, t.key.replaceAll('_', ' ').toUpperCase(), '${flM(t.value).length} groups', [
            for (final e in flM(t.value).entries) flRow(context, e.key, '${flN(flM(e.value)['moves']).toInt()} moves, caught ${flN(flM(e.value)['caught']).toInt()}${flThin(flM(e.value)) ? ', few moves' : ''}', flPct(flM(e.value)['catch_rate_pct'])),
          ]),
      ],
      if (b3.isNotEmpty) ...[
        const OwlSectionLabel('b3 (chop bot) on the same moves'),
        b3['present'] == true && b3['error'] == null
            ? OwlListCard(children: [
                flRow(context, 'b3 took a trade', '', '${flN(b3['TAKE']).toInt()}'),
                flRow(context, 'b3 saw a signal but skipped', '', '${flN(b3['SKIP_ONLY']).toInt()}'),
                flRow(context, 'b3 had no signal', '', '${flN(b3['NO_SIGNAL']).toInt()}'),
              ])
            : flNote(context, flS(b3['error']).isNotEmpty ? 'b3 database problem: ${flS(b3['error'])}' : flS(b3['note'])),
        if (flS(b3['note']).isNotEmpty && b3['present'] == true) Text(flS(b3['note']), style: context.type.caption),
      ],
    ];
  }
}
