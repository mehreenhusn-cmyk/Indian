import 'package:flutter/material.dart';

/// OWL Terminal design tokens (dark AMOLED exchange palette). R23: canvas is PURE BLACK, surfaces and the 1px lines are a little darker (terminal look); Light is untouched.
///
/// Single source of truth for every static color. The legacy names used by
/// the existing screens (obsidian, surfaceDark, glass*, profit, loss, accent,
/// purple, warning, text*) are kept as aliases so untouched files keep
/// compiling and automatically pick up the new look.
///
/// NOTE: these are dark-theme constants. Widgets that must also render in the
/// light theme read `context.palette` (see app_theme.dart) instead.
class AppColors {
  AppColors._();

  // ---- Backgrounds (true-black canvas for AMOLED, raised surfaces above) ----
  // Ink-navy canvas: still near-black for AMOLED, but with a cool tint so
  // glass cards have something to glow against (premium glass look).
  static const Color background = Color(0xFF000000);
  static const Color surfacePrimary = Color(0xFF0C1017);
  static const Color surfaceElevated = Color(0xFF131923);
  static const Color surfaceHigher = Color(0xFF1A2230);

  // ---- Borders & accent ----
  static const Color border = Color(0xFF1E2633);
  // One calm blue-violet for tabs, buttons and selected states.
  static const Color accent = Color(0xFF7388FF);

  // ---- Text ----
  static const Color textPrimary = Color(0xFFE6EAF2);
  static const Color textSecondary = Color(0xFF9AA6BC);
  static const Color textMuted = Color(0xFF7683A0);

  // ---- Status ----
  static const Color positive = Color(0xFF0ECB81);
  static const Color negative = Color(0xFFF6465D);
  static const Color warning = Color(0xFFF0B90B);
  static const Color purple = Color(0xFF9D4EDD); // AI copilot
  static const Color owlEye = Color(0xFFFFB627); // owl-eye amber: fresh / live / attention

  // ---- Glow variants (15% / 15% / 20% alpha) ----
  static const Color positiveGlow = Color(0x260ECB81);
  static const Color negativeGlow = Color(0x26F6465D);
  static const Color accentGlow = Color(0x337388FF);

  // ---- Legacy aliases (do not remove: used across existing screens) ----
  static const Color obsidian = background;
  static const Color surfaceDark = surfacePrimary;
  static const Color profit = positive;
  static const Color loss = negative;
  // Solid (non-blurred) "glass" so scrolling lists stay at 60 FPS.
  static const Color glassFill = surfaceElevated;
  static const Color glassBorder = border;
  static const Color glassHighlight = Color(0x0DFFFFFF);
}
