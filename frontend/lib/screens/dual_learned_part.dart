part of 'dual_bot_screen.dart';

/// R19: the 'What it learned' cards (daily review, setups, retest, scenarios, lessons, model). A 'part of' file: do NOT import it.
/// Code moved unchanged from the old 957-line file.
extension _DualLearnedTab on _DualBotScreenState {
  Widget _modelCard(AppPalette p) {
    final m = _map(_st['model']);
    final rows = '${_st['rows'] ?? 0}';
    if (m.isEmpty) {
      return _card(p, title: 'WHAT IT HAS LEARNED', children: [
        Text('Still reading history ($rows situations so far). It needs about 150 before it starts to learn.', style: context.type.secondary),
      ]);
    }
    final learned = m['mode'] == 'LEARNED';
    final v = _map(m['val']);
    return _card(p, title: 'WHAT IT HAS LEARNED', edge: learned ? p.profit : p.warning,
        headline: learned ? 'LEARNED: its choice ${_n(v['taken_avg']).toStringAsFixed(2)}% vs take-all ${_n(v['all_avg']).toStringAsFixed(2)}% per trade' : 'STILL EXPLORING: it takes every signal and keeps learning',
        headlineColor: learned ? p.profit : p.warning, children: [
      Text(learned ? 'LEARNED' : 'STILL EXPLORING', style: context.type.section.copyWith(color: learned ? p.profit : p.warning, fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text(
          learned
              ? 'On newer data it had never seen, the signals it chose earned more than taking every signal, and more than luck gives. It now skips signals it expects to lose.'
              : 'It has not yet beaten "take every signal" on new data (checked against luck). So it takes every signal and keeps learning. This is normal at the start.',
          style: context.type.secondary),
      const SizedBox(height: 8),
      _kv('Situations remembered', rows),
      _kv('Signals it would take (new data)', '${v['taken'] ?? 0} of ${v['test'] ?? 0}'),
      _kv('Average per trade, its choice', '${_n(v['taken_avg']).toStringAsFixed(2)} ROI%'),
      _kv('Average per trade, take everything', '${_n(v['all_avg']).toStringAsFixed(2)} ROI%'),
      _kv('Luck check (best shuffle gain)', '${_n(v['luck_max']).toStringAsFixed(2)} ROI%'),
      _kv('Exit that earned most overall', '${m['best_exit'] ?? '-'}'),
    ]);
  }

  // ---- Daily review: the bot trades a full day first, then looks back ----
  Widget _reviewRow(AppPalette p, Map<String, dynamic> r) {
    final prev = r['prev'];
    final again = prev is num && prev < 0;
    final net = _n(r['net']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['name']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.3)),
        Text('${r['n']} trades, ${r['won']} won. Result ${_usdt(_n(r['pnl']))}.', style: context.type.metadata),
        Text(
            'If skipped: saved ${_n(r['saved']).toStringAsFixed(2)} USDT of losses, missed ${_n(r['missed']).toStringAsFixed(2)} USDT of profit. '
            'Net ${_usdt(net)}.',
            style: context.type.metadata.copyWith(height: 1.35, fontWeight: FontWeight.w700, color: net >= 0 ? p.profit : p.loss)),
        if (prev is num) Text(again ? 'Also bad the day before (${_usdt(prev.toDouble())}).' : 'Day before it was fine (${_usdt(prev.toDouble())}).', style: context.type.metadata),
      ]),
    );
  }

  Widget _reviewCard(AppPalette p) {
    final r = _map(_st['review']);
    if (r['status'] != 'ready') {
      return _card(p, title: 'DAILY REVIEW', children: [
        Text(
            'The bot trades every signal for one full day first. The review of that day comes after 5:30 AM IST, '
            'when the day is complete. It will show which scenarios to skip and what that would have saved.',
            style: context.type.secondary),
        Text('Last full day (${r['day'] ?? '-'}): ${r['n'] ?? 0} finished trades so far. It needs 10.', style: context.type.metadata),
      ]);
    }
    final bad = _maps(r['bad']);
    final good = _maps(r['good']);
    final c = _map(r['combo']);
    final wc = _n(c['with']) >= _n(c['without']) ? p.profit : p.loss;
    return _card(p, title: 'DAILY REVIEW (${r['day']})', edge: p.accent,
        headline: bad.isEmpty ? 'Day ${r['day']}: ${_usdt(_n(r['pnl']))}, no clear losing scenario' : 'Skipping the losers: ${_usdt(_n(c['with']))} instead of ${_usdt(_n(c['without']))}',
        headlineColor: bad.isEmpty ? null : wc,
        children: [
      Text('That day: ${r['n']} trades, ${r['won']} won, result ${_usdt(_n(r['pnl']))}.',
          style: context.type.primary.copyWith(fontWeight: FontWeight.w800, height: 1.3)),
      if (_n(r['open_left']) > 0) Text('${r['open_left']} trade(s) from that day are still open and not counted.', style: context.type.metadata),
      const SizedBox(height: 8),
      Text('Scenarios that lost (skip candidates)', style: context.type.label),
      const SizedBox(height: 4),
      if (bad.isEmpty) Text('No scenario lost clearly that day.', style: context.type.secondary),
      for (final b in bad) _reviewRow(p, b),
      if (bad.isNotEmpty)
        Text(
            'Skip all of these together: ${c['skipped']} trades skipped, the day would be ${_usdt(_n(c['with']))} instead of ${_usdt(_n(c['without']))}.',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w800, height: 1.35, color: _n(c['with']) >= _n(c['without']) ? p.profit : p.loss)),
      if (good.isNotEmpty) ...[
        const SizedBox(height: 10),
        Text('Scenarios that earned (keep)', style: context.type.label),
        const SizedBox(height: 4),
        for (final g in good)
          Text('${g['name']}: ${g['n']} trades, ${_usdt(_n(g['pnl']))}', style: context.type.metadata.copyWith(height: 1.4, color: p.profit)),
      ],
      const SizedBox(height: 8),
      Text('One day is a hint, not proof. Trust a skip only if the same scenario is bad again on the next days.', style: context.type.metadata),
    ]);
  }

  Widget _scenCard(AppPalette p) {
    final sc = _map(_st['scen']);
    final cards = _maps(sc['cards']);
    if (sc['status'] != 'ready' || cards.isEmpty) return const SizedBox.shrink();
    final nUse = cards.where((c) => c['verdict'] == 'USE').length;
    final nSkip = cards.where((c) => c['verdict'] == 'SKIP').length;
    return _card(p, title: 'SCENARIOS (HOW OFTEN, HOW LONG, HOW MUCH)', headline: '${cards.length} scenarios  ·  $nUse to use  ·  $nSkip to skip', children: [
      for (final c in cards)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                    color: (c['verdict'] == 'USE' ? p.profit : p.loss).withOpacity(0.18), borderRadius: BorderRadius.circular(6)),
                child: Text('${c['verdict']}',
                    style: context.type.metadata.copyWith(fontWeight: FontWeight.w800, color: c['verdict'] == 'USE' ? p.profit : p.loss)),
              ),
              const SizedBox(width: 8),
              Expanded(child: Text('${c['name']}', style: context.type.primary.copyWith(height: 1.3))),
            ]),
            const SizedBox(height: 2),
            Text(
                'Seen ${c['per_day']} times a day (${c['n']} trades). Takes about ${fmtMins(c['mins'])} with "${c['best_exit']}". '
                'Best exit: ${_n(c['best_avg']).toStringAsFixed(1)}% per trade, ${c['best_win']}% win. '
                'Bot exit: ${_n(c['bot_avg']).toStringAsFixed(1)}% per trade, ${c['bot_win']}% win.',
                style: context.type.metadata.copyWith(height: 1.35)),
          ]),
        ),
    ]);
  }

  Widget _setupRows(AppPalette p, List<Map<String, dynamic>> list) {
    if (list.isEmpty) return Padding(padding: const EdgeInsets.only(bottom: 8), child: Text('None yet.', style: context.type.metadata));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final c in list)
        Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${c['name']}', style: context.type.primary.copyWith(height: 1.3, fontSize: 13)),
            Text(
                '${c['n']} trades, seen ${c['per_day']}x a day. Bot exit: ${c['bot_win']}% won, avg ${_n(c['bot_avg']).toStringAsFixed(1)}%. '
                'Best exit "${c['best_exit']}": ${c['best_win']}% won, avg ${_n(c['best_avg']).toStringAsFixed(1)}%, about ${fmtMins(c['mins'])}.',
                style: context.type.metadata.copyWith(height: 1.35, color: _verdictColor(p, '${c['verdict']}'))),
          ]),
        ),
    ]);
  }

  Widget _setupCard(AppPalette p) {
    final sb = _map(_st['setups']);
    final tot = _map(sb['totals']);
    if (sb['status'] != 'ready') {
      return _card(p, title: 'SETUPS (BOTH INDICATORS TOGETHER)', children: [
        Text(
            'Collecting. It needs about 2 days of data before it can group the trades into setups. '
            '${_n(sb['days']) > 0 ? 'So far: ${_n(sb['days']).toStringAsFixed(1)} days.' : ''}',
            style: context.type.secondary),
      ]);
    }
    return _card(p, title: 'SETUPS (BOTH INDICATORS TOGETHER)', edge: p.accent, headline: '${tot['use']} good  ·  ${tot['skip']} bad  ·  ${tot['seen']} setups seen', children: [
      Text('${tot['seen']} different setups seen', style: context.type.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 15)),
      const SizedBox(height: 2),
      Text(
          '${tot['judged']} have 10+ trades and are judged: ${tot['use']} good, ${tot['skip']} bad, ${tot['unsure']} not clear. '
          '${tot['few']} have too few trades yet.',
          style: context.type.metadata.copyWith(height: 1.4)),
      Text('A setup is the full picture at the entry: who signalled, TSI vs zero, TSI vs its line, TSI histogram, Z candle vs its EMAs, '
          'Z cloud, Z vs ZSM, and price vs Z. Buy and sell with the same picture count together.',
          style: context.type.metadata.copyWith(height: 1.4)),
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: Column(children: [
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Most common setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['common']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Good setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: p.profit)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['use']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Bad setups', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: p.loss)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_setupRows(p, _maps(sb['skip']))],
          ),
        ]),
      ),
      Text('Found by counting. Good = the best exit earns in the older and the newer data. Bad = the bot exit loses in both.', style: context.type.metadata),
    ]);
  }

  Widget _lessonsCard(AppPalette p) {
    final l = _map(_st['lessons']);
    final closed = (l['closed'] ?? 0) as num;
    if (closed == 0) {
      return _card(p, title: 'LESSONS FROM MISTAKES', children: [
        Text('No finished trade yet. After each finished trade the bot marks it REAL or FAKE and remembers why.', style: context.type.secondary),
      ]);
    }
    final rep = _map(l['repeat']);
    final warned = (rep['warned'] ?? 0) as num;
    final free = (rep['not_warned'] ?? 0) as num;
    final reasons = _maps(l['top_reasons']);
    return _card(p, title: 'LESSONS FROM MISTAKES', headline: '${l['fake'] ?? 0} fake  ·  ${l['real'] ?? 0} real  ·  $closed finished', children: [
      _kv('Finished trades', '$closed'),
      _kv('Fake signals', '${l['fake'] ?? 0}', color: p.loss),
      _kv('Real moves', '${l['real'] ?? 0}', color: p.profit),
      if (reasons.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text('Why signals turned out fake', style: context.type.label),
        for (final r in reasons) Text('${r['n']}x  ${r['reason']}', style: context.type.metadata.copyWith(height: 1.4)),
      ],
      const SizedBox(height: 6),
      Text('Old-mistake warning check', style: context.type.label),
      Text(
          warned == 0
              ? 'No trade looked like an old mistake yet.'
              : 'Looked like an old mistake: ${rep['warned_lost']} of $warned lost. '
                  'Did not look like one: ${rep['not_warned_lost']} of $free lost.',
          style: context.type.metadata.copyWith(height: 1.4)),
    ]);
  }

  // ---- Retest check: what if we had waited for the price to come back to the EMA? ----
  Widget _retestRow(AppPalette p, Map<String, dynamic> b, {String? title}) {
    final gain = _n(b['gain']);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title ?? '${b['name']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.3)),
        Text(
            '${b['n']} signals: ${b['entered']} came back and would have entered, ${b['missed']} never came back. '
            'Entering at the signal: ${_usdt(_n(b['now_all']))}. Waiting for the retest: ${_usdt(_n(b['retest']))}.',
            style: context.type.metadata.copyWith(height: 1.35)),
        Text('Waiting is ${gain >= 0 ? 'better' : 'worse'} by ${_usdt(gain)}.',
            style: context.type.metadata.copyWith(fontWeight: FontWeight.w800, color: gain >= 0 ? p.profit : p.loss)),
      ]),
    );
  }

  Widget _retestCard(AppPalette p) {
    final r = _map(_st['retest']);
    if (r['status'] != 'ok') {
      return _card(p, title: 'RETEST CHECK', children: [
        Text(
            'For every signal the bot also measures: what if I had waited for the price to come back to the EMA, and entered there? '
            'It needs more finished signals first (${r['n'] ?? 0} so far, it needs 10).',
            style: context.type.secondary),
      ]);
    }
    final missedNow = _n(r['now_missed']);
    final tsi = _maps(r['tsi']);
    final extra = _n(r['extra_on_entered']);
    return _card(p, title: 'RETEST CHECK (WAIT FOR PRICE TO COME BACK TO THE EMA)', edge: p.accent,
        headline: 'Entering after a retest: ${_usdt(extra)} vs the signal entry', headlineColor: extra >= 0 ? p.profit : p.loss, children: [
      Text('Same stop, same targets, same exit. Only the entry changes: wait for a pullback to the EMA50. The bot measures 3, 6, 12 and 24 candles at once and shows the best.', style: context.type.metadata),
      const SizedBox(height: 8),
      _retestRow(p, r, title: 'All signals, best wait: ${r['wait']} candles'),
      for (final w in _maps(r['waits']))
        Text('Wait ${w['wait']} candles: ${w['entered']} enter, ${w['missed']} never come back, ${_n(w['gain']) >= 0 ? 'better' : 'worse'} by ${_usdt(_n(w['gain']))}', style: context.type.metadata),
      const SizedBox(height: 8),
      Text(
          'Trades that entered after a retest made ${_usdt(_n(r['extra_on_entered']))} more than the same trades entered at the signal. '
          'The ${r['missed']} trades that never came back would have made ${_usdt(missedNow)} if taken at the signal '
          '(${missedNow >= 0 ? 'profit you would have missed' : 'losses you would have avoided'}).',
          style: context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.35, fontSize: 13)),
      if (tsi.isNotEmpty) ...[
        const SizedBox(height: 10),
        Text('Does TSI change the answer?', style: context.type.label),
        const SizedBox(height: 4),
        for (final b in tsi) _retestRow(p, b),
      ],
      Text('This only measures. The bot still enters at the signal.', style: context.type.metadata),
    ]);
  }
}
