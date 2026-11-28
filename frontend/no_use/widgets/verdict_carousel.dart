import 'package:flutter/material.dart';
import '../models/verdict_card.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import 'owl_pressable.dart';
import 'status_chip.dart';
import 'verdict_badge.dart';

/// Round 8: a horizontal row of compact verdict cards (one swipe = one study), the top of the Study Lab hub.
/// Order: EDGE first, LOSING second (the two words that need action), then DIAGNOSIS, NO EDGE, and NOT ENOUGH DATA last.
/// Tap a card = onOpen(card) (the hub opens that study's screen). An empty list prints ONE calm line, never a wall of zeros.
class VerdictCarousel extends StatelessWidget {
  final List<VerdictCard> cards;
  final void Function(VerdictCard card)? onOpen;
  final double height;

  const VerdictCarousel({super.key, required this.cards, this.onOpen, this.height = 150});

  static const List<String> _order = ['EDGE', 'LOSING', 'DIAGNOSIS_ONLY', 'NO_EDGE', 'NOT_ENOUGH_DATA'];

  /// Same cards, sorted by the verdict order above (a stable sort: equal verdicts keep the order the backend sent).
  static List<VerdictCard> sorted(List<VerdictCard> src) {
    final idx = <VerdictCard, int>{for (var i = 0; i < src.length; i++) src[i]: i};
    final out = [...src];
    out.sort((a, b) {
      final d = _order.indexOf(VerdictStyle.clean(a.verdict)) - _order.indexOf(VerdictStyle.clean(b.verdict));
      return d != 0 ? d : idx[a]! - idx[b]!;
    });
    return out;
  }

  Widget _tile(BuildContext context, VerdictCard c) {
    final p = context.palette;
    final s = VerdictStyle.ofContext(context, c.verdict);
    return OWLPressable(
      onTap: onOpen == null ? null : () => onOpen!(c),
      pressedScale: 0.97,
      child: Container(
        width: 224,
        padding: const EdgeInsets.all(AppSpacing.cardPad),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: s.color.withOpacity(0.40)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            VerdictBadge(verdict: c.verdict, compact: true),
            const SizedBox(height: 8),
            Text(c.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(color: p.textMuted)),
            const SizedBox(height: 2),
            Expanded(child: Text(c.headline.isEmpty ? 'n/a' : c.headline, maxLines: 3, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.2))),
            Row(
              children: [
                Flexible(child: StatusChip(ageSec: c.updatedAgoSec)),
                if (c.n > 0) ...[const SizedBox(width: 6), Text('n ${c.n}', style: context.type.metadata)],
              ],
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (cards.isEmpty) {
      return Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.cardPad),
        decoration: BoxDecoration(color: context.palette.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: context.palette.border)),
        child: Text('No study has enough data for a verdict yet.', style: context.type.secondary),
      );
    }
    final list = sorted(cards);
    return SizedBox(
      height: height,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        physics: const BouncingScrollPhysics(),
        itemCount: list.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.cardGap),
        itemBuilder: (context, i) => _tile(context, list[i]),
      ),
    );
  }
}
