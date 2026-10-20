import 'package:flutter/material.dart';

/// OWL Terminal design tokens (dark AMOLED exchange palette).
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
  static const Color background = Color(0xFF000000);
  static const Color surfacePrimary = Color(0xFF11151A);
  static const Color surfaceElevated = Color(0xFF181C22);
  static const Color surfaceHigher = Color(0xFF1E2329);

  // ---- Borders & accent ----
  static const Color border = Color(0xFF242A32);
  static const Color accent = Color(0xFF4C8DFF);

  // ---- Text ----
  static const Color textPrimary = Color(0xFFF5F7FA);
  static const Color textSecondary = Color(0xFF8B95A5);
  static const Color textMuted = Color(0xFF5F6875);

  // ---- Status ----
  static const Color positive = Color(0xFF0ECB81);
  static const Color negative = Color(0xFFF6465D);
  static const Color warning = Color(0xFFF0B90B);
  static const Color purple = Color(0xFF9D4EDD); // AI copilot
  static const Color owlEye = Color(0xFFFFB627); // owl-eye amber: fresh / live / attention

  // ---- Glow variants (15% / 15% / 20% alpha) ----
  static const Color positiveGlow = Color(0x260ECB81);
  static const Color negativeGlow = Color(0x26F6465D);
  static const Color accentGlow = Color(0x334C8DFF);

  // ---- Legacy aliases (do not remove: used across existing screens) ----
  static const Color obsidian = background;
  static const Color surfaceDark = surfacePrimary;
  static const Color profit = positive;
  static const Color loss = negative;
  // Solid (non-blurred) "glass" so scrolling lists stay at 60 FPS.
  static const Color glassFill = surfaceElevated;
  static const Color glassBorder = border;
  static const Color glassHighlight = Color(0x08FFFFFF);
}
