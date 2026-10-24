import 'package:flutter/material.dart';

import '../screens/dual_bot_screen.dart';
import '../screens/tag_lab_screen.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';
import 'owl_route.dart';

/// Small Dashboard tile that opens the Tag Lab screen. Always visible (it does not depend on the
/// hidden Strategy Doctor flag). No network calls here, so it never slows the Dashboard.
class TagLabTile extends StatelessWidget {
  const TagLabTile({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: OWLPressable(
        onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => const TagLabScreen())),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: p.accent.withOpacity(0.55)),
          ),
          child: Row(children: [
            Icon(Icons.hub_outlined, size: 20, color: p.accent),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Tag Lab', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
                Text('Which mix of both indicators makes money?', style: context.type.metadata),
              ]),
            ),
            Icon(Icons.chevron_right, color: p.textSecondary),
          ]),
        ),
      ),
    );
  }
}

/// Dashboard tile for the Dual Bot (paper bot that learns from both indicators). No network call here.
class DualBotTile extends StatelessWidget {
  const DualBotTile({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: OWLPressable(
        onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => const DualBotScreen())),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: p.accent.withOpacity(0.55)),
          ),
          child: Row(children: [
            Icon(Icons.psychology_alt_outlined, size: 20, color: p.accent),
            const SizedBox(width: 10),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Dual Bot', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
                Text('Paper bot that learns from both indicators', style: context.type.metadata),
              ]),
            ),
            Icon(Icons.chevron_right, color: p.textSecondary),
          ]),
        ),
      ),
    );
  }
}
