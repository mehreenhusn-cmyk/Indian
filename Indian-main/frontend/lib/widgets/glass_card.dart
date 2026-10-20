import 'dart:ui';
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Card surface used across the app.
///
/// Solid fill + hairline border by default (cheap to paint inside scrolling
/// lists). Pass `blur: true` only for floating overlays - a BackdropFilter
/// per list item is what costs frames on mid-range phones.
class GlassCard extends StatelessWidget {
  final Widget child;
  final double? width;
  final double? height;
  final bool blur;
  final Color? glowColor;

  /// Hero cards (equity / P&L): real frosted blur over the ambient glow and
  /// a brighter top rim. Use on 1-2 cards per screen, never per list item.
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

    Widget surface = Container(
      decoration: BoxDecoration(
        color: (hero && dark) ? Colors.white.withOpacity(0.04) : p.glassFill,
        borderRadius: radius,
        border: Border.all(
          color: glowColor != null
              ? glowColor!.withOpacity(0.3)
              : (hero && dark ? Colors.white.withOpacity(0.10) : p.glassBorder),
          width: 1,
        ),
        boxShadow: glowColor != null
            ? [
                BoxShadow(
                  color: glowColor!.withOpacity(0.06),
                  blurRadius: 10,
                  spreadRadius: 1,
                ),
              ]
            : null,
        gradient: LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [p.glassHighlight, Colors.transparent],
          stops: const [0.0, 0.4],
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
