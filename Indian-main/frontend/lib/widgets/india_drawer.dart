import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'india_ui.dart';

/// Left slide-in menu of the India Paper terminal. Market selection lives here
/// (swipe from the left edge or tap the menu icon) - not as chips on the screen.
class IndiaDrawer extends StatelessWidget {
  final String sourceLabel;
  final VoidCallback onCrypto;
  const IndiaDrawer({super.key, required this.sourceLabel, required this.onCrypto});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    return Drawer(
      backgroundColor: p.bg,
      child: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('OWL TERMINAL', style: t.section.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.2)),
            const SizedBox(height: 2),
            Text('India Paper', style: t.metadata.copyWith(color: p.accent, fontWeight: FontWeight.w700)),
            const SizedBox(height: AppSpacing.l),
            Text('MARKET', style: t.metadata.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.1)),
            const SizedBox(height: AppSpacing.m - 2),
            MarketSwitch(onCrypto: () {
              Navigator.of(context).pop(); // close the drawer
              onCrypto(); // back to the crypto terminal
            }),
            const SizedBox(height: AppSpacing.l),
            Text('DATA SOURCE', style: t.metadata.copyWith(fontWeight: FontWeight.w700, letterSpacing: 1.1)),
            const SizedBox(height: AppSpacing.m - 2),
            Text(sourceLabel.isEmpty ? '-' : sourceLabel, style: t.secondary),
          ]),
        ),
      ),
    );
  }
}
