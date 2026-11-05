import 'package:flutter/material.dart';
import 'app_theme.dart';

/// Part P-A (look tokens v2): the NEW look rules in one file, so every later step (bar, top switch, status header) uses the same times and colours.
/// Not exported from app_theme.dart on purpose: import it where needed. Nothing here talks to the backend. Dart NOT compiled.
///
/// OwlMotion  how long things take. Rule: anything the owner TAPS answers in 120 ms; anything that slides or opens takes 220 to 280 ms and slows down at the end (ease-out), never longer.
/// OwlLook    the ONE accent gradient (only for the lit thing: the bar bubble, the switch thumb) and the PAPER / LIVE / ping colours.
class OwlMotion {
  OwlMotion._();

  static const Duration tap = Duration(milliseconds: 120); // press feedback
  static const Duration slide = Duration(milliseconds: 250); // bar bubble, CRYPTO / INDIA thumb
  static const Duration sheet = Duration(milliseconds: 280); // a panel that opens (details sheet)
  static const Duration fade = Duration(milliseconds: 180); // text / number change

  static const Curve spring = Curves.easeOutBack; // a small overshoot = feels alive, used only for the bar bubble
  static const Curve smooth = Curves.easeOutCubic; // everything else
}

class OwlLook {
  OwlLook._();

  /// The one gradient of the app: accent into purple, 45%. Only for what is LIT (selected). Never for a card or a background.
  static LinearGradient accentGradient(AppPalette p) => LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [p.accent, Color.lerp(p.accent, p.purple, 0.45)!],
      );

  /// PAPER (practice money) = the calm accent blue. LIVE (real money) = amber, because it needs attention. Green and red are NEVER used for the mode: they mean profit and loss only.
  static Color paper(AppPalette p) => p.accent;
  static Color live(AppPalette p) => p.owlEye;

  /// Backend answer time (ms): up to 150 green, up to 400 amber, above that red. null = unknown = grey (never green by default).
  static Color ping(AppPalette p, num? ms) {
    if (ms == null) return p.textMuted;
    if (ms <= 150) return p.profit;
    if (ms <= 400) return p.warning;
    return p.loss;
  }
}
