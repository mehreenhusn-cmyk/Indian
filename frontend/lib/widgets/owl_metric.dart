import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Label + value (+ optional sub-value) block used for stats rows.
/// The value colour is supplied by the caller from REAL data
/// (e.g. profit/loss colour derived from the live P&L sign).
///
/// [boxed] puts the metric in a soft tinted box (for 2-3 metric rows);
/// default stays unboxed so existing layouts do not change.
class OWLMetric extends StatelessWidget {
  final String label;
  final String value;
  final String? subValue;
  final Color? valueColor;
  final bool isHero;
  final bool boxed;

  const OWLMetric({
    super.key,
    required this.label,
    required this.value,
    this.subValue,
    this.valueColor,
    this.isHero = false,
    this.boxed = false,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    final p = context.palette;
    final col = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: t.label),
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
    if (!boxed) return col;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.m),
      decoration: BoxDecoration(
        color: p.surfaceHigher.withOpacity(p.brightness == Brightness.dark ? 0.55 : 0.7),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border.withOpacity(0.7), width: 1),
      ),
      child: col,
    );
  }
}
