import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Label + value (+ optional sub-value) block used for stats rows.
/// The value colour is supplied by the caller from REAL data
/// (e.g. profit/loss colour derived from the live P&L sign).
class OWLMetric extends StatelessWidget {
  final String label;
  final String value;
  final String? subValue;
  final Color? valueColor;
  final bool isHero;

  const OWLMetric({
    super.key,
    required this.label,
    required this.value,
    this.subValue,
    this.valueColor,
    this.isHero = false,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label.toUpperCase(), style: t.metadata),
        const SizedBox(height: 4),
        Text(
          value,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: isHero
              ? t.hero.copyWith(color: valueColor)
              : t.primary.copyWith(
                  color: valueColor,
                  fontWeight: FontWeight.w700,
                ),
        ),
        if (subValue != null)
          Text(
            subValue!,
            style: t.metadata.copyWith(color: valueColor?.withOpacity(0.8)),
          ),
      ],
    );
  }
}
