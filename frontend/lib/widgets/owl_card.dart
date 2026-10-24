import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Standard OWL surface: solid card, thin border, optional profit/loss glow.
/// Same premium look as GlassCard (soft rim in dark, soft shadow in light)
/// but no blur, so it is safe inside long live lists.
class OWLCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final bool hasPositiveGlow;
  final bool hasNegativeGlow;
  final double? width;

  const OWLCard({
    super.key,
    required this.child,
    this.padding,
    this.hasPositiveGlow = false,
    this.hasNegativeGlow = false,
    this.width,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final dark = p.brightness == Brightness.dark;
    final Color? glow = hasPositiveGlow
        ? p.positive
        : (hasNegativeGlow ? p.negative : null);

    return Container(
      width: width,
      padding: padding ?? const EdgeInsets.all(AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        gradient: dark
            ? LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  Color.alphaBlend(Colors.white.withOpacity(0.05), p.surfaceElevated),
                  p.surfaceElevated,
                ],
              )
            : null,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(
          color: glow != null ? glow.withOpacity(0.32) : p.border,
          width: 1,
        ),
        boxShadow: glow != null
            ? [BoxShadow(color: glow.withOpacity(dark ? 0.08 : 0.10), blurRadius: 14)]
            : (dark
                ? null
                : [
                    BoxShadow(
                      color: p.accent.withOpacity(0.06),
                      blurRadius: 18,
                      offset: const Offset(0, 6),
                    ),
                  ]),
      ),
      child: child,
    );
  }
}
