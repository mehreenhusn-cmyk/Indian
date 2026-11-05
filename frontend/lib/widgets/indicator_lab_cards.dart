import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import 'owl_pressable.dart';
import 'verdict_badge.dart';

/// R13: the pieces of the Study Lab RESULTS BOARD (screens/indicator_lab_screen.dart). Data = GET /api/v2/lab_results (read only, R9 + R10 + R11 backend).
/// One [LabTest] = one test (one TestResult of v2_testresults.py). Read only: a verdict is evidence, never an order, and no test here changes a trade.
/// Dart NOT compiled (the APK build is the proof).
class LabTest {
  final String id, family, title, side, context, verdict, headline, detail, caveat, reasonMissing, nextAction, source;
  final int n, needN, agoSec;
  final double? winPct, expR, liftR, liftTrain, liftTest, coinsBeatPct;
  final bool useInSniper;
  final Map<String, dynamic> raw; // R14a: the whole TestResult as the backend sent it (shown collapsed on the detail screen)

  const LabTest({
    required this.id,
    required this.family,
    required this.title,
    required this.side,
    required this.context,
    required this.verdict,
    required this.headline,
    required this.detail,
    required this.caveat,
    required this.reasonMissing,
    required this.nextAction,
    required this.source,
    required this.n,
    required this.needN,
    required this.agoSec,
    required this.useInSniper,
    this.raw = const <String, dynamic>{},
    this.winPct,
    this.expR,
    this.liftR,
    this.liftTrain,
    this.liftTest,
    this.coinsBeatPct,
  });

  static double? _d(dynamic v) => v is num && v.isFinite ? v.toDouble() : null;
  static int _i(dynamic v) => v is num && v.isFinite ? v.toInt() : 0;
  static String _s(dynamic v) => v == null ? '' : '$v';

  factory LabTest.fromJson(Map<String, dynamic> j) => LabTest(
        id: _s(j['id']),
        family: _s(j['family']),
        title: _s(j['title']),
        side: _s(j['side']),
        context: _s(j['context']),
        verdict: VerdictStyle.clean(_s(j['verdict'])),
        headline: _s(j['headline']),
        detail: _s(j['detail']),
        caveat: _s(j['caveat']),
        reasonMissing: _s(j['reason_missing']),
        nextAction: _s(j['next_action']),
        source: _s(j['source']),
        n: _i(j['have_n'] ?? j['n']),
        needN: _i(j['need_n']),
        agoSec: j['updated_ago_sec'] is num ? (j['updated_ago_sec'] as num).toInt() : -1,
        useInSniper: j['use_in_sniper'] == true,
        raw: j,
        winPct: _d(j['win_pct']),
        expR: _d(j['exp_r']),
        liftR: _d(j['lift_r']),
        liftTrain: _d(j['lift_train']),
        liftTest: _d(j['lift_test']),
        coinsBeatPct: _d(j['coins_beat_pct']),
      );

  static List<LabTest> listFrom(dynamic v) => v is List ? [for (final x in v) if (x is Map) LabTest.fromJson(Map<String, dynamic>.from(x))] : <LabTest>[];

  bool get needsData => verdict == 'NOT_ENOUGH_DATA';

  /// Part 13b: EDGE first, then CANDIDATE (= DIAGNOSIS_ONLY on the wire: looked good, not proven), NOT ENOUGH DATA, NO EDGE, LOSING (the backend order is kept inside one verdict).
  static int rank(String v) => const ['EDGE', 'DIAGNOSIS_ONLY', 'NOT_ENOUGH_DATA', 'NO_EDGE', 'LOSING'].indexOf(v);
}

/// Plain names for the families of the backend (the word on a card and on a chip).
const Map<String, String> kLabFamilies = {
  'zsma': 'Z-SMA',
  'sd_bands': 'SD bands',
  'pairs': 'Indicator pairs',
  'combos': 'Combos',
  'brain': 'Brain',
  'exit': 'Exit and hold',
  'dual': 'Dual split',
  'ignored': 'Skipped signals',
  'wick': 'Stop wick',
  'regime': 'Volatility',
  'scalp': 'Scalp',
  'loss': 'Money lost',
  'exitrule': 'Exit rules',
};

String labFamily(String f) => kLabFamilies[f] ?? f;

String _sg(double v, [int d = 2]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

/// "40s", "5 min", "2 h 10 min" (over 60 minutes = hours + minutes, owner rule).
String labAgo(int s) {
  if (s < 0) return 'not yet';
  if (s < 90) return '${s}s ago';
  final m = s ~/ 60;
  if (m < 60) return '$m min ago';
  return '${m ~/ 60} h ${m % 60} min ago';
}

/// The four tiles on top: EDGE / LOSING / TESTED (no proof) / NEED DATA, counted over ALL tests (the filter never changes them).
class LabSummaryStrip extends StatelessWidget {
  final Map<String, int> byVerdict;
  const LabSummaryStrip({super.key, required this.byVerdict});

  Widget _tile(BuildContext context, String label, int v, String sub, Color? c) {
    final p = context.palette;
    return Expanded(
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.s + 2),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: context.type.metadata),
          Text('$v', style: context.type.section.copyWith(fontWeight: FontWeight.w800, color: v > 0 && c != null ? c : p.textPrimary)),
          Text(sub, style: context.type.metadata, maxLines: 1, overflow: TextOverflow.ellipsis),
        ]),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    int c(String w) => byVerdict[w] ?? 0;
    return Row(children: [
      _tile(context, 'EDGE', c('EDGE'), 'proven', p.profit),
      const SizedBox(width: 8),
      _tile(context, 'LOSING', c('LOSING'), 'costs money', p.loss),
      const SizedBox(width: 8),
      _tile(context, 'TESTED', c('NO_EDGE') + c('DIAGNOSIS_ONLY'), 'no proof', null),
      const SizedBox(width: 8),
      _tile(context, 'NEED DATA', c('NOT_ENOUGH_DATA'), 'wait', p.warning),
    ]);
  }
}

/// One row of filter chips (horizontal scroll). [options] = chip label -> key; [counts] = key -> number shown on the chip.
class LabChipRow extends StatelessWidget {
  final Map<String, String> options;
  final Map<String, int> counts;
  final String selected;
  final ValueChanged<String> onSelect;
  const LabChipRow({super.key, required this.options, required this.counts, required this.selected, required this.onSelect});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(children: [
        for (final e in options.entries)
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: OWLPressable(
              onTap: () => onSelect(e.value),
              pressedScale: 0.96,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                decoration: BoxDecoration(
                  color: selected == e.value ? p.accent.withOpacity(0.16) : p.surface,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                  border: Border.all(color: selected == e.value ? p.accent : p.border),
                ),
                child: Text(counts[e.value] == null ? e.key : '${e.key} ${counts[e.value]}',
                    style: context.type.secondary.copyWith(fontWeight: FontWeight.w700, color: selected == e.value ? p.textPrimary : p.textSecondary)),
              ),
            ),
          ),
      ]),
    );
  }
}

/// ONE card per test: verdict badge, title, one headline, the key numbers. Tap = the plain details (what, how much, caveat, what is missing).
class LabTestCard extends StatefulWidget {
  final LabTest t;
  final VoidCallback? onOpen; // R14b: opens the full detail page (null = no button)
  const LabTestCard({super.key, required this.t, this.onOpen});

  @override
  State<LabTestCard> createState() => _LabTestCardState();
}

class _LabTestCardState extends State<LabTestCard> {
  bool _open = false;

  Widget _chip(AppPalette p, String s, {Color? c}) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(color: (c ?? p.textMuted).withOpacity(0.12), borderRadius: BorderRadius.circular(AppSpacing.radiusPill)),
        child: Text(s, style: context.type.metadata.copyWith(color: c ?? p.textSecondary, fontWeight: FontWeight.w700)),
      );

  /// Only the numbers that exist, never a guessed one.
  String _numbers(LabTest t) {
    final out = <String>[if (t.needN > 0) 'n ${t.n} of ${t.needN}' else 'n ${t.n}'];
    if (t.winPct != null) out.add('win ${t.winPct!.toStringAsFixed(0)}%');
    if (t.expR != null) out.add('${_sg(t.expR!)} R each');
    if (t.liftR != null) out.add('lift ${_sg(t.liftR!)} R');
    if (t.liftTrain != null && t.liftTest != null) out.add('halves ${_sg(t.liftTrain!)} / ${_sg(t.liftTest!)}');
    if (t.coinsBeatPct != null) out.add('${t.coinsBeatPct!.toStringAsFixed(0)}% of coins');
    return out.join('  |  ');
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = widget.t;
    final vs = VerdictStyle.of(p, t.verdict);
    final frac = t.needsData && t.needN > 0 ? (t.n / t.needN).clamp(0.0, 1.0) : null;
    // Part 13b: a FLAT row (no box per test): thin line under it, a coloured bar on the left for an EDGE.
    return OWLPressable(
        onTap: () => setState(() => _open = !_open),
        pressedScale: 0.99,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: AppSpacing.m, horizontal: 2),
          decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.border), left: BorderSide(color: t.verdict == 'EDGE' ? vs.color : Colors.transparent, width: 3))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              t.verdict == 'DIAGNOSIS_ONLY' ? _chip(p, 'CANDIDATE', c: p.accent) : VerdictBadge(verdict: t.verdict, compact: true),
              const SizedBox(width: 6),
              _chip(p, labFamily(t.family)),
              if (t.side.isNotEmpty) ...[const SizedBox(width: 4), _chip(p, t.side, c: t.side == 'LONG' ? p.profit : (t.side == 'SHORT' ? p.loss : null))],
              const Spacer(),
              Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
            ]),
            const SizedBox(height: 6),
            Text(t.title, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            if (t.headline.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(t.headline, style: context.type.secondary.copyWith(color: p.textPrimary))),
            if (t.context.isNotEmpty && !t.needsData) Padding(padding: const EdgeInsets.only(top: 2), child: Text('Setting: ${t.context}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
            const SizedBox(height: 6),
            if (frac != null) ...[
              ClipRRect(
                borderRadius: BorderRadius.circular(3),
                child: Stack(children: [Container(height: 5, color: p.border), FractionallySizedBox(widthFactor: frac, child: Container(height: 5, color: p.warning))]),
              ),
              const SizedBox(height: 4),
            ],
            Text(_numbers(t), style: context.type.metadata),
            if (_open) ...[
              const SizedBox(height: 8),
              if (t.detail.isNotEmpty) Text(t.detail, style: context.type.secondary),
              if (t.reasonMissing.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Missing: ${t.reasonMissing}', style: context.type.secondary.copyWith(color: p.warning))),
              if (t.nextAction.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('To do: ${t.nextAction}', style: context.type.secondary)),
              if (t.caveat.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(t.caveat, style: context.type.metadata)),
              if (widget.onOpen != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: OWLPressable(
                    onTap: widget.onOpen,
                    pressedScale: 0.97,
                    child: Row(mainAxisSize: MainAxisSize.min, children: [
                      Text('Open full detail', style: context.type.secondary.copyWith(color: p.accent, fontWeight: FontWeight.w800)),
                      Icon(Icons.chevron_right_rounded, size: 18, color: p.accent),
                    ]),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text('Sniper uses it: ${t.useInSniper ? 'yes' : 'no'}  |  updated ${labAgo(t.agoSec)}${t.source.isEmpty ? '' : '  |  ${t.source}'}', style: context.type.metadata),
              ),
            ],
          ]),
        ),
    );
  }
}
