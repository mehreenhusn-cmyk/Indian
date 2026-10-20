import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_price_ticker.dart';

/// Horizontal price ladder: SL - Entry - TP1..TP4, with the live price.
///
/// Levels are placed PROPORTIONALLY to their real price (lower price on the
/// left), so a TP that is far away really looks far away. Longs therefore
/// read left-to-right toward profit, shorts right-to-left.
///
/// - Bar fill runs Entry -> LTP: green while in profit, red while under water.
/// - A TP the price has already passed is a filled dot, the NEXT TP gets a
///   highlighted ring, the rest are hollow.
/// - `null` TPs (unset) are skipped but keep their TP number.
///
/// Purely visual - takes values, does no math on orders and touches no
/// PANIC / CLOSE / TP selection logic.
class TPLadder extends StatelessWidget {
  final double entry;
  final double ltp;
  final double? sl;
  final List<double?> tps;
  final bool isLong;

  const TPLadder({
    super.key,
    required this.entry,
    required this.ltp,
    this.sl,
    required this.tps,
    required this.isLong,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;

    final levels = <_Level>[
      if (sl != null) _Level('SL', sl!, p.negative, _Kind.sl),
      _Level('Entry', entry, p.accent, _Kind.entry),
    ];
    for (var i = 0; i < tps.length; i++) {
      final v = tps[i];
      if (v != null) levels.add(_Level('TP${i + 1}', v, p.positive, _Kind.tp));
    }

    // Price axis bounds cover every level AND the live price.
    var lo = ltp, hi = ltp;
    for (final l in levels) {
      if (l.price < lo) lo = l.price;
      if (l.price > hi) hi = l.price;
    }
    final range = hi - lo;
    double frac(double v) =>
        range <= 0 ? 0.5 : ((v - lo) / range).clamp(0.0, 1.0).toDouble();

    bool passed(double tp) => isLong ? ltp >= tp : ltp <= tp;
    // Next TP = nearest not-yet-passed TP in the profit direction.
    _Level? nextTp;
    for (final l in levels.where((l) => l.kind == _Kind.tp && !passed(l.price))) {
      final cur = nextTp;
      if (cur == null || (isLong ? l.price < cur.price : l.price > cur.price)) {
        nextTp = l;
      }
    }
    final next = nextTp;

    final inProfit = isLong ? ltp >= entry : ltp <= entry;
    final fillColor = (inProfit ? p.positive : p.negative).withOpacity(0.55);
    final a = frac(entry), b = frac(ltp);
    final fillStart = a < b ? a : b;
    final fillEnd = a < b ? b : a;

    final byPrice = [...levels]..sort((x, y) => x.price.compareTo(y.price));

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        SizedBox(
          height: 22,
          child: LayoutBuilder(
            builder: (context, c) {
              final w = c.maxWidth;
              const pad = 6.0; // keep edge dots inside the box
              final usable = w - pad * 2;
              double x(double f) => pad + usable * f;

              return Stack(
                clipBehavior: Clip.none,
                children: [
                  Positioned(
                    left: pad,
                    right: pad,
                    top: 10,
                    child: Container(
                      height: 2,
                      decoration: BoxDecoration(
                        color: p.border,
                        borderRadius: BorderRadius.circular(1),
                      ),
                    ),
                  ),
                  AnimatedPositioned(
                    duration: AppMotion.base,
                    curve: AppMotion.standard,
                    left: x(fillStart),
                    width: (x(fillEnd) - x(fillStart)).clamp(0.0, w).toDouble(),
                    top: 10,
                    child: Container(height: 2, color: fillColor),
                  ),
                  for (final l in levels)
                    Positioned(
                      left: x(frac(l.price)) - 5,
                      top: 6,
                      child: _dot(p, l, passed: l.kind == _Kind.tp && passed(l.price), isNext: identical(l, next)),
                    ),
                  // live price tick
                  AnimatedPositioned(
                    duration: AppMotion.base,
                    curve: AppMotion.standard,
                    left: x(b) - 1,
                    top: 2,
                    child: Container(
                      width: 2,
                      height: 18,
                      decoration: BoxDecoration(
                        color: p.textPrimary,
                        borderRadius: BorderRadius.circular(1),
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
        const SizedBox(height: AppSpacing.xs),
        // Tags + prices, ordered by price so they read the same way the bar does.
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            for (final l in byPrice)
              Flexible(
                child: FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        l.tag,
                        style: AppTypography.metadata.copyWith(
                          color: l.color,
                          fontWeight: FontWeight.w700,
                          fontSize: 9,
                        ),
                      ),
                      Text(
                        OWLPriceTicker.format(l.price),
                        style: AppTypography.metadata.copyWith(color: p.textSecondary),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ),
      ],
    );
  }

  Widget _dot(AppPalette p, _Level l, {required bool passed, required bool isNext}) {
    final solid = l.kind != _Kind.tp || passed;
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(
        color: solid ? l.color : p.surfaceElevated,
        shape: BoxShape.circle,
        border: Border.all(
          color: l.color,
          width: isNext ? 2 : 1.2,
        ),
        boxShadow: (solid || isNext)
            ? [BoxShadow(color: l.color.withOpacity(0.4), blurRadius: 4)]
            : null,
      ),
    );
  }
}

enum _Kind { sl, entry, tp }

class _Level {
  final String tag;
  final double price;
  final Color color;
  final _Kind kind;
  const _Level(this.tag, this.price, this.color, this.kind);
}
