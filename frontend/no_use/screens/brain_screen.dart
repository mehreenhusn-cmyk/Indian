import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/smart_brain_view.dart';

/// NEXT-4: the Brain as its own bottom tab. It used to be only a chip inside the Dual Bot screen (that chip stays, nothing is removed).
/// Same Brain view, same data (GET /api/smart_brain), paper only: nothing here controls a trade.
class BrainScreen extends StatelessWidget {
  const BrainScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
          children: [
            Text('Brain', style: context.type.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
            const SizedBox(height: 2),
            Text('What the Brain has learned from the trades. Paper only, nothing here trades.', style: context.type.metadata),
            const SizedBox(height: AppSpacing.l),
            const SmartBrainView(),
          ],
        ),
      ),
    );
  }
}
