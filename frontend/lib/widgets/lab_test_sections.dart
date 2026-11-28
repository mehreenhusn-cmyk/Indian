import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import 'indicator_lab_cards.dart';
import 'owl_card.dart';
import 'verdict_badge.dart';

/// R14a: the SECTIONS of one test's detail page (the page itself = screens/lab_test_detail_screen.dart, R14b). Every section takes ONE [LabTest] (one TestResult of GET /api/v2/lab_results) and shows only what the backend sent, never a guessed number.
/// Order on the page: verdict header, train vs unseen, numbers, what is missing (only when it needs data), caveat, raw data (collapsed). Read only: a verdict is evidence, never an order. Dart NOT compiled (the APK build is the proof).
const Map<String, String> kLabMeaning = {
  'EDGE': 'It held up on days it was not tuned on. Still paper results: evidence, not an order.',
  'LOSING': 'After fees it lost money on enough cases. Do not use it.',
  'DIAGNOSIS_ONLY': 'It describes what happened. A hint, not proof and not a filter.',
  'NO_EDGE': 'Tested: nothing clearly better than the plain baseline.',
  'NOT_ENOUGH_DATA': 'Cannot decide yet. See what is missing below.',
};

String _sg(double v, [int d = 2]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

Widget _box(BuildContext context, {required List<Widget> children, Color? edge}) {
  final p = context.palette;
  return Container(
    width: double.infinity,
    margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
    padding: const EdgeInsets.all(AppSpacing.cardPad),
    decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: edge ?? p.border)),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
  );
}

Widget _title(BuildContext context, String t) => Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(t, style: context.type.label.copyWith(color: context.palette.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.8)));

Widget _line(BuildContext context, String label, String value, {Color? c}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Expanded(child: Text(label, style: context.type.secondary)),
        Text(value, style: context.type.secondary.copyWith(color: c ?? context.palette.textPrimary, fontWeight: FontWeight.w700)),
      ]),
    );

/// 1. The answer first: verdict badge, title, headline and ONE plain sentence of what the verdict word means.
class LabVerdictHeader extends StatelessWidget {
  final LabTest t;
  const LabVerdictHeader({super.key, required this.t});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final vs = VerdictStyle.of(p, t.verdict);
    return _box(context, edge: vs.color.withOpacity(0.6), children: [
      Row(children: [
        VerdictBadge(verdict: t.verdict),
        const SizedBox(width: 8),
        Expanded(child: Text(labFamily(t.family) + (t.side.isEmpty ? '' : '  |  ${t.side}'), style: context.type.metadata, overflow: TextOverflow.ellipsis)),
      ]),
      const SizedBox(height: 8),
      Text(t.title, style: context.type.section.copyWith(fontWeight: FontWeight.w800)),
      if (t.headline.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(t.headline, style: context.type.primary)),
      const SizedBox(height: 6),
      Text(kLabMeaning[t.verdict] ?? '', style: context.type.secondary.copyWith(color: p.textSecondary)),
      if (t.detail.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(t.detail, style: context.type.secondary)),
      if (t.context.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Setting: ${t.context}', style: context.type.metadata)),
    ]);
  }
}

/// 2. TRAIN vs UNSEEN: the lift on the older days (the rule was tuned on them) next to the lift on the unseen days (judged once). Same sign on both = the evidence is not a one-day accident.
class LabTrainTestSection extends StatelessWidget {
  final LabTest t;
  const LabTrainTestSection({super.key, required this.t});

  Widget _col(BuildContext context, String label, String sub, double v, double scale) {
    final p = context.palette;
    final c = v >= 0 ? p.profit : p.loss;
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: context.type.metadata.copyWith(fontWeight: FontWeight.w700)),
        Text(sub, style: context.type.metadata),
        const SizedBox(height: 4),
        Text('${_sg(v)} R', style: context.type.section.copyWith(color: c, fontWeight: FontWeight.w800)),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: Stack(children: [Container(height: 6, color: p.border), FractionallySizedBox(widthFactor: (v.abs() / scale).clamp(0.02, 1.0), child: Container(height: 6, color: c))]),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final a = t.liftTrain, b = t.liftTest;
    if (a == null || b == null) {
      return _box(context, children: [
        _title(context, 'OLDER DAYS vs UNSEEN DAYS'),
        Text('This test has no older / unseen split. It is a replay or a description of the past, so it can never be called EDGE by itself.', style: context.type.secondary),
      ]);
    }
    final scale = [a.abs(), b.abs(), 0.01].reduce((x, y) => x > y ? x : y);
    final same = (a >= 0) == (b >= 0);
    final shrank = same && a != 0 && b.abs() < a.abs() * 0.5;
    return _box(context, children: [
      _title(context, 'OLDER DAYS vs UNSEEN DAYS'),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _col(context, 'OLDER DAYS', 'rule tuned on these', a, scale),
        const SizedBox(width: 16),
        _col(context, 'UNSEEN DAYS', 'judged once', b, scale),
      ]),
      const SizedBox(height: 8),
      _line(context, 'Same sign on both', same ? 'yes' : 'no', c: same ? p.profit : p.loss),
      Text(
        !same
            ? 'It only worked on the days it was tuned on. That is the usual sign of luck.'
            : (shrank ? 'The gain shrank by more than half on unseen days: be careful.' : 'The unseen days point the same way as the older days.'),
        style: context.type.secondary.copyWith(color: !same ? p.loss : (shrank ? p.warning : null)),
      ),
      Padding(padding: const EdgeInsets.only(top: 4), child: Text('Lift = R per trade above the plain baseline, after fees.', style: context.type.metadata)),
    ]);
  }
}

/// 3. THE NUMBERS: only the ones that exist. Cases are shown as "have of need" with a bar while the test still needs data.
class LabNumbersSection extends StatelessWidget {
  final LabTest t;
  const LabNumbersSection({super.key, required this.t});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final frac = t.needN > 0 ? (t.n / t.needN).clamp(0.0, 1.0) : null;
    return _box(context, children: [
      _title(context, 'THE NUMBERS'),
      _line(context, 'Cases', t.needN > 0 ? '${t.n} of ${t.needN} needed' : '${t.n}'),
      if (frac != null && t.needsData)
        Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: ClipRRect(borderRadius: BorderRadius.circular(3), child: Stack(children: [Container(height: 6, color: p.border), FractionallySizedBox(widthFactor: frac, child: Container(height: 6, color: p.warning))])),
        ),
      if (t.winPct != null) _line(context, 'Win rate', '${t.winPct!.toStringAsFixed(1)}%'),
      if (t.expR != null) _line(context, 'R per trade, after fees', '${_sg(t.expR!, 3)} R', c: t.expR! >= 0 ? p.profit : p.loss),
      if (t.liftR != null) _line(context, 'Lift above the baseline', '${_sg(t.liftR!, 3)} R', c: t.liftR! >= 0 ? p.profit : p.loss),
      if (t.coinsBeatPct != null) _line(context, 'Coins that beat the baseline', '${t.coinsBeatPct!.toStringAsFixed(0)}%'),
      if (t.winPct == null && t.expR == null && t.liftR == null && t.coinsBeatPct == null) Text('The backend sent no further number for this test.', style: context.type.metadata),
    ]);
  }
}

/// 4. WHAT IS MISSING: only for NOT_ENOUGH_DATA (UI rule 4): what, how much, what to do.
class LabMissingSection extends StatelessWidget {
  final LabTest t;
  const LabMissingSection({super.key, required this.t});

  @override
  Widget build(BuildContext context) {
    if (!t.needsData) return const SizedBox.shrink();
    final p = context.palette;
    return _box(context, edge: p.warning.withOpacity(0.5), children: [
      _title(context, 'WHAT IS MISSING'),
      if (t.reasonMissing.isNotEmpty) Text(t.reasonMissing, style: context.type.secondary.copyWith(color: p.textPrimary)),
      if (t.needN > 0) Padding(padding: const EdgeInsets.only(top: 4), child: Text('${t.n} of ${t.needN} cases so far (${t.needN > t.n ? t.needN - t.n : 0} to go).', style: context.type.secondary)),
      if (t.nextAction.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('What to do: ${t.nextAction}', style: context.type.secondary)),
    ]);
  }
}

/// 5. HONESTY: the caveat of the test, whether the Sniper uses it, where the number comes from and how old it is.
class LabCaveatSection extends StatelessWidget {
  final LabTest t;
  const LabCaveatSection({super.key, required this.t});

  @override
  Widget build(BuildContext context) {
    return _box(context, children: [
      _title(context, 'READ THIS FIRST'),
      if (t.caveat.isNotEmpty) Text(t.caveat, style: context.type.secondary),
      const SizedBox(height: 6),
      _line(context, 'Sniper uses it', t.useInSniper ? 'yes' : 'no'),
      _line(context, 'Updated', labAgo(t.agoSec)),
      if (t.source.isNotEmpty) _line(context, 'Source', t.source),
    ]);
  }
}

/// 6. RAW DATA, collapsed: every key the backend sent for this test, one line each (long values are cut at 160 characters).
class LabRawSection extends StatelessWidget {
  final LabTest t;
  const LabRawSection({super.key, required this.t});

  static String _v(dynamic v) {
    final s = '$v';
    return s.length > 160 ? '${s.substring(0, 160)}...' : s;
  }

  @override
  Widget build(BuildContext context) {
    final keys = t.raw.keys.toList()..sort();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      child: OwlFold(
        title: 'RAW DATA',
        headline: '${keys.length} fields as the backend sent them',
        children: [
          for (final k in keys)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Text('$k: ${_v(t.raw[k])}', style: context.type.metadata.copyWith(fontFamily: 'monospace')),
            ),
        ],
      ),
    );
  }
}
