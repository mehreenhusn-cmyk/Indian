import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Part P-E: ONE icon style for list rows: a small rounded square tinted with a soft version of its colour, the icon inside in the full colour.
/// Used as the [leading] of an OwlRow (the More page). The colour is a GROUP colour (one per group of rows), never red / green (those mean profit and loss only).
/// Flat: a 1 px soft edge, no shadow. Dart NOT compiled.
class OwlIconTile extends StatelessWidget {
  final IconData icon;
  final Color color;
  final double size;

  const OwlIconTile(this.icon, this.color, {super.key, this.size = 36});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium - 2),
        border: Border.all(color: color.withOpacity(0.22)),
      ),
      child: Icon(icon, size: size * 0.56, color: color),
    );
  }
}
