import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/dedupe_positions.dart';
import '../utils/format.dart';
import 'owl_pressable.dart';

/// Round 13: "Open pairs" on the Dashboard. ONE compact row per coin + side (dedupePositions folds repeats, "x2" shows the fold),
/// newest first, at most [maxRows] rows, the rest as "+N more". Tap anywhere = Positions tab (where close / TP / SL live).
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
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
          padding: const EdgeInsets.all(AppSpacing.cardPad),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            OWLPressable(
              pressedScale: 0.99,
              onTap: openPositions,
              child: Row(children: [
                Expanded(child: Text(rows.isEmpty ? 'Open pairs' : 'Open pairs (${rows.length})', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
                if (rows.isNotEmpty) Text(fmtSigned(total), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: total > 0 ? p.profit : (total < 0 ? p.loss : p.textPrimary))),
                Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
              ]),
            ),
            if (rows.isEmpty)
              Padding(padding: const EdgeInsets.only(top: 6), child: Text('No open trades right now', style: context.type.secondary.copyWith(color: p.textMuted)))
            else ...[
              const SizedBox(height: AppSpacing.s),
              for (final r in shown) _PairRow(row: r, onTap: openPositions),
              if (rows.length > shown.length)
                Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Text('+${rows.length - shown.length} more in Positions', style: context.type.metadata),
                ),
            ],
          ]),
        );
      },
    );
  }
}

class _PairRow extends StatelessWidget {
  final Map<String, dynamic> row;
  final VoidCallback onTap;

  const _PairRow({required this.row, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final isLong = row['action'] == 'BUY';
    final side = isLong ? p.profit : p.loss;
    final pnl = DashboardPairs._n(row['pnl_usdt']);
    final roi = DashboardPairs._n(row['roi_pct']);
    final ts = DashboardPairs._n(row['opened_at_ts']);
    final dup = (row['dup_count'] is num) ? (row['dup_count'] as num).toInt() : 1;
    final age = ts == null ? '' : fmtSpan(DateTime.now().millisecondsSinceEpoch / 1000 - ts);
    final pnlColor = pnl == null || pnl == 0 ? p.textPrimary : (pnl > 0 ? p.profit : p.loss);
    final symbol = (row['symbol'] ?? '--').toString();
    return OWLPressable(
      pressedScale: 0.99,
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(symbol, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(color: side.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2)),
                  child: Text(isLong ? 'LONG' : 'SHORT', style: context.type.label.copyWith(color: side, fontSize: 10.5, fontWeight: FontWeight.w700)),
                ),
                if (dup > 1) Padding(padding: const EdgeInsets.only(left: 6), child: Text('x$dup', style: context.type.label.copyWith(color: p.warning, fontWeight: FontWeight.w700))),
              ]),
              if (age.isNotEmpty) Text('open $age', style: context.type.metadata),
            ]),
          ),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(pnl == null ? '--' : fmtSigned(pnl), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: pnlColor)),
            if (roi != null) Text('${fmtSigned(roi, 1)}%', style: context.type.metadata.copyWith(color: pnlColor)),
          ]),
        ]),
      ),
    );
  }
}
