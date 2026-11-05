import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_text_tabs.dart';
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
  final _lg = LastGood();
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
      _lg.take(r, _bad(r)); // R8: a failed refresh keeps the last good data
      _r = _lg.data;
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

  // R25b: plain text tabs (same look as Positions) instead of three chips.
  Widget _sources(AppPalette p) {
    const names = ['PAPER', 'SHADOW', 'REPLAY'];
    return OwlTextTabs(
      names: names,
      index: names.indexOf(_src).clamp(0, 2),
      fontSize: 14,
      onChanged: (i) {
        _src = names[i];
        _lg.reset(); // another source: old numbers must not stay
        _r = null;
        _load();
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [LoadSpinner(onRetry: _load)];
    } else if (_bad(r)) {
      kids = [
        _sources(p),
        OWLCard(edge: p.warning, child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)),
          const SizedBox(height: 10),
          OutlinedButton(onPressed: _load, child: const Text('Retry')), // Plan D: failure = message + Retry, numbers stay "--"
        ])),
      ];
    } else {
      final ok = r!;
      kids = [
        _sources(p),
        UpdatedLine(lg: _lg, onRetry: _load),
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
