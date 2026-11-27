import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_hero_card.dart';

/// Part 11 (D2b, 28 Nov 2026): one quick-access tile of the More page = a tinted icon over a short name. Plain widget, no provider.
/// tone: 'good' green, 'bad' red, 'warn' amber, anything else = the app accent. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.
class MoreQuickItem {
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final String tone;

  const MoreQuickItem({required this.icon, required this.label, required this.onTap, this.tone = ''});
}

/// A row of 2 to 4 quick tiles at the top of the More page (the things used most). Every tile is also a normal row further down: nothing moved, nothing deleted.
class MoreQuickTiles extends StatelessWidget {
  final List<MoreQuickItem> items;

  const MoreQuickTiles({super.key, required this.items});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Row(children: [
      for (var i = 0; i < items.length; i++) ...[
        if (i > 0) const SizedBox(width: AppSpacing.s),
        Expanded(child: _tile(p, items[i])),
      ],
    ]);
  }

  Widget _tile(AppPalette p, MoreQuickItem it) {
    final c = owlToneColor(p, it.tone);
    return Semantics(
      button: true,
      label: it.label,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          onTap: it.onTap,
          child: Container(
            padding: const EdgeInsets.symmetric(vertical: 12),
            decoration: BoxDecoration(
              color: Color.alphaBlend(c.withOpacity(0.07), p.surface),
              borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
              border: Border.all(color: c.withOpacity(0.22)),
            ),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(11)),
                child: Icon(it.icon, size: 20, color: c),
              ),
              const SizedBox(height: 6),
              Text(it.label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
            ]),
          ),
        ),
      ),
    );
  }
}
