part of 'dual_bot_screen.dart';

/// R19: the NOW tab cards of the Dual Bot screen (top strip, open trades, today, BTC, bot control). A 'part of' file: do NOT import it,
/// it is pulled in by dual_bot_screen.dart. Code moved unchanged from the old 957-line file.
extension _DualNowTab on _DualBotScreenState {
  Widget _statusCard(AppPalette p) {
    final state = '${_st['state'] ?? ''}';
    final running = state == 'running' || state == 'loading' || (state.isEmpty && _st['running'] == true);
    final enabled = _st['enabled'] != false;
    final progress = '${_st['progress'] ?? ''}';
    // One plain sentence from the backend (stopped / starting / busy / loading / running). Before the first reply: "Connecting...".
    final stateText = _st.isEmpty ? (_err.isEmpty ? 'Connecting...' : 'Cannot reach the backend') : '${_st['state_text'] ?? (running ? 'Running' : 'Starting up...')}';
    final dotColor = running ? p.profit : (state == 'busy' || state == 'starting' || _st.isEmpty ? p.warning : (state == 'error' ? p.loss : p.textMuted));
    final btcMargin = _n(_st['btc_margin']);
    final btcNote = btcMargin > 0 ? 'BTC is always included, with ${btcMargin.toStringAsFixed(0)} USDT per trade. ' : '';
    return _card(p, title: 'DUAL BOT (PAPER)', edge: p.accent, children: [
      Text(
          'Paper only: ${_n(_st['margin']).toStringAsFixed(0)} USDT per trade at ${_n(_st['lev']).toStringAsFixed(0)}x. '
          '$btcNote'
          'Your live bot is not touched.',
          style: context.type.metadata),
      const SizedBox(height: 8),
      Row(children: [
        Icon(Icons.circle, size: 10, color: dotColor),
        const SizedBox(width: 6),
        Expanded(
            child: Text(
                stateText,
                style: context.type.primary)),
        OutlinedButton(
          onPressed: _busy ? null : () => _toggle(!enabled),
          child: Text(enabled ? 'Stop' : 'Start'),
        ),
      ]),
      if (progress.isNotEmpty && enabled && state != 'busy') Padding(padding: const EdgeInsets.only(top: 6), child: Text(progress, style: context.type.metadata)),
      if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
    ]);
  }

  // ---- Today (same day as Dashboard: 5:30 AM IST to 5:30 AM IST) ----
  Widget _todayCard(AppPalette p) {
    final t = _map(_map(_st['summary'])['today']);
    if (t.isEmpty) return const SizedBox.shrink();
    final total = _n(t['total']);
    final up = total >= 0;
    return _card(p, title: 'DUAL BOT PAPER, TODAY (5:30 AM IST TO 5:30 AM IST)', edge: up ? p.profit : p.loss, children: [
      Text(_usdt(total), style: context.type.primary.copyWith(fontWeight: FontWeight.w900, fontSize: 24, color: up ? p.profit : p.loss)),
      Text('Dual Bot paper today: closed ${_usdt(_n(t['realized']))}, open ${_usdt(_n(t['open_pnl']))}', style: context.type.metadata),
      const SizedBox(height: 8),
      _kv('Opened today', '${t['opened'] ?? 0}'),
      _kv('Closed today', '${t['closed'] ?? 0}  (${t['wins'] ?? 0} won, ${t['losses'] ?? 0} lost)'),
      _kv('Open now', '${t['open'] ?? 0}  (${t['open_long'] ?? 0} long, ${((t['open'] ?? 0) as num) - ((t['open_long'] ?? 0) as num)} short)'),
      _kv('Skipped today (still followed)', '${t['skipped'] ?? 0}'),
    ]);
  }

  // ---- BTC (own margin, own totals - never added to the alt coins above) ----
  Widget _btcDualCard(AppPalette p) {
    final s = _map(_map(_st['summary'])['btc']);
    if (s.isEmpty) return const SizedBox.shrink();
    final t = _map(s['today']);
    final opened = _n(t['opened']).toInt();
    final closedN = _n(s['closed']).toInt();
    if (opened == 0 && closedN == 0 && _n(s['open']) == 0) return const SizedBox.shrink();
    final total = _n(t['total']);
    final up = total >= 0;
    final bm = _n(_st['btc_margin']);
    return _card(p, title: 'BTC ONLY (${bm > 0 ? bm.toStringAsFixed(0) : '1000'} USDT PER TRADE)', edge: up ? p.profit : p.loss, children: [
      Text(_usdt(total), style: context.type.primary.copyWith(fontWeight: FontWeight.w900, fontSize: 22, color: up ? p.profit : p.loss)),
      Text('Dual Bot paper, BTC only, today: closed ${_usdt(_n(t['realized']))}, open ${_usdt(_n(t['open_pnl']))}. Not part of the totals above.', style: context.type.metadata),
      const SizedBox(height: 8),
      _kv('Opened today', '${t['opened'] ?? 0}'),
      _kv('Closed today', '${t['closed'] ?? 0}  (${t['wins'] ?? 0} won, ${t['losses'] ?? 0} lost)'),
      _kv('All BTC trades', '$closedN finished, ${_usdt(_n(s['pnl']))}', color: _n(s['pnl']) >= 0 ? p.profit : p.loss),
    ]);
  }

  Color _verdictColor(AppPalette p, String v) => v == 'USE' ? p.profit : (v == 'SKIP' ? p.loss : p.textMuted);

  /// One short line: what this trade's setup did before.
  Widget _setupLine(AppPalette p, Map stp) {
    final n = (stp['n'] is num) ? (stp['n'] as num).toInt() : 0;
    final v = '${stp['verdict'] ?? ''}';
    if (n == 0) return Text('Setup: new, the bot never saw this picture before.', style: context.type.metadata);
    final avg = _n(stp['avg']);
    final word = v == 'USE' ? 'good setup' : (v == 'SKIP' ? 'bad setup' : (v == 'FEW' ? 'too few to judge' : 'not clear'));
    return Text('Setup: $n old trades, ${stp['win']}% won, avg ${avg >= 0 ? '+' : ''}${avg.toStringAsFixed(1)}%  ($word)',
        style: context.type.metadata.copyWith(fontWeight: FontWeight.w700, color: _verdictColor(p, v)));
  }

  Map<String, dynamic>? _brainOf(Map<String, dynamic> t) {
    final o = _brainIds['${t['s']}|${t['f']}|${t['t']}'];
    return o is Map ? Map<String, dynamic>.from(o) : null;
  }

  /// Now tab filter: All / Good only (Brain clean score 70+) / Long / Short.
  bool _passFilter(Map<String, dynamic> t) {
    switch (_filter) {
      case 1:
        return DualTradeCard.quality(_brainOf(t)) == 'good';
      case 2:
        return (t['d'] ?? 1) > 0;
      case 3:
        return (t['d'] ?? 1) < 0;
      default:
        return true;
    }
  }

  Widget _filterRow(AppPalette p, int total, int shown) {
    const names = ['All', 'Good only', 'Long', 'Short'];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(children: [
            for (var i = 0; i < names.length; i++)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ChoiceChip(
                  label: Text(names[i], style: const TextStyle(fontSize: 12)),
                  visualDensity: VisualDensity.compact,
                  selected: _filter == i,
                  onSelected: (_) => _setFilter(i),
                ),
              ),
          ]),
        ),
        if (_filter != 0) Text('Showing $shown of $total open trades.', style: context.type.metadata),
      ]),
    );
  }

  Widget _stripCard(AppPalette p) {
    final state = '${_st['state'] ?? ''}';
    final running = state == 'running' || state == 'loading' || (state.isEmpty && _st['running'] == true);
    final stateText = _st.isEmpty ? (_err.isEmpty ? 'Connecting...' : 'Cannot reach the backend') : '${_st['state_text'] ?? 'Starting up...'}';
    return DualSummaryStrip(
      running: running,
      learned: '${_map(_st['model'])['mode']}' == 'LEARNED',
      stateText: stateText,
      trust: _brainTrust,
      today: _map(_map(_st['summary'])['today']),
      open: _maps(_st['recent']).where((t) => '${t['status']}' == 'open').toList(),
      brain: _brainIds,
    );
  }

  Widget _openCard(AppPalette p) {
    final allOpen = _maps(_st['recent']).where((t) => '${t['status']}' == 'open').toList();
    final open = allOpen.where(_passFilter).toList();
    final nMain = open.where((t) => '${t['src']}' == 'MAIN').length;
    final nZ = open.where((t) => '${t['src']}' == 'Z').length;
    final nBoth = open.where((t) => '${t['src']}' == 'BOTH').length;
    return _card(p, title: 'OPEN TRADES (LIVE)', edge: open.isEmpty ? null : p.profit, children: [
      if (allOpen.isNotEmpty) _filterRow(p, allOpen.length, open.length),
      if (allOpen.isEmpty) Text('No open trade right now. Tap any trade below to see its chart.', style: context.type.secondary),
      if (allOpen.isNotEmpty && open.isEmpty) Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('No open trade matches this filter.', style: context.type.secondary)),
      if (open.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Text(
            'Entry from: $nMain Main, $nZ Z${nBoth > 0 ? ', $nBoth both' : ''}',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13),
          ),
        ),
      for (final t in open)
        DualTradeCard(
          row: t,
          margin: _mg(t),
          onTap: () => showDualTradeChart(context, row: t, margin: _mg(t), lev: _n(_st['lev'])),
          setupLine: t['stp'] is Map ? _setupLine(p, t['stp'] as Map) : null,
          brain: _brainIds['${t['s']}|${t['f']}|${t['t']}'] is Map ? Map<String, dynamic>.from(_brainIds['${t['s']}|${t['f']}|${t['t']}'] as Map) : null,
        ),
      if (open.isNotEmpty) Text('Tap a card: big chart with entry, stop and take-profit lines. Scroll and zoom like the Positions tab.', style: context.type.metadata),
    ]);
  }
}
