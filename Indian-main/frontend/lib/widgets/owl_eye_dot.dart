import 'dart:math' as math;
import 'package:flutter/material.dart';

/// Status dot that behaves like an owl eye: while [live] it breathes with a
/// soft glow and blinks once every few seconds. When not live it is a plain
/// static dot (no animation running, no battery cost).
class OwlEyeDot extends StatefulWidget {
  final bool live;
  final Color color;
  final double size;

  const OwlEyeDot({super.key, required this.live, required this.color, this.size = 7});

  @override
  State<OwlEyeDot> createState() => _OwlEyeDotState();
}

class _OwlEyeDotState extends State<OwlEyeDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(vsync: this, duration: const Duration(seconds: 5));
    if (widget.live) _c.repeat();
  }

  @override
  void didUpdateWidget(OwlEyeDot old) {
    super.didUpdateWidget(old);
    if (widget.live && !_c.isAnimating) {
      _c.repeat();
    } else if (!widget.live && _c.isAnimating) {
      _c.stop();
    }
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final dot = AnimatedBuilder(
      animation: _c,
      builder: (context, _) {
        final t = widget.live ? _c.value : 0.0;
        // Blink during the last 4% of each 5s cycle: eye closes and reopens.
        double sy = 1.0;
        if (t > 0.96) {
          final k = (t - 0.96) / 0.04; // 0..1
          sy = 1.0 - (k < 0.5 ? k * 2 : (1 - k) * 2) * 0.85;
        }
        final glow = widget.live ? (0.18 + 0.22 * (0.5 + 0.5 * math.sin(t * 2 * math.pi))) : 0.0;
        return Transform(
          alignment: Alignment.center,
          transform: Matrix4.diagonal3Values(1.0, sy, 1.0),
          child: Container(
            width: widget.size,
            height: widget.size,
            decoration: BoxDecoration(
              color: widget.color,
              shape: BoxShape.circle,
              boxShadow: widget.live
                  ? [BoxShadow(color: widget.color.withOpacity(glow), blurRadius: 6, spreadRadius: 1)]
                  : null,
            ),
          ),
        );
      },
    );
    return dot;
  }
}
