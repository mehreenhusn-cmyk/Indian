import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'trade_row.dart';

/// Bottom sheet with every trade of ONE coin (usually today's), newest first.
/// Rows are TradeRow, so tapping one opens its chart like everywhere else.
void showCoinHistorySheet(
  BuildContext context, {
  required String title,
  required List<TradeRowData> rows,
}) {
  showModalBottomSheet(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.transparent,
    builder: (ctx) => DraggableScrollableSheet(
      initialChildSize: 0.66,
      minChildSize: 0.4,
      maxChildSize: 0.94,
      expand: false,
      builder: (ctx, ctl) => _CoinHistory(title: title, rows: rows, controller: ctl),
    ),
  );
}

class _CoinHistory extends StatelessWidget {
  final String title;
  final List<TradeRowData> rows;
  final ScrollController controller;
  const _CoinHistory({required this.title, required this.rows, required this.controller});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final won = rows.where((r) => r.status == 'won').length;
    final lost = rows.where((r) => r.status == 'lost').length;
    final net = rows.fold<double>(0, (a, r) => a + (r.pnl ?? 0));
    final netColor = net > 0 ? p.profit : (net < 0 ? p.loss : p.textSecondary);

    return Container(
      decoration: BoxDecoration(
        color: p.bg,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(24)),
        border: Border.all(color: p.border),
      ),
      child: Column(
        children: [
          const SizedBox(height: 8),
          Container(
            width: 38,
            height: 4,
            decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(4)),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: t.section.copyWith(fontSize: 18, fontWeight: FontWeight.w700)),
                      const SizedBox(height: 2),
                      Text('${rows.length} trades  ·  $won won  ·  $lost lost', style: t.metadata),
                    ],
                  ),
                ),
                Text('${fmtSigned(net)} USDT',
                    style: t.primary.copyWith(color: netColor, fontWeight: FontWeight.w800, fontSize: 18)),
              ],
            ),
          ),
          Expanded(
            child: rows.isEmpty
                ? Center(child: Text('No trades yet', style: t.secondary))
                : ListView.separated(
                    controller: controller,
                    padding: const EdgeInsets.fromLTRB(14, 6, 14, 24),
                    itemCount: rows.length,
                    separatorBuilder: (_, __) => const SizedBox(height: AppSpacing.s),
                    itemBuilder: (_, i) => TradeRow(data: rows[i]),
                  ),
          ),
        ],
      ),
    );
  }
}
