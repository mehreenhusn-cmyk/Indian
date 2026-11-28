import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import 'filter_part_loader.dart';

/// Part 8B-2b (README_FILTER): the DECISIONS tab = saved summaries of Part 6 (ENTER / WAIT / REJECT / NO_TRADE) and Part 1B (Sniper LEARN + b3 log). Read only.
/// Three views: "Four words" (Part 6), "Sniper LEARN" and "b3 log" (both Part 1B).
/// Four words: SETUP (band + TSI + EMA agree) x CURVE (slope of 5 candles with the side). FLAT -> NO_TRADE, AGAINST or WEAK -> REJECT, COMPLETE + RUNNING -> ENTER, rest WAIT. Fixed definitions, not fitted to money.
/// Judged on the real paper trades (Main / Sniper never added, all timeframes / 5m only): per word, the four word filters with Part 4 verdicts, the WAIT test, and the b3 overlay (my word x b3 action x b3 verdict).
/// A PASS here is a candidate, not a rule: the gate (Part 7) builds its own rules from Part 4 only. Dart NOT compiled (the APK build is the proof).
class FilterDecisionsTab extends StatefulWidget {
  const FilterDecisionsTab({super.key});

  @override
  State<FilterDecisionsTab> createState() => _FilterDecisionsTabState();
}

class _FilterDecisionsTabState extends State<FilterDecisionsTab> {
  String _view = 'words';
  String _g = 'MAIN';
  String _scope = 'all';

  static const _wordList = ['ENTER', 'WAIT', 'NO_TRADE', 'REJECT', 'NO_DATA'];

  @override
  Widget build(BuildContext context) {
    return FilterPartView(ids: const ['f6', 'f1b'], builder: (c, data, missing) => _body(c, flM(data['f6']), flM(data['f1b']), missing));
  }

  Widget _body(BuildContext context, Map<String, dynamic> f6, Map<String, dynamic> f1b, List<String> missing) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      OwlSegmented(items: const [('words', 'Four words'), ('learn', 'Sniper LEARN'), ('b3', 'b3 log')], active: _view, onPick: (k) => setState(() => _view = k)),
      if (_view == 'words')
        ..._wordsView(context, f6, missing.contains('f6'))
      else if (_view == 'learn')
        ..._learnView(context, flM(f1b['sniper_learn']), missing.contains('f1b'))
      else
        ..._b3View(context, flM(f1b['b3']), missing.contains('f1b')),
    ]);
  }

  Color _wordColor(BuildContext context, String w) {
    final p = context.palette;
    switch (w) {
      case 'ENTER':
        return p.profit;
      case 'WAIT':
        return p.warning;
      case 'REJECT':
        return p.loss;
      default:
        return p.textMuted;
    }
  }

  String _cnt(Map<String, dynamic> c) => '${flN(c['trades']).toInt()} trades, won ${flPct(c['win_pct'])}, fake ${flPct(c['fake_pct'])}';

  // ---------------------------------------------------------------- view 1: the four words (Part 6)
  List<Widget> _wordsView(BuildContext context, Map<String, dynamic> f, bool missing) {
    if (f.isEmpty) return [const SizedBox(height: AppSpacing.s), flNote(context, 'The Part 6 summary is not made yet. The study run makes it (Overview: "Run study now").')];
    final sc = flM(flM(f[_g])[_scope]);
    final out = <Widget>[
      OwlSegmented(items: const [('MAIN', 'Main'), ('SNIPER', 'Sniper')], active: _g, onPick: (k) => setState(() => _g = k)),
      OwlSegmented(items: const [('all', 'All timeframes'), ('5m', '5m only')], active: _scope, onPick: (k) => setState(() => _scope = k)),
      if (flS(f['framework']).isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(flS(f['framework']), style: context.type.caption)),
      if (flS(f['moves_check']).startsWith('NOT AVAILABLE')) flNote(context, flS(f['moves_check']), bad: true),
    ];
    if (sc.isEmpty || flThin(sc)) {
      out.add(flNote(context, 'NOT ENOUGH DATA for this scope (the four words need enough paper trades with saved candles).'));
    } else {
      out.addAll(_often(context, sc));
      out.addAll(_byWord(context, flM(sc['by_decision'])));
      out.addAll(_filters(context, sc));
      out.addAll(_wait(context, flM(sc['wait_test'])));
    }
    out.addAll(_overlay(context, flM(f['b3_overlay'])));
    out.add(const SizedBox(height: AppSpacing.s));
    out.add(Text('The four words are fixed definitions, not fitted to money. About 8 scopes are looked at, so a PASS can still be luck: check LUCK %. Python Z vs Pine Z is still unchecked.', style: context.type.caption));
    return out;
  }

  List<Widget> _often(BuildContext context, Map<String, dynamic> sc) {
    final h = flM(sc['how_often']);
    if (h.isEmpty) return [];
    return [
      OwlSectionLabel('How often each word comes', note: '${flN(sc['trades']).toInt()} trades'),
      OwlListCard(children: [for (final w in _wordList) if (h[w] != null) flRow(context, w.replaceAll('_', ' '), '', flPct(h[w]), color: _wordColor(context, w))]),
    ];
  }

  List<Widget> _byWord(BuildContext context, Map<String, dynamic> by) {
    if (by.isEmpty) return [];
    return [
      const OwlSectionLabel('What happened to the trades', note: 'real paper trades'),
      OwlListCard(children: [
        for (final w in _wordList)
          if (by[w] != null)
            flRow(context, w.replaceAll('_', ' '), '${_cnt(flM(flM(by[w])['all']))}. TRAIN ${flUsdt(flM(flM(by[w])['train'])['net_usdt'])}, TEST ${flUsdt(flM(flM(by[w])['test'])['net_usdt'])} USDT', flUsdt(flM(flM(by[w])['all'])['net_usdt']),
                color: _wordColor(context, w)),
      ]),
    ];
  }

  List<Widget> _filters(BuildContext context, Map<String, dynamic> sc) {
    final fl = flMl(sc['filters']);
    if (fl.isEmpty) return [];
    return [
      OwlSectionLabel('The words as filters', note: 'split ${flS(sc['split_utc'])} UTC'),
      OwlListCard(children: [for (final j in fl) _filterRow(context, j)]),
    ];
  }

  Widget _filterRow(BuildContext context, Map<String, dynamic> j) {
    final tr = flM(j['train']), te = flM(j['test']);
    final luck = j['luck_random_as_good_pct'];
    final v = flS(j['verdict']);
    final sub = 'TRAIN ${flUsdt(tr['net_gain'])}, TEST ${flUsdt(te['net_gain'])} USDT. TEST blocks ${flN(te['blocked']).toInt()}, losers cut ${flN(te['losers_cut']).toInt()}, winners cut ${flN(te['winners_cut']).toInt()}, moves lost ${flN(te['moves_lost']).toInt()}${flHas(luck) ? ', luck ${flN(luck).toStringAsFixed(0)}%' : ''}';
    return flRow(context, flS(j['filter']), sub, v.replaceAll('_', ' '), color: flVerdictColor(context, v));
  }

  List<Widget> _wait(BuildContext context, Map<String, dynamic> w) {
    if (w.isEmpty) return [];
    return [
      const OwlSectionLabel('WAIT test', note: 'what if we had waited'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${flN(w['wait_trades']).toInt()} WAIT trades. ${flN(w['turned_ENTER_within_3_candles']).toInt()} turned ENTER within 3 candles: entering late ${flUsdt(w['late_entry_net_usdt'])} USDT, entering at the real entry (replay) ${flUsdt(w['same_trades_real_entry_replay_net_usdt'])}, real trades ${flUsdt(w['same_trades_real_net_usdt'])}.',
              style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text('${flN(w['never_turned_ENTER']).toInt()} never turned ENTER: real net ${flUsdt(w['never_turned_ENTER_real_net_usdt'])} USDT.', style: context.type.secondary),
          if (flThin(w)) Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: read as a hint only.', style: context.type.caption)),
        ]),
      ),
    ];
  }

  List<Widget> _overlay(BuildContext context, Map<String, dynamic> o) {
    if (o.isEmpty) return [];
    final table = flM(o['table_my_word_x_b3_action_x_b3_verdict']);
    if (table.isEmpty) {
      final msg = flS(o['error']).isNotEmpty ? flS(o['error']) : (flS(o['note']).isNotEmpty ? flS(o['note']) : 'No b3 decision got a word yet.');
      return [const OwlSectionLabel('b3 overlay'), flNote(context, msg)];
    }
    final rows = <Widget>[];
    for (final w in _wordList) {
      for (final a in flM(table[w]).entries) {
        for (final l in flM(a.value).entries) {
          final cell = flM(l.value);
          rows.add(flRow(context, '$w + b3 ${a.key}', l.key.replaceAll('_', ' '), '${flN(cell['n']).toInt()} / ${flUsdt(cell['net_usdt'])}', color: _wordColor(context, w)));
        }
      }
    }
    return [
      const OwlSectionLabel('b3 overlay', note: 'my word x b3 action x b3 verdict'),
      flFold(context, 'MY WORD x b3', '${flN(o['decisions_given_a_word']).toInt()} b3 decisions got a word (count / net USDT)', rows),
    ];
  }

  // ---------------------------------------------------------------- view 2: Sniper LEARN (Part 1B)
  List<Widget> _learnView(BuildContext context, Map<String, dynamic> sl, bool missing) {
    if (sl.isEmpty) return [const SizedBox(height: AppSpacing.s), flNote(context, 'The Part 1B summary is not made yet. The study run makes it (Overview: "Run study now").')];
    final st = flM(sl['state']), tr = flM(sl['trades']);
    final learn = flM(tr['LEARN']), real = flM(tr['REAL_GATE']);
    final out = <Widget>[const SizedBox(height: AppSpacing.s)];
    if (st['present'] != true) {
      out.add(flNote(context, flS(st['note']).isNotEmpty ? flS(st['note']) : 'No LEARN state yet.'));
    } else {
      final cl = flM(st['closed_by_learn_counter']);
      final p = context.palette;
      out.addAll([
        const OwlSectionLabel('Sniper LEARN now'),
        OwlListCard(children: [
          flRow(context, 'LEARN switch', 'floor ${flS(st['floor'])}, size ${flS(st['size_usdt'])} USDT, max open ${flS(st['max_open'])}, open now ${flS(st['open_now'])}', st['enabled'] == true ? 'ON' : 'OFF', color: st['enabled'] == true ? p.profit : p.textMuted),
          flRow(context, 'Kill switch', flS(st['kill_reason']), st['kill_on'] == true ? 'KILLED' : 'ok', color: st['kill_on'] == true ? p.loss : p.profit),
          flRow(context, 'Closed LEARN trades', 'won ${flN(cl['wins']).toInt()}, lost ${flN(cl['losses']).toInt()}, net ${flUsdt(cl['pnl_usdt'])} USDT', '${flN(cl['n']).toInt()} of 30'),
          flRow(context, 'Orders', 'opened ${flN(st['orders_opened']).toInt()}, not opened ${flN(st['orders_not_opened']).toInt()}', '${flN(st['orders_kept']).toInt()} kept'),
        ]),
        const SizedBox(height: AppSpacing.s),
        flNote(context, flS(st['verdict'])),
      ]);
    }
    final la = flM(learn['all']), ra = flM(real['all']);
    if (la.isNotEmpty) {
      out.addAll([
        const OwlSectionLabel('LEARN vs REAL_GATE', note: 'paper trades'),
        OwlListCard(children: [
          flRow(context, 'LEARN lane', '${_cnt(la)}, avg hold ${flS(la['avg_hold'])}', flUsdt(la['net_usdt'])),
          if (flN(ra['trades']) > 0) flRow(context, 'REAL_GATE lane', '${_cnt(ra)}, avg hold ${flS(ra['avg_hold'])}', flUsdt(ra['net_usdt'])),
        ]),
        Padding(padding: const EdgeInsets.only(top: 4), child: Text('LEARN trades are tiny (1 USDT) and take sideways signals on purpose, so their win % is NOT the real bot win %.', style: context.type.caption)),
      ]);
    }
    out.addAll(_curve(context, flM(learn['learning_curve'])));
    out.addAll(_numbers(context, flM(sl['entry_numbers'])));
    return out;
  }

  List<Widget> _curve(BuildContext context, Map<String, dynamic> cv) {
    if (cv.isEmpty) return [];
    final a = flM(cv['first_half']), b = flM(cv['second_half']);
    if (a.isEmpty || b.isEmpty) return [const OwlSectionLabel('Learning curve'), flNote(context, 'NOT ENOUGH DATA: ${flN(cv['closed_trades']).toInt()} closed LEARN trades so far.')];
    final blocks = flMl(cv['blocks_of_10']);
    return [
      const OwlSectionLabel('Learning curve', note: 'first half vs second half'),
      OwlListCard(children: [
        flRow(context, 'First half', '${_cnt(a)}, avg net ${flUsdt(a['avg_net_usdt'])}', flUsdt(a['net_usdt'])),
        flRow(context, 'Second half', '${_cnt(b)}, avg net ${flUsdt(b['avg_net_usdt'])}', flUsdt(b['net_usdt'])),
      ]),
      Padding(padding: const EdgeInsets.only(top: 4, bottom: AppSpacing.s), child: Text(flS(cv['reading']), style: context.type.caption)),
      if (blocks.isNotEmpty) flFold(context, 'BLOCKS OF 10 TRADES', 'last ${blocks.length} blocks', [for (final x in blocks) flRow(context, 'Trades ${flS(x['trades'])}', 'from ${flS(x['from_utc'])}, won ${flPct(x['win_pct'])}', flUsdt(x['net_usdt']))]),
    ];
  }

  List<Widget> _numbers(BuildContext context, Map<String, dynamic> en) {
    if (en.isEmpty) return [];
    if (en['present'] != true) return [flNote(context, flS(en['note']).isNotEmpty ? flS(en['note']) : 'No entry numbers for LEARN trades yet.')];
    final out = <Widget>[OwlSectionLabel('LEARN trades by entry number', note: '${flN(en['learn_trades_with_numbers']).toInt()} trades')];
    for (final t in flM(en['tables']).entries) {
      final rows = flM(t.value);
      if (rows.isEmpty) continue;
      out.add(flFold(context, t.key.toUpperCase(), '${rows.length} buckets', [for (final r in rows.entries) flRow(context, r.key, '${_cnt(flM(r.value))}${flThin(flM(r.value)) ? ' (few)' : ''}', flUsdt(flM(r.value)['net_usdt']))]));
    }
    return out;
  }

  // ---------------------------------------------------------------- view 3: b3 log (Part 1B)
  List<Widget> _b3View(BuildContext context, Map<String, dynamic> b, bool missing) {
    final out = <Widget>[const SizedBox(height: AppSpacing.s)];
    if (b.isEmpty) return [...out, flNote(context, 'The Part 1B summary is not made yet. The study run makes it (Overview: "Run study now").')];
    if (b['present'] != true) return [...out, flNote(context, flS(b['note']).isNotEmpty ? flS(b['note']) : 'b3 has no log yet.')];
    if (flS(b['error']).isNotEmpty) return [...out, flNote(context, flS(b['error']), bad: true)];
    final d = flM(b['decisions']), t = flM(b['trades']), lg = flM(b['ledger']);
    final rm = flM(lg['rally_missed']), la = flM(lg['loss_avoided']);
    out.addAll([
      const OwlSectionLabel('b3 chop bot', note: 'TAKE / SKIP log'),
      OwlListCard(children: [
        flRow(context, 'Decisions', '${flN(d['take']).toInt()} TAKE, ${flN(d['skip']).toInt()} SKIP', '${flN(d['all']).toInt()}'),
        flRow(context, 'Closed trades', 'won ${flPct(t['win_pct'])}, open now ${flN(t['open_now']).toInt()}${flThin(t) ? ', NOT ENOUGH DATA' : ''}', flUsdt(t['net_usdt'])),
        flRow(context, 'Skips judged', '${flN(flM(b['skips'])['waiting_for_verdict']).toInt()} still waiting for a verdict', '${flN(flM(b['skips'])['judged']).toInt()}'),
      ]),
      const OwlSectionLabel('Skip ledger', note: 'what-if at FULL size'),
      OwlListCard(children: [
        flRow(context, 'Rally missed (skipped, then it ran)', '${flN(rm['n']).toInt()} skips', flUsdt(rm['usdt_what_if']), color: context.palette.loss),
        flRow(context, 'Loss avoided (skipped, it lost)', '${flN(la['n']).toInt()} skips', flUsdt(la['usdt_what_if']), color: context.palette.profit),
      ]),
    ]);
    if (flThin(lg)) out.add(Padding(padding: const EdgeInsets.only(top: 4), child: Text('NOT ENOUGH DATA: fewer than the minimum judged skips, read as a hint only.', style: context.type.caption)));
    final rules = flMl(b['per_rule']), bands = flM(b['per_score_band']), missed = flMl(b['biggest_missed_rallies']);
    out.add(const SizedBox(height: AppSpacing.s));
    if (rules.isNotEmpty) out.add(flFold(context, 'PER RULE', '${rules.length} rules (right % = decision was right)', [for (final r in rules) flRow(context, '${flS(r['action'])} ${flS(r['rule'])}', 'judged ${flN(r['judged']).toInt()}, right ${flPct(r['right_pct'])}${flThin(r) ? ' (few)' : ''}', flUsdt(r['usdt']))]));
    if (bands.isNotEmpty) out.add(flFold(context, 'PER SCORE BAND', '${bands.length} bands', [for (final e in bands.entries) flRow(context, e.key, 'TAKE ${flN(flM(e.value)['take']).toInt()}, SKIP ${flN(flM(e.value)['skip']).toInt()}, judged ${flN(flM(e.value)['judged']).toInt()}', flPct(flM(e.value)['right_pct']))]));
    if (missed.isNotEmpty) {
      out.add(flFold(context, '10 BIGGEST MISSED RALLIES', 'what b3 skipped', [
        for (final r in missed) flRow(context, '${flS(r['symbol'])} ${r['side'] == 1 ? 'LONG' : (r['side'] == -1 ? 'SHORT' : flS(r['side']))}', '${flS(r['when_utc'])}, ${flS(r['rule'])}, score ${flS(r['score'])}', flUsdt(r['would_usdt'])),
      ]));
    }
    if (flS(b['what_if_note']).isNotEmpty) out.add(Text(flS(b['what_if_note']), style: context.type.caption));
    return out;
  }
}
