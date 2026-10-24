import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Premium glass surface used across the app.
///
/// Dark theme: deep navy fill, a thin light rim at the top and a faint
/// accent glow. Light theme: white card with a soft lavender shadow.
/// No blur by default (cheap inside scrolling lists). Pass `blur: true` or
/// `hero: true` only for 1-2 floating cards per screen.
class GlassCard extends StatelessWidget {
  final Widget child;
  final double? width;
  final double? height;
  final bool blur;
  final Color? glowColor;

  /// Hero cards (equity / P&L): real frosted blur + brighter top rim.
  final bool hero;

  const GlassCard({
    super.key,
    required this.child,
    this.width,
    this.height,
    this.blur = false,
    this.glowColor,
    this.hero = false,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final radius = BorderRadius.circular(AppSpacing.radiusLarge);
    final dark = p.brightness == Brightness.dark;
    final useBlur = blur || (hero && dark);
    final glow = glowColor;

    final borderColor = glow != null
        ? glow.withOpacity(dark ? 0.34 : 0.28)
        : (hero && dark ? Colors.white.withOpacity(0.12) : p.glassBorder);

    final shadows = <BoxShadow>[
      if (glow != null)
        BoxShadow(color: glow.withOpacity(dark ? 0.10 : 0.12), blurRadius: 18, spreadRadius: 0)
      else if (!dark)
        BoxShadow(
          color: p.accent.withOpacity(0.07),
          blurRadius: 22,
          offset: const Offset(0, 8),
        ),
    ];

    Widget surface = Container(
      decoration: BoxDecoration(
        color: (hero && dark) ? Colors.white.withOpacity(0.045) : p.glassFill,
        borderRadius: radius,
        border: Border.all(color: borderColor, width: 1),
        boxShadow: shadows,
        // Thin light "rim" fading from the top edge = the glass look.
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [p.glassHighlight, Colors.transparent],
          stops: const [0.0, 0.45],
        ),
      ),
      child: child,
    );

    if (useBlur) {
      surface = ClipRRect(
        borderRadius: radius,
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
          child: surface,
        ),
      );
    }

    return SizedBox(width: width, height: height, child: surface);
  }
}
