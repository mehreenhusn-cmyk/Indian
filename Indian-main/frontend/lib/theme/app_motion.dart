import 'package:flutter/animation.dart';
import 'package:flutter/services.dart';

/// Shared animation durations + curves. One place to tune the whole app's
/// "feel" instead of hunting for hardcoded 200ms / 220ms / 280ms values.
class AppMotion {
  AppMotion._();

  static const Duration fast = Duration(milliseconds: 120); // press feedback
  static const Duration base = Duration(milliseconds: 200); // expand, fade
  static const Duration slow = Duration(milliseconds: 280); // glow, tab switch
  static const Duration tick = Duration(milliseconds: 350); // live-price flash
  static const Duration entrance = Duration(milliseconds: 380); // list item slide-in
  static const Duration stagger = Duration(milliseconds: 45); // delay per list index

  static const Curve standard = Curves.easeOut;
  static const Curve emphasized = Curves.easeInOutCubic;
  static const Curve decel = Curves.easeOutCubic;
}

/// Thin wrapper over HapticFeedback so every screen uses the same
/// intensity for the same kind of event.
class AppHaptics {
  AppHaptics._();

  /// Tab switch, TP target set, SL -> BE.
  static void light() => HapticFeedback.lightImpact();

  /// Trade closed / bulk close done.
  static void medium() => HapticFeedback.mediumImpact();

  /// PANIC confirmed - the one action that should feel heavy.
  static void heavy() => HapticFeedback.heavyImpact();
}
