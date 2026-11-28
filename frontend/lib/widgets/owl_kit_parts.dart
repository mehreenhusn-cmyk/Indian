import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/app_typography.dart';
import 'owl_hero_card.dart';

/// Part 8 (D1a, 28 Nov 2026): shared UI kit, piece 2 = SECTION HEADER + STAT TILE + a row of tiles.
/// Every screen of the redesign (parts 10 to 19) uses these instead of writing its own heading / number box.
/// The older StatTile (widgets/stat_tile.dart) is NOT removed: screens move to OwlStatTile one by one. Plain widgets, no provider, no network.
/// Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

/// Section heading: bold title, one short muted line next to it, optional small action on the right ("Sab dekho").
class OwlSectionHeader extends StatelessWidget {
  final String title;
  final String sub;
  final String actionLabel;
  final VoidCallback? onAction;

  const OwlSectionHeader({super.key, required this.title, this.sub = '', this.actionLabel = '', this.onAction});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: 4, bottom: 8),
      child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
        Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(width: 8),
        Expanded(child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
        if (actionLabel.isNotEmpty && onAction != null)
          GestureDetector(
            onTap: onAction,
            behavior: HitTestBehavior.opaque,
            child: Padding(padding: const EdgeInsets.only(left: 8), child: Text(actionLabel, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.accent))),
          ),
      ]),
    );
  }
}

/// One number tile: small muted label, big number, optional small line. A tone tints the tile ('good' green, 'bad' red, 'warn' amber, '' neutral).
class OwlStatTile extends StatelessWidget {
  final String label;
  final String value;
  final String sub;
  final String tone;
  final IconData? icon;

  const OwlStatTile({super.key, required this.label, required this.value, this.sub = '', this.tone = '', this.icon});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final tinted = tone.isNotEmpty;
    final c = owlToneColor(p, tone);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: 10),
      decoration: BoxDecoration(
        color: tinted ? Color.alphaBlend(c.withOpacity(0.08), p.surface) : p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
        border: Border.all(color: tinted ? c.withOpacity(0.25) : p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Row(children: [
          Expanded(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: p.textMuted))),
          if (icon != null) Icon(icon, size: 15, color: tinted ? c : p.textMuted),
        ]),
        const SizedBox(height: 3),
        Text(value, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppTypography.number.copyWith(fontSize: 20, color: tinted ? c : p.textPrimary)),
        if (sub.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 10.5, color: p.textMuted))),
      ]),
    );
  }
}

/// 2 to 4 tiles side by side, same width and the same height.
class OwlStatRow extends StatelessWidget {
  final List<Widget> tiles;
  const OwlStatRow({super.key, required this.tiles});

  @override
  Widget build(BuildContext context) {
    return IntrinsicHeight(
      child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (var i = 0; i < tiles.length; i++) ...[
          if (i > 0) const SizedBox(width: AppSpacing.s),
          Expanded(child: tiles[i]),
        ],
      ]),
    );
  }
}
