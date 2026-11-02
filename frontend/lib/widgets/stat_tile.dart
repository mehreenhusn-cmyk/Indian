import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Round 7b: one compact number tile: dim label on top, big number, optional small line under it.
/// tone: 'good' = green, 'bad' = red, 'warn' = amber, anything else = normal text colour.
/// Round 10b: the number uses context.type.number (20 pt). Use it in a Row / Wrap of 2 to 4 tiles; the number is the hero, so it is never printed twice on a screen (UI rule 2).
class StatTile extends StatelessWidget {
  final String label;
  final String value;
  final String sub;
  final String tone;

  const StatTile({super.key, required this.label, required this.value, this.sub = '', this.tone = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final Color c = tone == 'good' ? p.profit : tone == 'bad' ? p.loss : tone == 'warn' ? p.warning : p.textPrimary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.s + 2),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label),
          const SizedBox(height: 2),
          Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.number.copyWith(color: c)),
          if (sub.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
        ],
      ),
    );
  }
}
