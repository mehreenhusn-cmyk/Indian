import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_card.dart';

/// Z2b (Part U4, app part 1): TODAY vs LAST 7 DAYS blocks for the Dual Bot desk, each with 5m and 15m rows.
/// Shows only what GET /api/dual_desk already sends (small, read-only, from the permanent archive). Nothing here trades.
///   TODAY       = trades on coins that are in today's top list (BTC included)
///   LAST 7 DAYS = trades on coins that are on the list ONLY because they were top coins in the last 7 days
/// Money = USDT (margin x ROI), same as the rest of the screen. Trading day = 5:30 AM IST.
class UniverseStrip extends StatelessWidget {
  final Map<String, dynamic> desk; // reply of /api/dual_desk (may be empty before the first answer)
  final Map<String, dynamic> archive; // reply of /api/archive, for the DATA SAFE chip (Z2c)

  const UniverseStrip({super.key, required this.desk, this.archive = const {}});

  /// DATA SAFE chip: the permanent archive is saving (safe), waiting (Dual Bot stopped?), not started, or has a problem.
  Widget _safeChip(AppPalette p) {
    switch ('${archive['state'] ?? ''}') {
      case 'safe':
        return OwlChip('DATA SAFE', p.profit);
      case 'stale':
        return OwlChip('SAVE WAITING', p.warning);
      case 'error':
        return OwlChip('ARCHIVE PROBLEM', p.loss);
      case 'none':
        return OwlChip('NOT STARTED', p.textMuted);
      default:
        return const SizedBox.shrink();
    }
  }

  static const _tab = [FontFeature.tabularFigures()];
  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

  Widget _row(BuildContext context, AppPalette p, String tf, Map<String, dynamic> c) {
    final n = _n(c['n']).toInt();
    final wins = _n(c['wins']).toInt();
    final open = _n(c['open']).toInt();
    final net = _n(c['net']);
    final sub = n == 0 ? 'no finished trade yet' : '$n done, ${(100 * wins / n).round()}% won';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        SizedBox(width: 44, child: OwlChip(tf, p.textMuted)),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(sub, style: context.type.secondary),
            Text(open == 0 ? 'nothing open' : '$open open now', style: context.type.metadata),
          ]),
        ),
        if (n > 0)
          Text('${fmtSigned(net)} USDT',
              style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss, fontFeatures: _tab)),
      ]),
    );
  }

  Widget _block(BuildContext context, AppPalette p, String title, Map<String, dynamic> g) {
    var net = 0.0;
    for (final tf in const ['5m', '15m']) {
      net += _n(_m(g[tf])['net']);
    }
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 10),
      decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(10)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: context.type.label.copyWith(fontWeight: FontWeight.w800))),
          Text('${fmtSigned(net)} USDT', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss, fontFeatures: _tab)),
        ]),
        _row(context, p, '5m', _m(g['5m'])),
        _row(context, p, '15m', _m(g['15m'])),
      ]),
    );
  }

  /// Old trades (before the coin log started) or coins that left the list: one quiet line, only if there are any.
  String _otherLine(Map<String, dynamic> g) {
    var n = 0, open = 0;
    for (final tf in const ['5m', '15m']) {
      n += _n(_m(g[tf])['n']).toInt();
      open += _n(_m(g[tf])['open']).toInt();
    }
    return (n + open) == 0 ? '' : 'Also today: $n done and $open open on coins that left the list (not in the blocks above).';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final state = '${desk['state'] ?? ''}';
    if (desk.isEmpty || state == 'none') {
      return OwlSectionCard(title: 'TODAY VS LAST 7 DAYS COINS', children: [
        Text(desk.isEmpty ? 'Waiting for the first answer...' : 'Archive not started yet. It fills as the Dual Bot runs.', style: context.type.secondary),
      ]);
    }
    if (state == 'error') {
      return OwlSectionCard(title: 'TODAY VS LAST 7 DAYS COINS', edge: p.warning, children: [
        Text('Could not read the archive just now. It will retry by itself.', style: context.type.secondary),
        if ('${desk['err'] ?? ''}'.isNotEmpty) Text('${desk['err']}', style: context.type.metadata),
      ]);
    }
    final g = _m(desk['groups']);
    final other = _otherLine(_m(g['other']));
    // UI2a: folded. The headline already carries the two money numbers, the blocks open on tap.
    double grp(String k) => _n(_m(_m(g[k])['5m'])['net']) + _n(_m(_m(g[k])['15m'])['net']);
    final tNet = grp('today'), dNet = grp('d7');
    return OwlFold(
      title: 'TODAY VS LAST 7 DAYS COINS',
      headline: 'Today coins ${fmtSigned(tNet)}  ·  7-day coins ${fmtSigned(dNet)} USDT',
      trailing: _safeChip(p),
      children: [
        Text('Since 5:30 AM IST. Same trades, split by where the coin came from.', style: context.type.metadata),
        const SizedBox(height: 6),
        _block(context, p, "TODAY'S TOP COINS", _m(g['today'])),
        _block(context, p, "LAST 7 DAYS' COINS (live only)", _m(g['d7'])),
        if (other.isNotEmpty) Text(other, style: context.type.metadata),
      ],
    );
  }
}
