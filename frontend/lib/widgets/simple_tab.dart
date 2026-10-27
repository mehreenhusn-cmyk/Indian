import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'dual_trade_card.dart';
import 'owl_card.dart';
import 'owl_status_pill.dart';
import 'universe_strip.dart';

/// Dual Bot "Simple" tab: the whole picture in 5 small blocks, no jargon. Block 0: Locked / Floating / Net + Brain dislike %.
/// 1) Is the bot OK today (one colour, one sentence)  2) open trades, one line each, tap = chart
/// 3) best and worst finished trades  4) one line about what the sideways market cost.
/// Only shows numbers the screen already has. Nothing here trades or changes anything.
class SimpleTab extends StatefulWidget {
  final Map<String, dynamic> today; // summary.today from /api/dual_lab
  final List<Map<String, dynamic>> recent; // open + latest finished trades
  final Map<String, dynamic> brainIds; // Brain opinion per trade key (coin|timeframe|time)
  final Map<String, dynamic> sideways; // Brain's sideways report (may be empty)
  final Map<String, dynamic> bySrc; // summary.by_src from /api/dual_lab: finished trades by signal type (alt coins)
  final Map<String, dynamic> desk; // /api/dual_desk (today vs last 7 days coins, Z2b)
  final Map<String, dynamic> archive; // /api/archive (DATA SAFE chip, Z2c)
  final double Function(Map<String, dynamic>) marginOf;
  final void Function(Map<String, dynamic>) onOpen;

  const SimpleTab({
    super.key,
    required this.today,
    required this.recent,
    required this.brainIds,
    required this.sideways,
    this.bySrc = const {},
    this.desk = const {},
    this.archive = const {},
    required this.marginOf,
    required this.onOpen,
  });

  @override
  State<SimpleTab> createState() => _SimpleTabState();
}

class _SimpleTabState extends State<SimpleTab> {
  bool _all = false;
  int _flt = 0; // open list filter: 0 All, 1 Today, 2 7d, 3 Long, 4 Short (Z2c)
  static const _fltNames = ['All', 'Today', '7d', 'Long', 'Short'];
  static const _showFirst = 12;
  static const _tab = [FontFeature.tabularFigures()];

  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';
  static String _coin(dynamic s) => '$s'.replaceAll('USDT', '');

  double _openUsdt(Map<String, dynamic> t) {
    final roi = t['live_now'] is num ? _n(t['live_now']) : _n(t['live']);
    return widget.marginOf(t) * roi / 100.0;
  }

  /// Where the coin came from: 'today' (top list now, BTC too) or 'd7' (only a 7-day name). Empty = unknown (old trade).
  String _from(Map<String, dynamic> t) {
    if ('${t['s']}' == 'BTCUSDT') return 'today';
    final tags = widget.desk['tags'];
    return tags is Map ? '${tags['${t['s']}'] ?? ''}' : '';
  }

  bool _keep(Map<String, dynamic> t) {
    switch (_flt) {
      case 1:
        return _from(t) == 'today';
      case 2:
        return _from(t) == 'd7';
      case 3:
        return _n(t['d']) > 0;
      case 4:
        return _n(t['d']) < 0;
      default:
        return true;
    }
  }

  Map<String, dynamic>? _brain(Map<String, dynamic> t) {
    final o = widget.brainIds['${t['s']}|${t['f']}|${t['t']}'];
    return o is Map ? Map<String, dynamic>.from(o) : null;
  }

  /// UI2a: today's money. ONE hero number (NET = locked + floating) with a status chip, LOCKED and FLOATING smaller below,
  /// and the Brain dislike line. Same numbers as before, only the hierarchy changed.
  Widget _threeBoxes(AppPalette p) {
    final td = widget.today;
    if (td.isEmpty) return const SizedBox.shrink();
    final total = _n(td['total']);
    final locked = td.containsKey('realized') ? _n(td['realized']) : total;
    final floating = _n(td['open_pnl']);
    final v = _verdict(p);
    var rated = 0, bad = 0, badDone = 0;
    double badUsdt = 0;
    for (final t in widget.recent) {
      final o = _brain(t);
      if (o == null) continue;
      rated++;
      if (DualTradeCard.quality(o) == 'bad') {
        bad++;
        if ('${t['status']}' == 'closed' && t['net'] is num) {
          badDone++;
          badUsdt += _n(t['net']) * widget.marginOf(t) / 100.0;
        }
      }
    }
    Widget small(String label, double val, String note) => Expanded(
          child: Container(
            margin: const EdgeInsets.symmetric(horizontal: 3),
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 10),
            decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(10)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: AppTypography.eyebrow.copyWith(color: p.textMuted, fontSize: 9.5)),
              const SizedBox(height: 3),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(_sg(val), maxLines: 1, style: AppTypography.numberLarge.copyWith(color: val >= 0 ? p.profit : p.loss)),
              ),
              const SizedBox(height: 1),
              Text(note, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata),
            ]),
          ),
        );
    return OwlSectionCard(
      title: 'TODAY IN USDT',
      hint: '5:30 AM IST to 5:30 AM IST',
      edge: total >= 0 ? p.profit : p.loss,
      trailing: OWLStatusPill(text: v.shortHead.toUpperCase(), color: v.c),
      children: [
        OwlHero(label: 'NET (LOCKED + FLOATING)', value: total),
        const SizedBox(height: AppSpacing.m),
        Row(children: [
          small('LOCKED', locked, 'closed, final'),
          small('FLOATING', floating, 'open, can change'),
        ]),
        if (rated > 0) ...[
          const SizedBox(height: 8),
          Text('Brain dislikes ${(100 * bad / rated).round()}% of the latest $rated trades.', style: context.type.primary),
          if (badDone > 0)
            Text('The disliked ones that finished made ${_sg(badUsdt)} USDT ($badDone trades).', style: context.type.secondary),
        ],
      ],
    );
  }

  /// One verdict for the day, used by the chip on the hero card and the sentence in IS THE BOT OK?.
  _V _verdict(AppPalette p) {
    final td = widget.today;
    final closed = _n(td['closed']).toInt();
    final locked = td.containsKey('realized') ? _n(td['realized']) : _n(td['total']);
    final floating = _n(td['open_pnl']);
    final total = _n(td['total']);
    if (closed < 20) return _V(p.textMuted, 'Too early to say', 'Too early', 'Only $closed trades have closed today. Check again later.');
    if (locked >= 0) return _V(p.profit, 'Looking fine', 'Looking fine', 'Closed trades are in profit today (${_sg(locked)} USDT locked in).');
    if (total >= 0) {
      return _V(p.warning, 'Careful, not locked in', 'Careful',
          'Closed trades lost ${_sg(locked)} USDT. The open trades are floating ${_sg(floating)} USDT, but that can still disappear.');
    }
    return _V(p.loss, 'Losing today', 'Losing', 'Closed trades ${_sg(locked)} USDT, open trades ${_sg(floating)} USDT. Total ${_sg(total)} USDT.');
  }

  Widget _health(AppPalette p) {
    final td = widget.today;
    final closed = _n(td['closed']).toInt();
    final wins = _n(td['wins']).toInt();
    final nOpen = _n(td['open']).toInt();
    final winPct = closed > 0 ? (100 * wins / closed).round() : null;
    final v = _verdict(p);

    final sw = widget.sideways;
    final cost = sw['cost'];
    final swLine = ('${sw['status']}' == 'ready' && cost is num)
        ? 'Sideways markets have cost ${cost.toStringAsFixed(2)} USDT so far (see Brain tab for details).'
        : '';

    // The verdict word itself is the chip on the hero card; here only the plain sentence + counts.
    return OwlSectionCard(title: 'IS THE BOT OK?', edge: v.c, children: [
      Text(v.why, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 6),
      Text(
        closed == 0
            ? 'No trade has closed today yet.'
            : '$closed closed today, ${winPct ?? 0}% won. $nOpen trades are open right now.',
        style: context.type.secondary,
      ),
      if (swLine.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(swLine, style: context.type.secondary)),
    ]);
  }

  /// Finished trades by signal type: both indicators on the same candle versus one indicator alone (alt coins, closed trades only).
  Widget _signalTypeCard(AppPalette p) {
    if (widget.bySrc.isEmpty) return const SizedBox.shrink();
    const names = {'BOTH': 'Both on the same candle', 'Z': 'Z black candle only', 'MAIN': 'Main chart only'};
    final rows = <Widget>[];
    String? bestName;
    double bestPnl = 0;
    for (final k in const ['BOTH', 'Z', 'MAIN']) {
      final v = widget.bySrc[k];
      if (v is! Map) continue;
      final n = _n(v['n']).toInt();
      final w = _n(v['wins']).toInt();
      final pnl = _n(v['pnl']);
      if (n > 0 && (bestName == null || pnl > bestPnl)) {
        bestName = names[k] ?? k;
        bestPnl = pnl;
      }
      rows.add(Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(names[k] ?? k, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
              Text(n == 0 ? 'no finished trade yet' : '$n trades, ${(100 * w / n).round()}% won', style: context.type.metadata),
            ]),
          ),
          if (n > 0) Text('${_sg(pnl)} USDT', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: pnl >= 0 ? p.profit : p.loss, fontFeatures: _tab)),
        ]),
      ));
    }
    if (rows.isEmpty) return const SizedBox.shrink();
    return OwlFold(title: 'WHICH SIGNAL TYPE PAYS (FINISHED TRADES)', headline: bestName == null ? 'No finished trade yet' : 'Best: $bestName ${_sg(bestPnl)} USDT', headlineColor: bestName == null ? null : (bestPnl >= 0 ? p.profit : p.loss), children: [
      ...rows,
      Text('Closed trades only, alt coins. Open trades are not counted here.', style: context.type.metadata),
    ]);
  }

  Widget _openRow(AppPalette p, Map<String, dynamic> t) {
    final buy = _n(t['d']) > 0;
    final u = _openUsdt(t);
    final g = DualTradeCard.quality(_brain(t));
    final dot = g == 'good' ? p.profit : (g == 'bad' ? p.loss : p.border);
    final src = '${t['src'] ?? ''}';
    return InkWell(
      onTap: () => widget.onOpen(t),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(children: [
          Icon(Icons.circle, size: 9, color: dot),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(_coin(t['s']), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w800))),
                const SizedBox(width: 6),
                Text(buy ? 'BUY' : 'SELL', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: buy ? p.profit : p.loss)),
                if (_from(t).isNotEmpty) ...[const SizedBox(width: 6), OwlChip(_from(t) == 'd7' ? '7D' : 'TODAY', p.textMuted)],
              ]),
              Text('${t['f'] ?? ''}${src.isNotEmpty ? '  ·  $src' : ''}  ·  ${DualTradeCard.openFor(t['t']) == 'now' ? 'just now' : '${DualTradeCard.openFor(t['t'])} ago'}', style: context.type.metadata),
              Padding(padding: const EdgeInsets.only(top: 2), child: DualTradeCard.badgeRow(p, brain: _brain(t), label: t['label'])),
            ]),
          ),
          Text('${_sg(u)} USDT', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: u >= 0 ? p.profit : p.loss, fontFeatures: _tab)),
          Icon(Icons.chevron_right, size: 18, color: p.textMuted),
        ]),
      ),
    );
  }

  Widget _openCard(AppPalette p) {
    final allOpen = widget.recent.where((t) => '${t['status']}' == 'open').toList();
    final open = allOpen.where(_keep).toList();
    open.sort((a, b) => _openUsdt(b).compareTo(_openUsdt(a)));
    final shown = _all ? open : open.take(_showFirst).toList();
    final up = open.where((t) => _openUsdt(t) >= 0).length;
    return OwlSectionCard(title: _flt == 0 ? 'OPEN TRADES (${open.length})' : 'OPEN TRADES (${open.length} of ${allOpen.length})', children: [
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (var i = 0; i < _fltNames.length; i++)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(label: Text(_fltNames[i]), selected: _flt == i, visualDensity: VisualDensity.compact, onSelected: (_) => setState(() => _flt = i)),
            ),
        ]),
      ),
      if (open.isEmpty) Text(allOpen.isEmpty ? 'Nothing is open right now.' : 'No open trade matches this filter.', style: context.type.secondary),
      if (open.isNotEmpty) ...[
        Text('$up in profit, ${open.length - up} in loss. Best first. Tap for the chart.', style: context.type.metadata),
        const SizedBox(height: 2),
        for (final t in shown) _openRow(p, t),
        if (open.length > _showFirst)
          TextButton(
            onPressed: () => setState(() => _all = !_all),
            child: Text(_all ? 'Show less' : 'Show all ${open.length}'),
          ),
      ],
    ]);
  }

  Widget _doneRow(AppPalette p, Map<String, dynamic> t) {
    final buy = _n(t['d']) > 0;
    final u = _n(t['net']) * widget.marginOf(t) / 100.0;
    return InkWell(
      onTap: () => widget.onOpen(t),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${_coin(t['s'])}  ${buy ? 'BUY' : 'SELL'}  ${t['f'] ?? ''}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
              Padding(padding: const EdgeInsets.only(top: 2), child: DualTradeCard.badgeRow(p, brain: _brain(t), label: t['label'])),
            ]),
          ),
          Text('${_sg(u)} USDT', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: u >= 0 ? p.profit : p.loss, fontFeatures: _tab)),
        ]),
      ),
    );
  }

  Widget _doneCard(AppPalette p) {
    final done = widget.recent.where((t) => '${t['status']}' == 'closed' && t['net'] is num).toList();
    if (done.isEmpty) {
      return OwlSectionCard(title: 'BEST AND WORST FINISHED TRADES', children: [Text('No finished trade yet.', style: context.type.secondary)]);
    }
    done.sort((a, b) => (_n(b['net']) * widget.marginOf(b)).compareTo(_n(a['net']) * widget.marginOf(a)));
    final best = done.where((t) => _n(t['net']) > 0).take(3).toList();
    final worst = done.reversed.where((t) => _n(t['net']) < 0).take(3).toList();
    double usdt(Map<String, dynamic> t) => _n(t['net']) * widget.marginOf(t) / 100.0;
    final head = [
      if (best.isNotEmpty) 'Best ${_sg(usdt(best.first))}',
      if (worst.isNotEmpty) 'Worst ${_sg(usdt(worst.first))}',
    ].join('  ·  ');
    return OwlFold(title: 'BEST AND WORST FINISHED TRADES', headline: head.isEmpty ? 'Out of the latest ${done.length} finished trades' : '$head USDT', children: [
      Text('Out of the latest ${done.length} finished trades.', style: context.type.metadata),
      if (best.isNotEmpty) ...[
        const SizedBox(height: 4),
        Text('Best', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
        for (final t in best) _doneRow(p, t),
      ],
      if (worst.isNotEmpty) ...[
        const SizedBox(height: 6),
        Text('Worst', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
        for (final t in worst) _doneRow(p, t),
      ],
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      _threeBoxes(p),
      _health(p),
      _openCard(p),
      UniverseStrip(desk: widget.desk, archive: widget.archive),
      _signalTypeCard(p),
      _doneCard(p),
      Padding(
        padding: const EdgeInsets.only(top: 2, bottom: 4),
        child: Text('Want more detail? Now has the full trade cards, Brain has the scores and reports.', style: context.type.metadata),
      ),
    ]);
  }
}

/// UI2a: the day's verdict (colour, long word, short chip word, one sentence).
class _V {
  final Color c;
  final String head;
  final String shortHead;
  final String why;
  const _V(this.c, this.head, this.shortHead, this.why);
}
