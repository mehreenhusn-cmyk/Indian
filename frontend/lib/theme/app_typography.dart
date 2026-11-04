import 'dart:ui' show FontFeature;
import 'package:flutter/material.dart';

/// Colour-less text styles. Colours are applied per theme through
/// `context.type` (see app_theme.dart) so the same widget renders correctly
/// in both the dark and the light theme.
///
/// Numbers use tabular figures so live prices/P&L do not "jitter" sideways
/// when digits change. The bundled Inter files only ship Regular (400) and
/// Bold (700); w500 resolves to Regular and w600 to Bold.
/// R23 text scale (OWL_BRIEF/06): hero 28 (heroXL kept as a name, now 28), title 20, heading 16, row title 15, row number 14.5 (15 in the plan: kept 0.5 smaller so 6-decimal prices still fit 360dp),
/// secondary 13, caption / label / metadata 12, nothing below 11 (eyebrow 11). System font scale is clamped in app_scale.dart.
class AppTypography {
  AppTypography._();

  static const String fontFamily = 'Inter';

  static const List<FontFeature> _tabular = [FontFeature.tabularFigures()];

  static const TextStyle heroNumber = TextStyle(
    fontFamily: fontFamily,
    fontSize: 28,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.8,
    fontFeatures: _tabular,
  );

  /// UI1: the ONE big number of a screen (Today P&L, Net). SR1a: 36px, tight tracking.
  static const TextStyle heroXL = TextStyle(
    fontFamily: fontFamily,
    fontSize: 28,
    fontWeight: FontWeight.w700,
    letterSpacing: -1.0,
    height: 1.05,
    fontFeatures: _tabular,
  );

  static const TextStyle sectionHeading = TextStyle(
    fontFamily: fontFamily,
    fontSize: 16,
    fontWeight: FontWeight.w600,
  );

  static const TextStyle primaryData = TextStyle(
    fontFamily: fontFamily,
    fontSize: 15,
    fontWeight: FontWeight.w500,
    fontFeatures: _tabular,
  );

  static const TextStyle secondaryData = TextStyle(
    fontFamily: fontFamily,
    fontSize: 13,
    fontWeight: FontWeight.w400,
    fontFeatures: _tabular,
  );

  static const TextStyle metadata = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
    fontFeatures: _tabular,
  );

  /// Small caption above a value ("Entry", "Realized PNL"). Slightly
  /// looser tracking + a touch smaller than [metadata] so the value under
  /// it reads as the hero of the cell. (Real Medium/SemiBold weights need
  /// Inter Medium/SemiBold .ttf bundled in assets/fonts - until then
  /// hierarchy comes from size, colour and tracking.)
  static const TextStyle label = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
    letterSpacing: 0.25,
    fontFeatures: _tabular,
  );

  /// Big-but-not-hero number (Realized PNL in a card grid).
  static const TextStyle numberLarge = TextStyle(
    fontFamily: fontFamily,
    fontSize: 17,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.3,
    fontFeatures: _tabular,
  );

  /// Live price in a list row / tile - tight tracking so 6-decimal
  /// micro-cap prices (0.123456) still fit on a 360dp phone.
  static const TextStyle priceRow = TextStyle(
    fontFamily: fontFamily,
    fontSize: 14.5,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.35,
    fontFeatures: _tabular,
  );

  /// Round 10b: the number of a stat tile or verdict card (plan: numbers 18 to 22 pt, bold, tabular so live digits do not jitter).
  static const TextStyle number = TextStyle(
    fontFamily: fontFamily,
    fontSize: 20,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.4,
    fontFeatures: _tabular,
  );

  /// Round 10b: dimmed helper line under a number or a title (plan: labels and metadata 11 to 13 pt).
  static const TextStyle caption = TextStyle(
    fontFamily: fontFamily,
    fontSize: 12,
    fontWeight: FontWeight.w400,
    fontFeatures: _tabular,
  );

  /// Tiny uppercase eyebrow above a section ("P&L TODAY").
  static const TextStyle eyebrow = TextStyle(
    fontFamily: fontFamily,
    fontSize: 11,
    fontWeight: FontWeight.w700,
    letterSpacing: 0.8,
  );
}
