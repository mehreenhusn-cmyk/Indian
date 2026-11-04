part of 'dual_bot_screen.dart';

/// R19: the PERFORMANCE tab cards (results, situations, recent trades, how to read, report). A 'part of' file: do NOT import it.
/// Code moved unchanged from the old 957-line file.
extension _DualPerfTab on _DualBotScreenState {
  Widget _resultCard(AppPalette p) {
    final s = _map(_st['summary']);
    final closed = (s['closed'] ?? 0) as num;
    final wins = (s['wins'] ?? 0) as num;
    final pnl = _n(s['pnl']);
    final skipped = _n(s['skipped_pnl']);
    final bySrc = _map(s['by_src']);
    const names = {'MAIN': 'Main chart signal (your bot)', 'Z': 'Z black candle only', 'BOTH': 'Both on the same candle'};
    return _card(p, title: 'LIVE PAPER RESULT', children: [
      _kv('Finished trades', '$closed'),
      _kv('Win rate', closed > 0 ? '${(100 * wins / closed).toStringAsFixed(0)}%' : '-'),
      _kv('Profit / loss', _usdt(pnl), color: pnl >= 0 ? p.profit : p.loss),
      _kv('Open now', '${s['open'] ?? 0}  (${_usdt(_n(s['open_pnl']))})'),
      const SizedBox(height: 4),
      Text('Skipped signals (still followed)', style: context.type.label),
      const SizedBox(height: 2),
      Text(
          (s['skipped_done'] ?? 0) == 0
              ? 'None finished yet.'
              : '${s['skipped_done']} finished. They would have made ${_usdt(skipped)}. '
                  '${skipped < 0 ? 'So skipping them saved money.' : 'So skipping them cost profit.'}',
          style: context.type.secondary),
      if (bySrc.isNotEmpty) ...[
        const SizedBox(height: 8),
        Text('By signal type', style: context.type.label),
        const SizedBox(height: 2),
        for (final e in bySrc.entries)
          _kv('${names[e.key] ?? e.key}', '${_map(e.value)['n']} trades, ${_usdt(_n(_map(e.value)['pnl']))}',
              color: _n(_map(e.value)['pnl']) >= 0 ? p.profit : p.loss),
      ],
    ]);
  }

  Widget _insightRows(AppPalette p, List<Map<String, dynamic>> l) {
    if (l.isEmpty) return Text('Not enough history yet.', style: context.type.secondary);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final g in l)
          Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${g['name']}', style: context.type.primary.copyWith(height: 1.3)),
              Text(
                  '${g['n']} trades. Best exit "${g['exit']}": ${_n(g['best']).toStringAsFixed(1)} ROI% per trade. '
                  'Bot exit: ${_n(g['bot']).toStringAsFixed(1)}. ${g['both_halves'] == true ? 'Positive in older and newer data.' : 'Not proven in both halves.'}',
                  style: context.type.metadata),
            ]),
          ),
      ],
    );
  }

  Widget _situationsCard(AppPalette p) {
    final ins = _map(_st['insights']);
    return _card(p, title: 'SITUATIONS (FOUND BY THE BOT, NOT TYPED BY YOU)', children: [
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: Column(children: [
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Best situations', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_insightRows(p, _maps(ins['best']))],
          ),
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: Text('Worst situations', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            expandedCrossAxisAlignment: CrossAxisAlignment.start,
            children: [_insightRows(p, _maps(ins['worst']))],
          ),
        ]),
      ),
      Text('Plain counting on old replays, fee inside. A situation is only strong if it is positive in both older and newer data.',
          style: context.type.metadata),
    ]);
  }

  Widget _tradeRow(AppPalette p, Map<String, dynamic> t, {bool short = false}) {
    final status = '${t['status']}';
    final long = (t['d'] ?? 1) > 0;
    double? net;
    String tag;
    switch (status) {
      case 'closed':
        net = t['net'] is num ? (t['net'] as num).toDouble() : null;
        tag = '${t['end'] ?? 'done'}';
        break;
      case 'open':
        final liveV = t['live_now'] is num ? t['live_now'] : t['live'];            // price of right now, else of the last closed candle
        net = liveV is num ? liveV.toDouble() : null;
        tag = 'open, live';
        break;
      case 'skipped_done':
        net = t['net'] is num ? (t['net'] as num).toDouble() : null;
        tag = 'skipped, would be';
        break;
      case 'skipped':
        tag = 'skipped';
        break;
      default:
        tag = status;
    }
    final usdt = net == null ? null : net * _mg(t) / 100.0;
    final path = t['path'] is List ? (t['path'] as List).length : 0;
    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: () => showDualTradeChart(context, row: t, margin: _mg(t), lev: _n(_st['lev'])),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Icon(long ? Icons.arrow_upward : Icons.arrow_downward, size: 16, color: long ? p.profit : p.loss),
          const SizedBox(width: 6),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${t['s']} ${t['f']}  ${long ? 'LONG' : 'SHORT'}  (${t['src']})', style: context.type.primary),
              Text('$tag. Exit: ${t['exit']}${path > 0 ? '. Stop moved $path×' : ''}', style: context.type.metadata),
              if (!short && '${t['what1'] ?? ''}'.isNotEmpty) Text('${t['what1']}', style: context.type.metadata.copyWith(height: 1.3)),
              if (!short && (t['label'] == 'real' || t['label'] == 'fake'))
                Text('${t['label'] == 'fake' ? 'FAKE' : 'REAL'}: ${t['reason'] ?? ''}',
                    style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: t['label'] == 'fake' ? p.loss : p.profit)),
              if (!short && t['side'] is List && (t['side'] as List).length == 2 && (t['side'] as List)[0] is num)
                Text('Sideways: main chart ${(t['side'] as List)[0]}%, Z pane ${(t['side'] as List)[1]}%', style: context.type.metadata),
              if (t['stp'] is Map) _setupLine(p, t['stp'] as Map),
              if (!short && t['mem'] is Map && '${(t['mem'] as Map)['text'] ?? ''}'.isNotEmpty)
                Text('${(t['mem'] as Map)['text']}', style: context.type.metadata.copyWith(height: 1.3)),
            ]),
          ),
          if (usdt != null)
            Text(_usdt(usdt), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: usdt >= 0 ? p.profit : p.loss)),
          Icon(Icons.chevron_right, size: 18, color: p.textMuted),
        ]),
      ),
    );
  }

  void _openReport() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const Padding(
        padding: EdgeInsets.all(12),
        child: SafeArea(
          child: ReportDownloadCard(
            title: 'Dual Bot report',
            description:
                'One text file for any AI: what the Dual Bot is, every trade with its stop steps, exit and situation, the retest check, TSI split, setups, lessons and totals. Send it to any AI and ask what to improve.',
            textPath: '/api/dual_lab/report',
            savePath: '/api/dual_lab/report_save',
          ),
        ),
      ),
    );
  }

  Widget _recentCard(AppPalette p) {
    final recent = _maps(_st['recent']).where((t) => '${t['status']}' != 'open').toList();
    return _card(p, title: 'LATEST SIGNALS (FINISHED AND SKIPPED)', children: [
      if (recent.isEmpty) Text('No signal yet. New ones appear after each candle closes (5m and 15m).', style: context.type.secondary),
      for (final t in recent.take(25)) _tradeRow(p, t),
    ]);
  }

  Widget _howToReadCard(AppPalette p) {
    const exits = [
      'Bot exit: TP4, or the main chart turns',
      'TP4, or the Z black candle turns',
      'All closed at TP1',
      'All closed at TP2',
      'No limit, leaves when the main chart turns',
      'No limit, leaves at the Z black candle',
      'No limit, trailing stop 1.5R',
      'No limit, trailing stop 3R',
      'Closed after 12 candles',
    ];
    return _card(p, title: 'HOW TO READ THIS', children: [
      Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text('Tap here to read', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
                'Every signal is a paper trade. The bot looks at both indicators, takes the trade, and checks how 9 different exits would have done. '
                'Entry and first stop are always the same: the stop is the low (buy) or high (sell) of the signal candle. '
                'Tap a trade to see it on the chart: blue triangle = in, orange steps = where the stop moved, green lines = take-profit levels, dot = out.',
                style: context.type.secondary.copyWith(height: 1.35)),
            const SizedBox(height: 8),
            Text('The 9 exits it tests', style: context.type.label),
            const SizedBox(height: 2),
            for (var k = 0; k < exits.length; k++) Text('${k + 1}. ${exits[k]}', style: context.type.metadata.copyWith(height: 1.4)),
            const SizedBox(height: 6),
            Text('R = the distance from entry to the first stop. Fee is already inside every result.', style: context.type.metadata),
          ],
        ),
      ),
    ]);
  }
}
