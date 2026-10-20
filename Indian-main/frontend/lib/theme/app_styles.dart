import 'dart:ui';
import 'package:flutter/material.dart';
import 'app_theme.dart';

/// Reusable design system decorators and typography styles for the crypto
/// exchange terminal. Kept in one place so widgets share one definition of
/// the card surface / number style.
class AppStyles {
  /// Card surface decoration: solid fill + 1px border, optional soft glow.
  /// No default drop-shadow (keeps lists cheap to paint at 60 FPS).
  static BoxDecoration glassDecoration({
    Color fillColor = AppColors.glassFill,
    Color borderColor = AppColors.glassBorder,
    double borderRadius = 12.0,
    Color? glowColor,
    double glowRadius = 10.0,
  }) {
    return BoxDecoration(
      color: fillColor,
      borderRadius: BorderRadius.circular(borderRadius),
      border: Border.all(
        color: glowColor != null ? glowColor.withOpacity(0.3) : borderColor,
        width: 1.0,
      ),
      boxShadow: glowColor != null
          ? [
              BoxShadow(
                color: glowColor.withOpacity(0.06),
                blurRadius: glowRadius,
                spreadRadius: 1,
              ),
            ]
          : null,
    );
  }

  /// Card wrapper. Solid by default; pass `blur: true` ONLY for overlays
  /// (dialogs, sheets) - BackdropFilter inside scrolling lists is expensive.
  static Widget glassCard({
    required Widget child,
    EdgeInsetsGeometry padding = const EdgeInsets.all(12),
    EdgeInsetsGeometry margin = EdgeInsets.zero,
    Color fillColor = AppColors.glassFill,
    Color borderColor = AppColors.glassBorder,
    double borderRadius = 12.0,
    Color? glowColor,
    VoidCallback? onTap,
    bool blur = false,
  }) {
    Widget body = Container(
      padding: padding,
      decoration: glassDecoration(
        fillColor: fillColor,
        borderColor: borderColor,
        borderRadius: borderRadius,
        glowColor: glowColor,
      ),
      child: child,
    );

    if (blur) {
      body = ClipRRect(
        borderRadius: BorderRadius.circular(borderRadius),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 12, sigmaY: 12),
          child: body,
        ),
      );
    }

    if (onTap != null) {
      return Container(
        margin: margin,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(borderRadius),
          child: body,
        ),
      );
    }

    return Container(margin: margin, child: body);
  }

  /// Number style for prices, orders & P&L: Inter with tabular figures so
  /// digits keep a fixed width while live values tick.
  static TextStyle monoStyle({
    double fontSize = 13.0,
    FontWeight fontWeight = FontWeight.w600,
    Color color = AppColors.textPrimary,
    double? letterSpacing,
  }) {
    return TextStyle(
      fontFamily: AppTypography.fontFamily,
      fontFeatures: const [FontFeature.tabularFigures()],
      fontSize: fontSize,
      fontWeight: fontWeight,
      color: color,
      letterSpacing: letterSpacing,
    );
  }

  /// Status pill badge decoration.
  static BoxDecoration pillDecoration({
    required Color color,
    double opacity = 0.12,
    double borderRadius = 20.0,
  }) {
    return BoxDecoration(
      color: color.withOpacity(opacity),
      borderRadius: BorderRadius.circular(borderRadius),
      border: Border.all(color: color.withOpacity(0.35), width: 1),
    );
  }
}
