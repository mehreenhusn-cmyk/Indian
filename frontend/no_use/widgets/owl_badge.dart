import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Small LONG / SHORT style tag. `isPositive` picks profit vs loss colour.
class OWLBadge extends StatelessWidget {
  final String text;
  final bool isPositive;

  const OWLBadge({super.key, required this.text, required this.isPositive});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final color = isPositive ? p.positive : p.negative;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(
          color: color,
          fontWeight: FontWeight.w800,
          fontSize: 9,
        ),
      ),
    );
  }
}
