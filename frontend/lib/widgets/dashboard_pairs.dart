import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/dedupe_positions.dart';
import '../utils/format.dart';
import 'owl_number.dart';
import 'owl_row.dart';
import 'owl_sentence.dart';

/// Round 13: "Open pairs" on the Dashboard. ONE compact row per coin + side (dedupePositions folds repeats, "x2" shows the fold),
/// newest first, at most [maxRows] rows, the rest as "+N more". Tap anywhere = Positions tab (where close / TP / SL live).
/// Part 12b: new look = a small spaced heading (with the open total on the right), then ONE card around the whole list: rows (OwlRow, height follows the screen), thin dividers, no box per row.
/// Numbers come only from the position maps the backend already sends: pnl_usdt, roi_pct, opened_at_ts. A missing number prints "--", never "None".
/// Own Selector: rebuilds only when a row's coin, side, rounded P&L or count changes, not on every price tick of an unrelated coin.
class DashboardPairs extends StatelessWidget {
  final int maxRows;

  const DashboardPairs({super.key, this.maxRows = 5});

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  static String _sig(AppProvider p) => [
        for (final r in dedupePositions(p.positions)) '${r['symbol']}|${r['action']}|${((_n(r['pnl_usdt']) ?? 0) * 100).round()}|${r['dup_count']}',
      ].join(';');

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, String>(
      selector: (_, p) => _sig(p),
      builder: (context, _, __) {
        final prov = context.read<AppProvider>();
        final p = context.palette;
        final rows = dedupePositions(prov.positions);
        final total = rows.fold<double>(0, (a, r) => a + (_n(r['pnl_usdt']) ?? 0));
        final shown = rows.take(maxRows).toList();
        void openPositions() => prov.goToRoute(AppRoute.positions);
        return Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            OwlSectionLabel(rows.isEmpty ? 'Open pairs' : 'Open pairs (${rows.length})', note: rows.isEmpty ? '' : '${fmtSigned(total)} USDT'),
            if (rows.isEmpty)
              OwlListCard(children: [OwlRow(title: 'No open trades right now', sub: 'Open pairs appear here', onTap: openPositions)])
            else
              OwlListCard(children: [
                for (final r in shown) _pairRow(context, r, openPositions),
                if (rows.length > shown.length) OwlRow(title: '+${rows.length - shown.length} more in Positions', onTap: openPositions),
              ]),
          ]),
        );
      },
    );
  }

  Widget _pairRow(BuildContext context, Map<String, dynamic> row, VoidCallback onTap) {
    final p = context.palette;
    final isLong = row['action'] == 'BUY';
    final pnl = _n(row['pnl_usdt']);
    final roi = _n(row['roi_pct']);
    final ts = _n(row['opened_at_ts']);
    final dup = (row['dup_count'] is num) ? (row['dup_count'] as num).toInt() : 1;
    final age = ts == null ? '' : fmtSpan(DateTime.now().millisecondsSinceEpoch / 1000 - ts);
    final symbol = (row['symbol'] ?? '--').toString();
    return OwlRow(
      title: dup > 1 ? '$symbol  x$dup' : symbol,
      sub: age.isEmpty ? '' : 'open $age',
      leading: OwlPill(isLong ? 'LONG' : 'SHORT', tone: isLong ? 'good' : 'bad'),
      trailing: Column(crossAxisAlignment: CrossAxisAlignment.end, mainAxisSize: MainAxisSize.min, children: [
        OwlNumber(pnl, size: 15, alignRight: true),
        if (roi != null) Text('${fmtSigned(roi, 1)}%', style: context.type.metadata.copyWith(color: pnl == null || pnl == 0 ? p.textMuted : (pnl > 0 ? p.profit : p.loss))),
      ]),
      onTap: onTap,
    );
  }
}
