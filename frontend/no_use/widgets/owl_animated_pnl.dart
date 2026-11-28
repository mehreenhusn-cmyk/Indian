import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Signed P&L number that smoothly counts from its previous value to the new
/// one (350 ms) whenever [pnl] changes, coloured green/red by sign.
///
/// On every change it also flashes a soft glow behind the number - green when
/// P&L went up, red when it went down - that fades out in ~500 ms, so a
/// trader sees the direction of the move at a glance without reading digits.
///
/// TweenAnimationBuilder is given only an `end`, so it animates from
/// whatever value is currently on screen. (A tween with begin == end never
/// animates.)
class OWLAnimatedPnl extends StatefulWidget {
  final double pnl;
  final String currency;
  final TextStyle? style;
  final bool isHero;
  final int precision;

  /// Set false to disable the change-flash glow (e.g. dense lists).
  final bool flash;

  const OWLAnimatedPnl({
    super.key,
    required this.pnl,
    this.currency = 'USDT',
    this.style,
    this.isHero = false,
    this.precision = 2,
    this.flash = true,
  });

  @override
  State<OWLAnimatedPnl> createState() => _OWLAnimatedPnlState();
}

class _OWLAnimatedPnlState extends State<OWLAnimatedPnl>
    with SingleTickerProviderStateMixin {
  late final AnimationController _flashCtl;
  bool _wentUp = true;

  @override
  void initState() {
    super.initState();
    _flashCtl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 550),
    );
  }

  @override
  void didUpdateWidget(covariant OWLAnimatedPnl old) {
    super.didUpdateWidget(old);
    if (!widget.flash) return;
    // Ignore sub-display noise: only flash when the shown number changes.
    final a = old.pnl.toStringAsFixed(widget.precision);
    final b = widget.pnl.toStringAsFixed(widget.precision);
    if (a != b) {
      _wentUp = widget.pnl > old.pnl;
      _flashCtl.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _flashCtl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final color = widget.pnl >= 0 ? p.positive : p.negative;
    final base = widget.style ??
        (widget.isHero ? AppTypography.heroNumber : AppTypography.primaryData);

    final number = TweenAnimationBuilder<double>(
      tween: Tween<double>(end: widget.pnl),
      duration: const Duration(milliseconds: 350),
      curve: Curves.easeOutCubic,
      builder: (context, value, _) {
        var body = value.toStringAsFixed(widget.precision);
        // "-0.00" is noise; show a clean zero.
        if (double.tryParse(body) == 0) body = body.replaceFirst('-', '');
        final sign = value >= 0 || double.tryParse(body) == 0 ? '+' : '';
        return Row(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.baseline,
          textBaseline: TextBaseline.alphabetic,
          children: [
            Text('$sign$body', style: base.copyWith(color: color)),
            if (widget.currency.isNotEmpty) ...[
              const SizedBox(width: 4),
              Text(
                widget.currency,
                style: AppTypography.metadata.copyWith(color: p.textSecondary),
              ),
            ],
          ],
        );
      },
    );

    if (!widget.flash) return number;

    return AnimatedBuilder(
      animation: _flashCtl,
      child: number,
      builder: (context, child) {
        // 1.0 -> 0.0 over the flash duration.
        final t = 1.0 - Curves.easeOut.transform(_flashCtl.value);
        final flashColor = _wentUp ? p.positive : p.negative;
        return Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
          decoration: BoxDecoration(
            color: flashColor.withOpacity(0.16 * t),
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
          ),
          child: child,
        );
      },
    );
  }
}
