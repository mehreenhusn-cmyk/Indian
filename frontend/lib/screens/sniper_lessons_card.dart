import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'sniper_ab_card.dart';
import 'sniper_learn_cards.dart';
import 'sniper_tpsl_card.dart';

/// R17b: card 4 = WEEKLY LESSONS (GET /api/v2/sniper_lessons: the tag of every closed Sniper trade: entry error / exit error / sideways loss / good, and up to 3 plain lessons of the week),
/// plus [SniperLearnSection] = the loader that puts all SIX learning cards on the Sniper tab. Each route loads alone with a 12 s limit, so one slow or broken route only turns ITS card into a plain line.
/// [refresh] = a number the screen raises on a pull-down, so the cards load again. Read only, paper only. Dart NOT compiled (the APK build is the proof).
class SniperLessonsCard extends StatelessWidget {
  final Map<String, dynamic>? r;
  const SniperLessonsCard({super.key, this.r});

  @override
  Widget build(BuildContext context) {
    final bad = lcProblem(r);
    if (bad.isNotEmpty) return LearnCard(title: 'LESSONS OF THE WEEK', headline: bad);
    final st = '${r!['state'] ?? ''}';
    final wk = lcMap(r!['week']);
    final n = lcI(wk['trades']) ?? 0;
    final good = lcI(wk['good']) ?? 0;
    final bad2 = lcI(wk['mistakes']) ?? 0;
    final ls = wk['lessons'] is List ? [for (final x in wk['lessons'] as List) lcMap(x)['text'] != null ? '${lcMap(x)['text']}' : '$x'] : <String>[];
    final reasons = r!['reasons'] is List ? [for (final x in r!['reasons'] as List) '$x'] : <String>[];
    if (st == 'NO_TRADES_YET' || n == 0) {
      return LearnCard(title: 'LESSONS OF THE WEEK', word: 'NO TRADES YET', tone: 'wait', headline: reasons.isNotEmpty ? reasons.first : 'The Sniper has no closed trade this week, so there is nothing to learn from yet.');
    }
    return LearnCard(
      title: 'LESSONS OF THE WEEK',
      word: 'LEARNING',
      tone: 'wait',
      headline: 'This week: $n trades, $good good, $bad2 mistakes',
      lines: ls.take(3).toList(),
      note: 'A mistake that repeats lowers the score of that setup. Advice only.',
    );
  }
}

class SniperLearnSection extends StatefulWidget {
  final int refresh;
  const SniperLearnSection({super.key, this.refresh = 0});

  @override
  State<SniperLearnSection> createState() => _SniperLearnSectionState();
}

class _SniperLearnSectionState extends State<SniperLearnSection> {
  static const _limit = Duration(seconds: 8);
  static Map<String, dynamic>? _cHist, _cExit, _cLessons; // Part 5: last good answers, shown at once next time
  Map<String, dynamic>? _hist = _cHist, _exit = _cExit, _lessons = _cLessons; // null = still loading (first time only)
  int _gen = 0; // a late answer of an older load is thrown away

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void didUpdateWidget(SniperLearnSection old) {
    super.didUpdateWidget(old);
    if (old.refresh != widget.refresh) _load();
  }

  Future<Map<String, dynamic>> _safe(Future<Map<String, dynamic>> f) async {
    try {
      return await f.timeout(_limit);
    } catch (_) {
      return {'state': 'error'};
    }
  }

  void _load() {
    final pr = context.read<AppProvider>();
    final g = ++_gen;
    // Part 5: a failed try keeps the old card (last known) instead of replacing it with an error line.
    void put(void Function(Map<String, dynamic>) set, void Function(Map<String, dynamic>) keep, Map<String, dynamic>? old, Future<Map<String, dynamic>> f) => _safe(f).then((r) {
          if (!mounted || g != _gen) return;
          final failed = r['state'] == 'error' && old != null;
          if (!failed) keep(r);
          setState(() => set(failed ? old : r));
        });
    put((r) => _hist = r, (r) => _cHist = r, _hist, pr.fetchSniperHist());
    put((r) => _exit = r, (r) => _cExit = r, _exit, pr.fetchSniperExit());
    put((r) => _lessons = r, (r) => _cLessons = r, _lessons, pr.fetchSniperLessons());
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    Widget gap() => const SizedBox(height: 10);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('WHAT IT LEARNED', style: context.type.label.copyWith(color: p.textMuted, fontWeight: FontWeight.w800, letterSpacing: 0.8))),
      SniperBookingCard(r: _exit),
      gap(),
      SniperTpslCard(r: _exit),
      gap(),
      SniperAbCard(r: _exit),
      gap(),
      SniperEntryCard(r: _exit),
      gap(),
      SniperLessonsCard(r: _lessons),
      gap(),
      SniperDataHealthCard(r: _hist),
    ]);
  }
}
