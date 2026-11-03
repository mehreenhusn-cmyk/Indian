import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';
import 'brain_dashboard_cards.dart';
import 'brain_dashboard_summary.dart';

/// Part M3 (Brain Dashboard), part 1 of 2: read-only, on the Part M3 route /api/v2/brain_dash. One home page of the Brain: today net, Brain 30 days next to Main bot 30 days,
/// open positions, today signals, daily loss cap, recent days, all-time net, the Brain's own sentence. The cards are in brain_dashboard_cards.dart (part 2 of 2).
/// PAPER, SHADOW and REPLAY are three separate tabs, never added. LIVE is locked (a line says so) and has no tab. Dart NOT compiled (the APK build is the proof).
class BrainDashboardScreen extends StatefulWidget {
  const BrainDashboardScreen({super.key});

  @override
  State<BrainDashboardScreen> createState() => _BrainDashboardScreenState();
}

class _BrainDashboardScreenState extends State<BrainDashboardScreen> {
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
    final r = await context.read<AppProvider>().fetchBrainDash(_src);
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
        return 'This backend does not have the dashboard route yet. Install the newest zip, restart the backend, then pull down.';
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
      kids = [LoadSpinner(onRetry: _load)];
    } else if (_bad(r)) {
      kids = [_sources(p), OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      final ok = r!;
      kids = [
        _sources(p),
        Text('LIVE is LOCKED. Showing the $_src numbers only.', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
        brainSummaryCard(p, ok),
        ...brainDashboardCards(p, ok),
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
