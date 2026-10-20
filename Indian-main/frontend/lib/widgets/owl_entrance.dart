import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// One-shot list-item entrance: fade + slide up, staggered by [index].
///
/// * Give it a stable `key` (e.g. the alert / signal id). A brand-new item
///   gets a fresh State and plays the animation; items that merely shift
///   down when a new one arrives keep their State and do NOT replay.
/// * Only the first ~10 rows animate - rows further down appear instantly so
///   fast scrolling never feels laggy.
/// * [shake] adds a short horizontal shake (used for a fresh stop-loss).
class OwlEntrance extends StatefulWidget {
  final Widget child;
  final int index;
  final bool shake;

  const OwlEntrance({
    super.key,
    required this.child,
    this.index = 0,
    this.shake = false,
  });

  @override
  State<OwlEntrance> createState() => _OwlEntranceState();
}

class _OwlEntranceState extends State<OwlEntrance> with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  Timer? _delay;

  @override
  void initState() {
    super.initState();
    final instant = widget.index > 9;
    _c = AnimationController(vsync: this, duration: AppMotion.entrance);
    if (instant) {
      _c.value = 1;
    } else {
      _delay = Timer(AppMotion.stagger * widget.index, () {
        if (mounted) _c.forward();
      });
    }
  }

  @override
  void dispose() {
    _delay?.cancel();
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      child: widget.child,
      builder: (context, child) {
        final t = AppMotion.decel.transform(_c.value);
        final dx = widget.shake ? math.sin(_c.value * math.pi * 6) * 5 * (1 - _c.value) : 0.0;
        return Opacity(
          opacity: t.clamp(0.0, 1.0),
          child: Transform.translate(
            offset: Offset(dx, (1 - t) * 14),
            child: child,
          ),
        );
      },
    );
  }
}
