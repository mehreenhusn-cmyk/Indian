import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/data_doctor_card.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';
import '../widgets/sniper_health_tiles.dart';
import 'diagnostics_cards.dart';
import 'learning_progress_cards.dart';

/// R22b Diagnostics: 6 tiles on top, system checks + Data Doctor in closed folds. Part M1b: System Health screen, read-only, on the Part M1a route /api/v2/sys_health (idea of mock picture 10, REAL FACTS ONLY).
/// Shows: one headline (all OK / mostly fine / needs attention), the measured cards two by two (state dot, value, small line), a list of what is NOT MEASURED with the reason, an honest note.
/// A card the backend could not measure says NOT AVAILABLE and is grey; nothing is faked. Pull down to refresh.
/// Round 28 (Diagnostics tab): below the old cards two blocks are added, each loaded on its own so one missing route never hides the other: OwlSniper health (SniperHealthTiles, /api/v2/sniper_health)
/// and the Data Doctor (DataDoctorCard: which coins have candle gaps + the Termux commands; /api/v2/gaps and /api/v2/status). Dart NOT compiled (the APK build is the proof).
/// Part 15 (FILE 32): the green / amber connection tiles (SniperHealthTiles) now sit at the TOP, right under the pull-down, then the system headline and its small cards, then the Data Doctor.
/// The loading circle is the shared LoadSpinner (12 s, then "taking long" + Retry). Part 16 (FILE 33): the measured cards are ONE compact list and 'Not measured yet' is one closed line (screens/diagnostics_cards.dart).
class SystemHealthScreen extends StatefulWidget {
  const SystemHealthScreen({super.key});

  @override
  State<SystemHealthScreen> createState() => _SystemHealthScreenState();
}

class _SystemHealthScreenState extends State<SystemHealthScreen> {
  Map<String, dynamic>? _r;
  Map<String, dynamic>? _sh, _gaps, _st;
  bool _busy = true;
  final _lg = LastGood();

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final pv = context.read<AppProvider>();
    final all = await Future.wait([pv.fetchSysHealth(), pv.fetchSniperHealth(), pv.fetchV2Gaps(), pv.fetchV2Status()]);
    if (!mounted) return;
    setState(() {
      _lg.take(all[0], _bad(all[0])); // R8: a failed refresh keeps the last good data
      _r = _lg.data;
      _sh = all[1];
      _gaps = all[2];
      _st = all[3];
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r == null ? 'error' : r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the system health route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
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
        SniperHealthTiles(r: _sh),
        OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary))),
        OwlFold(title: 'DATA DOCTOR', headline: 'Candle gaps and the fix commands', bare: true, children: [DataDoctorCard(gaps: _gaps, status: _st)]),
      ];
    } else {
      final ok = r!;
      final bad = lpNum(ok['bad']);
      final warn = lpNum(ok['warn']);
      final hc = bad > 0 ? p.loss : warn > 0 ? p.warning : p.profit;
      kids = [
        UpdatedLine(lg: _lg, onRetry: _load),
        SniperHealthTiles(r: _sh),
        OWLCard(
          edge: hc,
          child: Row(children: [
            Icon(Icons.circle, size: 14, color: hc),
            const SizedBox(width: 10),
            Expanded(child: Text('${ok['headline'] ?? ''}', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary))),
          ]),
        ),
        // R22b Diagnostics: 6 tiles on top (headline + the 5 Sniper checks); everything else sits in two closed folds.
        OwlFold(
          title: 'ALL SYSTEM CHECKS',
          headline: bad > 0 ? '$bad bad, $warn warn: tap to see each check' : warn > 0 ? '$warn warn: tap to see each check' : 'All measured checks OK',
          headlineColor: hc,
          bare: true,
          children: [
            DiagCompactCards(cards: lpList(ok['cards'])),
            DiagNotMeasured(items: lpList(ok['not_measured'])),
            Text('${ok['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ],
        ),
        OwlFold(title: 'DATA DOCTOR', headline: 'Candle gaps and the fix commands', bare: true, children: [DataDoctorCard(gaps: _gaps, status: _st)]),
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
