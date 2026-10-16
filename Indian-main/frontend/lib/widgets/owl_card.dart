import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Standard OWL surface: solid card, 1px border, optional profit/loss glow.
/// No blur and no default shadow, so it is safe inside long live lists.
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
    final Color? glow = hasPositiveGlow
        ? p.positive
        : (hasNegativeGlow ? p.negative : null);

    return Container(
      width: width,
      padding: padding ?? const EdgeInsets.all(AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        // Very faint top-down sheen, dark theme only (light theme stays flat).
        gradient: Theme.of(context).brightness == Brightness.dark
            ? LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color.alphaBlend(Colors.white.withOpacity(0.035), p.surfaceElevated), p.surfaceElevated],
              )
            : null,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(
          color: glow != null ? glow.withOpacity(0.3) : p.border,
          width: 1,
        ),
        boxShadow: glow != null
            ? [
                BoxShadow(
                  color: glow.withOpacity(0.05),
                  blurRadius: 10,
                  spreadRadius: 1,
                ),
              ]
            : null,
      ),
      child: child,
    );
  }
}
