import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/indicator_lab_cards.dart';
import '../widgets/lab_test_sections.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_route.dart';
import '../widgets/verdict_badge.dart';

/// R14b: the DETAIL page of ONE test of the Study Lab results board (opened by "Open full detail" on a card of screens/indicator_lab_screen.dart).
/// Order: verdict header, older vs unseen days, numbers, what is missing (only when it needs data), read-this-first, the other tests of the same study (tap = open that one), raw data (collapsed).
/// Everything shown comes from the ONE LabTest the board already holds, so this page asks the backend for nothing and works as long as the board has data. Read only: a verdict is evidence, never an order. Dart NOT compiled (the APK build is the proof).
class LabTestDetailScreen extends StatelessWidget {
  static const _maxSiblings = 8;
  final LabTest test;
  final List<LabTest> siblings; // the other tests of the same study (family), any order

  const LabTestDetailScreen({super.key, required this.test, this.siblings = const <LabTest>[]});

  void _open(BuildContext context, LabTest t) {
    // the new page keeps the same study list (this test replaces the one we open)
    final next = [for (final s in [...siblings, test]) if (s.id != t.id) s];
    Navigator.of(context).push(OwlRoute(builder: (_) => LabTestDetailScreen(test: t, siblings: next)));
  }

  Widget _row(BuildContext context, LabTest t) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: OWLPressable(
        onTap: () => _open(context, t),
        pressedScale: 0.985,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          decoration: BoxDecoration(color: p.bg, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
          child: Row(children: [
            VerdictBadge(verdict: t.verdict, compact: true),
            const SizedBox(width: 8),
            Expanded(child: Text(t.headline.isNotEmpty ? t.headline : t.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.secondary.copyWith(color: p.textPrimary))),
            Icon(Icons.chevron_right_rounded, size: 20, color: p.textMuted),
          ]),
        ),
      ),
    );
  }

  Widget _siblings(BuildContext context) {
    if (siblings.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    final list = [...siblings]..sort((a, b) => LabTest.rank(a.verdict).compareTo(LabTest.rank(b.verdict)));
    final shown = list.take(_maxSiblings).toList();
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Text('OTHER TESTS OF ${labFamily(test.family).toUpperCase()} (${list.length})', style: context.type.label.copyWith(color: p.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.8)),
        ),
        for (final t in shown) _row(context, t),
        if (list.length > shown.length) Text('${list.length - shown.length} more on the results board.', style: context.type.metadata),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('Test detail', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
      body: ListView(
        physics: const BouncingScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.screenPad, AppSpacing.s, AppSpacing.screenPad, AppSpacing.huge),
        children: [
          LabVerdictHeader(t: test),
          LabTrainTestSection(t: test),
          LabNumbersSection(t: test),
          LabMissingSection(t: test),
          LabCaveatSection(t: test),
          _siblings(context),
          LabRawSection(t: test),
          Text('Paper only. A verdict is evidence, not an order: no test here changes a trade.', style: context.type.metadata),
        ],
      ),
    );
  }
}
