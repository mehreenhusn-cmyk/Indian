import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Dot + label pill, e.g. LIVE / OFFLINE / PAPER, or one trade state:
/// OPEN / WON / LOST / SKIPPED (use [OWLStatusPill.trade]).
/// The colour comes from the caller so it always reflects real state.
class OWLStatusPill extends StatelessWidget {
  final String text;
  final Color color;
  final bool showDot;

  const OWLStatusPill({
    super.key,
    required this.text,
    required this.color,
    this.showDot = true,
  });

  /// One tag style for every trade state. [status] is matched ignoring case:
  /// open/running -> accent, won/profit/tp -> green, lost/loss/sl -> red,
  /// anything else (skipped, closed) -> grey.
  static Widget trade(BuildContext context, String status) {
    final p = context.palette;
    final s = status.toLowerCase();
    Color c;
    String label;
    if (s == 'open' || s == 'running' || s == 'active') {
      c = p.accent;
      label = 'OPEN';
    } else if (s == 'won' || s == 'win' || s == 'profit' || s == 'tp') {
      c = p.profit;
      label = 'WON';
    } else if (s == 'lost' || s == 'loss' || s == 'sl') {
      c = p.loss;
      label = 'LOST';
    } else if (s == 'skipped' || s == 'skip') {
      c = p.textMuted;
      label = 'SKIPPED';
    } else {
      c = p.textMuted;
      label = status.toUpperCase();
    }
    return OWLStatusPill(text: label, color: c);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.s + 1, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
        border: Border.all(color: color.withOpacity(0.30), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (showDot) ...[
            Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
            ),
            const SizedBox(width: 6),
          ],
          Text(
            text.toUpperCase(),
            style: AppTypography.metadata.copyWith(
              color: color,
              fontWeight: FontWeight.bold,
              letterSpacing: 0.3,
            ),
          ),
        ],
      ),
    );
  }
}
