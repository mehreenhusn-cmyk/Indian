import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Number text that flashes green when [value] goes up and red when it goes
/// down, then fades back to [baseColor] (350 ms). Use it for live prices and
/// small numbers in lists. Signed P&L already has OWLAnimatedPnl.
///
/// Only flashes when the SHOWN text changes, so tiny noise below the display
/// precision does not blink.
class FlashValue extends StatefulWidget {
  final double value;
  final String text;
  final TextStyle? style;
  final Color? baseColor;

  const FlashValue({
    super.key,
    required this.value,
    required this.text,
    this.style,
    this.baseColor,
  });

  @override
  State<FlashValue> createState() => _FlashValueState();
}

class _FlashValueState extends State<FlashValue>
    with SingleTickerProviderStateMixin {
  late final AnimationController _ctl;
  bool _up = true;

  @override
  void initState() {
    super.initState();
    _ctl = AnimationController(vsync: this, duration: AppMotion.tick + const Duration(milliseconds: 150));
  }

  @override
  void didUpdateWidget(covariant FlashValue old) {
    super.didUpdateWidget(old);
    if (old.text != widget.text && old.value != widget.value) {
      _up = widget.value > old.value;
      _ctl.forward(from: 0);
    }
  }

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final base = widget.baseColor ?? widget.style?.color ?? p.textPrimary;
    final flash = _up ? p.profit : p.loss;
    return AnimatedBuilder(
      animation: _ctl,
      builder: (context, _) {
        // 1 right after the change, easing to 0.
        final k = _ctl.isAnimating ? 1.0 - Curves.easeOut.transform(_ctl.value) : 0.0;
        return Text(
          widget.text,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: (widget.style ?? context.type.primary).copyWith(
            color: Color.lerp(base, flash, k),
          ),
        );
      },
    );
  }
}
