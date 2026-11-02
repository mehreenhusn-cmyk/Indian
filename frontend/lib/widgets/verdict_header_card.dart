import 'package:flutter/material.dart';
import '../models/verdict_card.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import 'owl_pressable.dart';
import 'status_chip.dart';
import 'verdict_badge.dart';

/// Round 8: the full verdict header of ONE study. Answer first (UI rule 1): badge + title, one headline line, then the detail.
/// A card that cannot decide (NOT ENOUGH DATA) does not only say so: it shows WHAT is missing, HOW MUCH (progress bar),
/// WHEN it will be ready and WHAT TO DO (plan: "Actionable answers"). The n is printed once (UI rule 2): inside the
/// progress line for a card that needs data, in the footer for a decided card. Missing text is left out, never "None".
class VerdictHeaderCard extends StatelessWidget {
  final VerdictCard card;
  final VoidCallback? onTap;

  const VerdictHeaderCard({super.key, required this.card, this.onTap});

  Widget _line(BuildContext context, String tag, String text, {Color? color}) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 46, child: Text(tag, style: context.type.label.copyWith(color: p.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.5))),
          Expanded(child: Text(text, style: context.type.secondary.copyWith(height: 1.25, color: color))),
        ],
      ),
    );
  }

  Widget _missing(BuildContext context) {
    final p = context.palette;
    final frac = card.needN > 0 ? (card.haveN / card.needN).clamp(0.0, 1.0).toDouble() : 0.0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (card.needN > 0) ...[
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: LinearProgressIndicator(value: frac, minHeight: 5, backgroundColor: p.border, valueColor: AlwaysStoppedAnimation<Color>(p.warning)),
          ),
          const SizedBox(height: 4),
          Text('${card.progressText}${card.etaText.isEmpty ? '' : ' · ${card.etaText}'}', style: context.type.metadata),
        ],
        if (card.reasonMissing.isNotEmpty) _line(context, 'WHY', card.reasonMissing),
        if (card.nextAction.isNotEmpty) _line(context, 'DO', card.nextAction, color: p.textPrimary),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = VerdictStyle.ofContext(context, card.verdict);
    final needs = card.needsData;
    final box = Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: s.color.withOpacity(0.40)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(child: Text(card.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w800))),
              const SizedBox(width: 8),
              VerdictBadge(verdict: card.verdict, compact: true),
            ],
          ),
          if (card.headline.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(card.headline, style: context.type.primary.copyWith(fontSize: 15, fontWeight: FontWeight.w700))),
          if (card.detail.isNotEmpty && !needs) Padding(padding: const EdgeInsets.only(top: 4), child: Text(card.detail, maxLines: 4, overflow: TextOverflow.ellipsis, style: context.type.secondary.copyWith(height: 1.25))),
          if (needs) _missing(context),
          if (card.caveat.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(card.caveat, style: context.type.metadata.copyWith(fontStyle: FontStyle.italic))),
          const SizedBox(height: 8),
          Row(
            children: [
              StatusChip(ageSec: card.updatedAgoSec),
              if (!needs && card.n > 0) ...[const SizedBox(width: 8), StatusChip(text: 'n = ${card.n}')],
              const Spacer(),
              if (onTap != null) Icon(Icons.chevron_right_rounded, size: 20, color: p.textMuted),
            ],
          ),
        ],
      ),
    );
    return onTap == null ? box : OWLPressable(onTap: onTap, pressedScale: 0.985, child: box);
  }
}
