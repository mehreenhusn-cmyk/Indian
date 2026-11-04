import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R17b: the cards of the Sniper tab that say WHAT IT LEARNED. This file = the shared card look + three cards (training data health, booking learned, entry learned).
/// The fourth card (weekly lessons) and the loader that feeds all four are in sniper_lessons_card.dart. Every card takes ONE answer map (a route of the backend) and never prints "null";
/// a loading, off, old or error answer becomes one plain line. Numbers are R per trade after fees on UNSEEN days unless the line says otherwise. Advice only, paper only.
/// Dart NOT compiled (the APK build is the proof).
Map<String, dynamic> lcMap(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
double? lcD(Object? v) => v is num && v.isFinite ? v.toDouble() : null;
int? lcI(Object? v) => v is num && v.isFinite ? v.toInt() : null;
String lcSg(double v, [int d = 3]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

/// The plain line for an answer that is not a real one (null = still loading), or '' when the answer is real.
String lcProblem(Map<String, dynamic>? r) {
  if (r == null) return 'Loading...';
  switch ('${r['state'] ?? ''}') {
    case 'off':
      return 'Switched off in the backend (V2 API or Sniper switch).';
    case 'old':
      return 'This backend does not have this route yet. Install the newest backend zip and restart it.';
    case 'error':
      return 'Could not be read right now. Pull down to try again.';
    case 'busy':
      return 'Still being built. Pull down in a minute.';
  }
  return '';
}

/// ONE card: small title, a state word chip (colour = [tone]: 'good', 'wait' or ''), one headline, up to a few short lines, an optional grey note.
class LearnCard extends StatelessWidget {
  final String title, word, headline, note;
  final String tone;
  final List<String> lines;
  const LearnCard({super.key, required this.title, this.word = '', this.tone = '', this.headline = '', this.lines = const <String>[], this.note = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = tone == 'good' ? p.profit : (tone == 'wait' ? p.warning : p.textMuted);
    return OWLCard(
      edge: tone == 'good' ? c : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(title, style: context.type.label.copyWith(color: p.textSecondary, fontWeight: FontWeight.w800, letterSpacing: 0.6))),
          if (word.isNotEmpty)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 3),
              decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(20), border: Border.all(color: c.withOpacity(0.5))),
              child: Text(word, style: context.type.label.copyWith(color: c, fontWeight: FontWeight.w800, fontSize: 11)),
            ),
        ]),
        if (headline.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(headline, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
        for (final l in lines) Padding(padding: const EdgeInsets.only(top: 3), child: Text(l, style: context.type.secondary)),
        if (note.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(note, style: context.type.metadata)),
      ]),
    );
  }
}

/// Card 1: TRAINING DATA HEALTH (GET /api/v2/sniper_hist). Per source apart (Dual, Brain, Main), never added: closed trades, how many the learner can replay now, how many can still be fixed by the candle download.
class SniperDataHealthCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperDataHealthCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'TRAINING DATA HEALTH', headline: bad);
    final by = lcMap(r!['by_source']);
    final rows = <String>[];
    for (final e in const {'dual': 'Dual', 'brain': 'Brain', 'main': 'Main bot'}.entries) {
      final s = lcMap(by[e.key]);
      if (s.isEmpty) continue;
      final rec = lcI(s['records']) ?? 0;
      final ready = lcI(s['ready']) ?? 0;
      final fix = lcI(s['needs_fetch']) ?? 0;
      rows.add('${e.value}: $ready of $rec trades ready to learn from${fix > 0 ? ', $fix more can be fixed by the download' : ''}');
    }
    final lines = r!['lines'] is List ? [for (final x in r!['lines'] as List) '$x'] : <String>[];
    return LearnCard(
      title: 'TRAINING DATA HEALTH',
      headline: lines.isNotEmpty ? lines.first : 'Saved trades the Sniper can learn from',
      lines: rows,
      note: 'Each book is counted apart. Old trades need saved candles: the background download fills the gaps.',
    );
  }
}

/// Card 2: BOOKING LEARNED (GET /api/v2/sniper_exitlearn). Fixed 2R exit vs the learned exit per market state, on unseen days; plus what was left on the table.
class SniperBookingCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperBookingCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'BOOKING LEARNED', headline: bad);
    final st = '${r!['state'] ?? ''}';
    final cmp = lcMap(r!['compare']);
    final base = lcD(cmp['default_mean_r']);
    final got = lcD(cmp['live_choice_mean_r']);
    final n = lcI(cmp['test_trades']);
    final lot = lcMap(r!['left_on_table']);
    final lm = lcD(lot['mean_r']);
    final lost = lcI(lot['reached_1r_then_lost']);
    final rules = lcMap(r!['rules']);
    final reasons = r!['reasons'] is List ? [for (final x in r!['reasons'] as List) '$x'] : <String>[];
    return LearnCard(
      title: 'BOOKING LEARNED',
      word: st == 'LEARNED_EXIT' ? 'LEARNED' : (st == 'EXPLORE_EXIT' ? 'EXPLORING' : 'NOT YET'),
      tone: st == 'LEARNED_EXIT' ? 'good' : 'wait',
      headline: base == null || got == null ? (reasons.isNotEmpty ? reasons.first : 'No unseen-days test yet.') : 'Unseen days: learned exit ${lcSg(got)} R vs fixed ${lcSg(base)} R each${n == null ? '' : ' ($n trades)'}',
      lines: [
        if (lm != null) 'Left on the table: ${lcSg(lm, 2)} R per trade${lost == null ? '' : ', $lost trades reached +1R and still lost'}',
        for (final e in rules.entries.take(3)) '${e.key}: book with ${e.value}',
      ],
      note: 'Paper only. The paper LEARN lane may use the learned exit; real orders never do.',
    );
  }
}

/// Card 3: ENTRY LEARNED (the "entry" block of GET /api/v2/sniper_exitlearn). Better entry than the signal candle? Advice only.
class SniperEntryCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperEntryCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'ENTRY LEARNED', headline: bad);
    final e = lcMap(r!['entry']);
    if (e.isEmpty) return const LearnCard(title: 'ENTRY LEARNED', headline: 'No entry answer in this backend yet (needs R5).');
    final st = '${e['state'] ?? ''}';
    final cmp = lcMap(e['compare']);
    final now = lcD(cmp['now_mean_r']);
    final got = lcD(cmp['learned_mean_r']);
    final n = lcI(cmp['test_signals']);
    final fill = lcMap(e['fill_pct']);
    final rules = lcMap(e['rules']);
    final reasons = e['reasons'] is List ? [for (final x in e['reasons'] as List) '$x'] : <String>[];
    return LearnCard(
      title: 'ENTRY LEARNED',
      word: st == 'LEARNED_ENTRY' ? 'LEARNED' : 'EXPLORING',
      tone: st == 'LEARNED_ENTRY' ? 'good' : 'wait',
      headline: now == null || got == null ? (reasons.isNotEmpty ? reasons.first : 'No unseen-days test yet.') : 'Unseen days: learned entry ${lcSg(got)} R vs now ${lcSg(now)} R per signal${n == null ? '' : ' ($n signals)'}',
      lines: [
        for (final x in rules.entries.take(3)) '${x.key}: enter with ${x.value}',
        if (fill.isNotEmpty) 'Fill rate: ${[for (final x in fill.entries.take(4)) '${x.key} ${lcD(x.value)?.toStringAsFixed(0) ?? '--'}%'].join(', ')}',
      ],
      note: 'Advice only: nothing live uses it. A missed signal counts as 0 R, so a better price that misses winners is not hidden.',
    );
  }
}
