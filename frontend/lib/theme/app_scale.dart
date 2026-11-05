import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'app_spacing.dart';

/// R23: ONE rule for text size on every phone. The system font scale is clamped to 0.9 - 1.15, so a phone set to
/// "huge text" (or a tiny one) can never break a screen. Used once, in OwlApp (main.dart) as MaterialApp.builder.
/// Everything else (sizes per role) lives in app_typography.dart and follows the table in OWL_BRIEF/06_FRONTEND_SPEC.md.
/// Part 12b (owner: "row height and font must AUTO-SIZE to the screen"): on top of the clamp, text AND list rows follow the screen size.
///   screen(context) = min(width / 360, height / 780), kept between 0.92 and 1.10 (a small phone a little smaller, a big phone a little bigger, never extreme).
///   Text: final scale = clamped system scale x screen(context), kept between 0.85 and 1.25 (so "huge text" in the phone settings still works and still cannot break a screen).
///   Rows: rowHeight(context) = AppSpacing.rowMinHeight (56) x screen(context). Set [autoSize] to false to switch the screen part off (system clamp only).
class AppScale {
  AppScale._();

  static const double minText = 0.9;
  static const double maxText = 1.15;
  static const bool autoSize = true;
  static const double minScreen = 0.92;
  static const double maxScreen = 1.10;

  /// 1.0 on a 360 x 780 dp phone.
  static double screen(BuildContext context) {
    if (!autoSize) return 1.0;
    final s = MediaQuery.of(context).size;
    if (s.width <= 0 || s.height <= 0) return 1.0;
    return math.min(s.width / 360.0, s.height / 780.0).clamp(minScreen, maxScreen).toDouble();
  }

  static double rowHeight(BuildContext context) => AppSpacing.rowMinHeight * screen(context);

  static Widget clampText(BuildContext context, Widget? child) {
    final mq = MediaQuery.of(context);
    final system = (mq.textScaler.scale(14.0) / 14.0).clamp(minText, maxText).toDouble();
    final scale = (system * screen(context)).clamp(0.85, 1.25).toDouble();
    // Part 13b (owner: "the bottom of the screen gets cut on some phones"): some Android phones report a bottom padding of 0 while the gesture / navigation bar still covers the screen.
    // Without the keyboard, the bottom inset is the larger of padding and viewPadding, so every SafeArea and the bottom bar keep clear of the system bar.
    final keyboard = mq.viewInsets.bottom > 0;
    final bottom = keyboard ? mq.padding.bottom : math.max(mq.padding.bottom, mq.viewPadding.bottom);
    return MediaQuery(
      data: mq.copyWith(textScaler: TextScaler.linear(scale), padding: mq.padding.copyWith(bottom: bottom)),
      child: child ?? const SizedBox.shrink(),
    );
  }
}
