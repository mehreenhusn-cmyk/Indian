import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';

/// Round 7a: the verdict badge shown at the top of every study card and every study screen.
/// One pill: icon + word, coloured by VerdictStyle (so EDGE is green, LOSING red, NOT ENOUGH DATA amber,
/// DIAGNOSIS blue, NO EDGE grey). compact = smaller pill for rows and carousels.
class VerdictBadge extends StatelessWidget {
  final String verdict;
  final bool compact;

  const VerdictBadge({super.key, required this.verdict, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final s = VerdictStyle.ofContext(context, verdict);
    final size = compact ? 11.0 : 12.0;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: compact ? 8 : 10, vertical: compact ? 3 : 5),
      decoration: BoxDecoration(
        color: s.tint,
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
        border: Border.all(color: s.color.withOpacity(0.45), width: 0.8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(s.icon, size: size + 2, color: s.color),
          const SizedBox(width: 5),
          Text(
            s.label,
            maxLines: 1,
            style: context.type.label.copyWith(color: s.color, fontSize: size, fontWeight: FontWeight.w700, letterSpacing: 0.3),
          ),
        ],
      ),
    );
  }
}
