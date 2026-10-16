import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Tap wrapper with a subtle press-fade and an optional haptic click.
///
/// Haptic fires only when a tap COMPLETES (not on touch-down), so starting a
/// scroll on top of a pressable never buzzes the phone.
///
/// Do NOT use this for hold-to-confirm actions (PANIC) - those keep their own
/// long-press gesture handling.
class OWLPressable extends StatefulWidget {
  final Widget child;
  final VoidCallback? onTap;
  final bool enableHaptics;

  /// Scale while pressed (1.0 = no scale). Small controls look better at
  /// ~0.96, big cards at ~0.985.
  final double pressedScale;

  /// Use the stronger click for important actions (close, toggle).
  final bool strongHaptic;

  const OWLPressable({
    super.key,
    required this.child,
    this.onTap,
    this.enableHaptics = true,
    this.pressedScale = 0.97,
    this.strongHaptic = false,
  });

  @override
  State<OWLPressable> createState() => _OWLPressableState();
}

class _OWLPressableState extends State<OWLPressable> {
  bool _isPressed = false;

  void _setPressed(bool v) {
    if (_isPressed != v && mounted) setState(() => _isPressed = v);
  }

  void _handleTap() {
    if (widget.enableHaptics) {
      widget.strongHaptic
          ? HapticFeedback.lightImpact()
          : HapticFeedback.selectionClick();
    }
    widget.onTap?.call();
  }

  @override
  Widget build(BuildContext context) {
    final enabled = widget.onTap != null;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapDown: enabled ? (_) => _setPressed(true) : null,
      onTapUp: enabled ? (_) => _setPressed(false) : null,
      onTapCancel: enabled ? () => _setPressed(false) : null,
      onTap: enabled ? _handleTap : null,
      child: AnimatedScale(
        duration: const Duration(milliseconds: 110),
        curve: Curves.easeOut,
        scale: _isPressed ? widget.pressedScale : 1.0,
        child: AnimatedOpacity(
          duration: const Duration(milliseconds: 90),
          opacity: _isPressed ? 0.78 : 1.0,
          child: widget.child,
        ),
      ),
    );
  }
}
