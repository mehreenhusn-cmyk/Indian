import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/study_verdict_header.dart';
import '../widgets/tag_lab_card.dart';

/// Tag Lab screen. Opened from the Dashboard card. It only shows the Tag Lab result
/// (which mix of the main chart signal, the Z candle, the Z-EMA cloud and TSI earned money).
/// Read-only: nothing here trades or changes the bot.
class TagLabScreen extends StatelessWidget {
  const TagLabScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text('Tag Lab', style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const StudyVerdictHeader(
              cardId: 'tag_lab',
              why: 'Many indicator mixes look good on old candles by pure luck.',
              what: 'Replays old candles and counts which mix made money, then compares it with the best of random shuffles.',
            ),
            const SizedBox(height: 12),
            Text(
              'Tap Run test. The backend replays old candles in its own process and counts which indicator mix made money. '
              'It does not trade and does not touch your bot.',
              style: context.type.secondary,
            ),
            const SizedBox(height: 12),
            const TagLabCard(),
          ],
        ),
      ),
    );
  }
}
