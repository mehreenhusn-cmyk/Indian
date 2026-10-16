import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Price text that flashes green/red for ~300 ms when the value ticks
/// up/down, then settles back to its base colour.
///
/// [precision] = null (default) picks decimals from the price size so
/// sub-dollar coins (0.000123) don't collapse to "0.00". Pass an explicit
/// precision to force a fixed number of decimals.
///
/// Wrapped in a RepaintBoundary so a 1 Hz price flash never repaints the
/// list row around it.
class OWLPriceTicker extends StatefulWidget {
  final double price;
  final int? precision;
  final TextStyle? style;
  final String prefix;
  final String suffix;

  const OWLPriceTicker({
    super.key,
    required this.price,
    this.precision,
    this.style,
    this.prefix = '',
    this.suffix = '',
  });

  /// Adaptive price formatting shared by the ladder / tiles.
  static String format(double price, {int? precision}) {
    if (precision != null) return price.toStringAsFixed(precision);
    final a = price.abs();
    int d;
    if (a >= 1000) {
      d = 2;
    } else if (a >= 100) {
      d = 3;
    } else if (a >= 1) {
      d = 4;
    } else if (a >= 0.1) {
      d = 5;
    } else if (a >= 0.01) {
      d = 6;
    } else {
      d = 8;
    }
    return price.toStringAsFixed(d);
  }

  @override
  State<OWLPriceTicker> createState() => _OWLPriceTickerState();
}

class _OWLPriceTickerState extends State<OWLPriceTicker>
    with SingleTickerProviderStateMixin {
  late final AnimationController _anim;
  Color? _flashColor;
  double _prevPrice = 0.0;

  @override
  void initState() {
    super.initState();
    _prevPrice = widget.price;
    _anim = AnimationController(
      vsync: this,
      duration: AppMotion.tick,
    );
  }

  @override
  void didUpdateWidget(covariant OWLPriceTicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.price != _prevPrice) {
      final p = context.palette;
      _flashColor = widget.price > _prevPrice ? p.positive : p.negative;
      _prevPrice = widget.price;
      _anim.forward(from: 0.0);
    }
  }

  @override
  void dispose() {
    _anim.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = widget.style ??
        AppTypography.primaryData.copyWith(fontWeight: FontWeight.w700);
    final baseColor = base.color ?? p.textPrimary;
    final text =
        '${widget.prefix}${OWLPriceTicker.format(widget.price, precision: widget.precision)}${widget.suffix}';

    return RepaintBoundary(
      child: AnimatedBuilder(
        animation: _anim,
        builder: (context, _) {
          final flash = _flashColor;
          final color = (flash == null || !_anim.isAnimating)
              ? baseColor
              : Color.lerp(flash, baseColor, Curves.easeOut.transform(_anim.value))!;
          return Text(text, style: base.copyWith(color: color));
        },
      ),
    );
  }
}
