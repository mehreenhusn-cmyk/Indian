import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

/// Round 7b: one small chip for "how fresh is this?" and any short status text.
///   StatusChip(text: 'PAPER', color: p.accent)          plain chip
///   StatusChip(ageSec: card.updatedAgoSec)               "updated 2 h 10 min ago" (fmtSpan, never "130 min")
/// ageSec: -1 or null = unknown (muted), under 1 day = normal, 1 day or older = amber "old".
class StatusChip extends StatelessWidget {
  final String text;
  final Color? color;
  final IconData? icon;
  final int? ageSec;

  const StatusChip({super.key, this.text = '', this.color, this.icon, this.ageSec});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    var label = text;
    var c = color ?? p.textMuted;
    if (ageSec != null) {
      final a = ageSec!;
      if (a < 0) {
        label = 'update time unknown';
      } else {
        label = a < 5 ? 'updated just now' : 'updated ${fmtSpan(a)} ago';
        if (a >= 86400) c = p.warning;
      }
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon!, size: 12, color: c), const SizedBox(width: 4)],
          Flexible(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(color: c, fontSize: 11))),
        ],
      ),
    );
  }
}
