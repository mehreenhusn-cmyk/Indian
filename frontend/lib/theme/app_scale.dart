import 'package:flutter/material.dart';

/// R23: ONE rule for text size on every phone. The system font scale is clamped to 0.9 - 1.15, so a phone set to
/// "huge text" (or a tiny one) can never break a screen. Used once, in OwlApp (main.dart) as MaterialApp.builder.
/// Everything else (sizes per role) lives in app_typography.dart and follows the table in OWL_BRIEF/06_FRONTEND_SPEC.md.
class AppScale {
  AppScale._();

  static const double minText = 0.9;
  static const double maxText = 1.15;

  static Widget clampText(BuildContext context, Widget? child) {
    final mq = MediaQuery.of(context);
    return MediaQuery(
      data: mq.copyWith(textScaler: mq.textScaler.clamp(minScaleFactor: minText, maxScaleFactor: maxText)),
      child: child ?? const SizedBox.shrink(),
    );
  }
}
