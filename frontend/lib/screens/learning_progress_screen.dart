import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'learning_progress_cards.dart';

/// Part L2 (Learning Progress), part 1 of 2: read-only, on the Part L1 route /api/v2/brain_progress.
/// Shows: how many trades the Brain took today (profit / loss / net), the weekly learning curve (losing trades per 10), is it getting better (older vs newer half),
/// mistakes, fixed, what it learned. The cards are in learning_progress_cards.dart (part 2 of 2).
/// PAPER, SHADOW and REPLAY are three separate tabs, never added. LIVE is locked and has no tab. No win-rate headline, no forecast. Dart NOT compiled (the APK build is the proof).
class LearningProgressScreen extends StatefulWidget {
  const LearningProgressScreen({super.key});

  @override
  State<LearningProgressScreen> createState() => _LearningProgressScreenState();
}

class _LearningProgressScreenState extends State<LearningProgressScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'PAPER';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainProgress(_src);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['ready'] == false && r['note'] != null) return '${r['note']}';
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r == null ? 'error' : r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the learning progress route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _sources(AppPalette p) => Wrap(spacing: 8, children: [
        for (final s in const ['PAPER', 'SHADOW', 'REPLAY'])
          ChoiceChip(
            label: Text(s),
            selected: _src == s,
            onSelected: (_) {
              if (_src == s) return;
              _src = s;
              _load();
            },
          ),
      ]);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [_sources(p), OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      final ok = r!;
      kids = [
        _sources(p),
        Text('$_src - ${ok['all_closed'] ?? 0} closed trades in total', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textSecondary)),
        ...learningProgressCards(p, ok),
      ];
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
      ),
    );
  }
}
