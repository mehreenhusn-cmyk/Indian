import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// One row of the Market Watch list - symbol, live price, 24h change pill.
/// `item` is a raw entry from `AppProvider.movers` (real backend shape:
/// symbol/price/change_pct/category - see recovered_bot/app.py
/// get_current_movers()). `rank` is supplied by the caller (list position),
/// since the backend does not send one.
class MarketTile extends StatefulWidget {
  final Map<String, dynamic> item;
  final int? rank;
  final VoidCallback? onTap;

  const MarketTile({super.key, required this.item, this.rank, this.onTap});

  @override
  State<MarketTile> createState() => _MarketTileState();
}

class _MarketTileState extends State<MarketTile>
    with SingleTickerProviderStateMixin {
  late final AnimationController _flash = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 500),
  );
  bool _up = true;

  static double? _num(dynamic v) =>
      v is num ? v.toDouble() : double.tryParse('$v');

  @override
  void didUpdateWidget(covariant MarketTile old) {
    super.didUpdateWidget(old);
    final a = _num(old.item['price']);
    final b = _num(widget.item['price']);
    if (a != null && b != null && a != b) {
      _up = b > a;
      _flash.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _flash.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final item = widget.item;
    final rank = widget.rank;
    final onTap = widget.onTap;
    final p = context.palette;
    final t = context.type;

    final String symbol = '${item['symbol'] ?? '--'}';
    final num? priceNum = item['price'] is num ? item['price'] as num : num.tryParse('${item['price']}');
    final num? changeNum =
        item['change_pct'] is num ? item['change_pct'] as num : num.tryParse('${item['change_pct']}');
    final double change = changeNum?.toDouble() ?? 0.0;
    final bool isPositive = change >= 0;
    final Color color = isPositive ? p.positive : p.negative;
    final String category = '${item['category'] ?? ''}';

    // Adaptive precision - sub-dollar coins need more decimals than
    // toStringAsFixed(2) shows (matches the fix already noted for the
    // live ticker elsewhere in this app).
    String priceText;
    if (priceNum == null) {
      priceText = '--';
    } else {
      final v = priceNum.toDouble();
      final decimals = v >= 100 ? 2 : (v >= 1 ? 4 : 6);
      priceText = v.toStringAsFixed(decimals);
    }

    return InkWell(
      onTap: onTap,
      child: AnimatedBuilder(
        animation: _flash,
        builder: (context, child) {
          final t = 1.0 - Curves.easeOut.transform(_flash.value);
          return Container(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.m, horizontal: AppSpacing.l),
            decoration: BoxDecoration(
              color: (_up ? p.positive : p.negative).withOpacity(0.08 * t),
              border: Border(bottom: BorderSide(color: p.border, width: 0.5)),
            ),
            child: child,
          );
        },
        child: Row(
          children: [
            // 1. Rank & Symbol
            Expanded(
              flex: 3,
              child: Row(
                children: [
                  if (rank != null)
                    Container(
                      width: 24,
                      alignment: Alignment.centerLeft,
                      child: Text('#$rank', style: t.metadata),
                    ),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          symbol,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: t.primary.copyWith(fontWeight: FontWeight.bold),
                        ),
                        if (category.isNotEmpty)
                          Text(category.toUpperCase(), style: t.metadata.copyWith(fontSize: 8)),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            // 2. Last price
            Expanded(
              flex: 3,
              child: Text(
                priceText,
                textAlign: TextAlign.right,
                style: AppTypography.priceRow.copyWith(color: p.textPrimary),
              ),
            ),
            // 3. 24h change pill
            Expanded(
              flex: 2,
              child: Align(
                alignment: Alignment.centerRight,
                child: Container(
                  width: 65,
                  padding: const EdgeInsets.symmetric(vertical: AppSpacing.xs + 2),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.1),
                    borderRadius: BorderRadius.circular(AppSpacing.xs),
                  ),
                  child: Text(
                    '${isPositive ? '+' : ''}${change.toStringAsFixed(2)}%',
                    textAlign: TextAlign.center,
                    style: t.metadata.copyWith(color: color, fontWeight: FontWeight.w900, fontSize: 10),
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
