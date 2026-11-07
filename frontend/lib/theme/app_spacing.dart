import 'package:flutter/material.dart';

/// Spacing and radius scale shared by all OWL widgets.
class AppSpacing {
  AppSpacing._();

  static const double xs = 4.0;
  static const double s = 8.0;
  static const double m = 12.0;
  static const double l = 16.0;
  static const double xl = 20.0;
  static const double xxl = 24.0;
  static const double section = 32.0;
  static const double huge = 40.0;

  // Layout rhythm (screens use these instead of ad-hoc 14/18/22 values)
  static const double screenPad = 16.0; // horizontal page padding
  static const double cardGap = 10.0; // gap between stacked cards (E5: 12 -> 10)
  static const double cardPad = 12.0; // inner padding of a compact card (E5: 14 -> 12)

  // R31a (plan H3): section / row rhythm shared by every screen
  static const double sectionGap = 24.0; // space between two sections
  static const double rowMinHeight = 56.0; // a list row is never lower than this
  static const double rowPadV = 12.0; // vertical padding inside a row
  static const double dividerWidth = 1.0; // thin line between rows

  // Radii
  static const double radiusSmall = 8.0; // controls
  static const double radiusMedium = 12.0; // cards (R31a: 16 -> 12, less toy-like; one card around a whole list, not one per row)
  static const double radiusLarge = 18.0; // major surfaces (SR1a: 20 -> 18)
  static const double radiusPill = 100.0; // status badges

  // P-A / P-B: the floating bottom bar (one place to tune it)
  static const double radiusBar = 26.0; // bar corners
  static const double barHeight = 58.0; // the bar itself (E9: a bit lower)
  static const double barLift = 0.0; // E9: no lifted bubble any more (it cost 16 px of space on every screen)
  static const double barBubble = 46.0; // lit bubble size
  static const double barSide = 12.0; // gap left and right of the bar
}

/// E5: one shape and size for every button on every screen (Dashboard, Positions, Signals, Alerts, Dual Bot).
class AppButtons {
  AppButtons._();

  static const double minHeight = 40.0;
  static const EdgeInsets padding = EdgeInsets.symmetric(horizontal: 14, vertical: 8);
  static final RoundedRectangleBorder shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2));
  static const TextStyle label = TextStyle(fontSize: 13, fontWeight: FontWeight.w700, letterSpacing: 0.2);
}
