import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';
import '../widgets/signal_card.dart';
import 'sniper_compare.dart';
import 'sniper_extras.dart';
import 'sniper_lessons_card.dart';
import 'sniper_panels.dart';
import 'sniper_pillars.dart';
import 'sniper_quiet.dart';
import 'sniper_riskbox_fold.dart';
import 'sniper_state_banner.dart';

/// OwlSniper tab. Part S6 made it; Round 27 rebuilt it on the 3 pillars (Round 25) and the Sniper vs Main Bot panel. Read-only, on GET /api/v2/sniper.
/// Part 5: right under the headline sits the "Why is Sniper quiet?" card (LEARN progress n of 30 + plain reasons + the REAL gate state); its data is GET /api/v2/sniper_learn, loaded on its own so a slow answer never blocks the page.
/// Order: headline -> Why quiet -> Pillar B Volatility Guard -> order cards -> Pillar C Terminal Insight -> Sniper vs Main Bot -> Pillar A Capital Shield -> TEST-day equity -> 85% floor -> insight report -> auto-trade strip.
/// The page asks the backend again every 30 seconds while it is open (a cheap read of small files); the backend starts its own refresh by itself, so nothing has to be run by hand.
/// OwlSniper only WATCHES: nothing here sends an order, saves anything or switches anything (the auto-trade strip only SHOWS the executor state; arming is a Termux command, never a button).
/// Dart NOT compiled (the APK build is the proof).
class SniperScreen extends StatefulWidget {
  const SniperScreen({super.key});

  @override
  State<SniperScreen> createState() => _SniperScreenState();
}

class _SniperScreenState extends State<SniperScreen> {
  Map<String, dynamic>? _r;
  Map<String, dynamic>? _learn;
  Map<String, dynamic>? _ap; // R17a: GET /api/v2/sniper_autopilot (state, reasons, unseen-days compare)
  bool _busy = true;
  bool _all = false;
  int _tick = 0; // R17b: raised on a pull-down so the four learning cards load again
  Timer? _timer;
  final _lg = LastGood();

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 30), (_) => _load(silent: true));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent) setState(() { _busy = true; _tick++; });
    final r = await context.read<AppProvider>().fetchSniper();
    if (!mounted) return;
    setState(() {
      _lg.take(r, _bad(r)); // R8: a failed refresh keeps the last good data
      _r = _lg.data;
      _busy = false;
    });
    _loadLearn();
  }

  Future<void> _loadLearn() async {
    final pr = context.read<AppProvider>();
    final l = await pr.fetchSniperLearn();
    if (!mounted) return;
    setState(() => _learn = l);
    final a = await pr.fetchSniperAutopilot();
    if (!mounted) return;
    setState(() => _ap = a);
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r?['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the OwlSniper route yet. Install the newest backend zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  /// Shows what the executor is doing. No button: arming is a two-step Termux command on purpose.
  Widget _auto(AppPalette p, Map<String, dynamic> r) {
    final ex = r['executor'] is Map ? Map<String, dynamic>.from(r['executor'] as Map) : <String, dynamic>{};
    final kill = ex['kill'] is Map && (ex['kill'] as Map)['on'] == true;
    final armed = ex['armed'] == true;
    final String text;
    final Color c;
    if (ex.isEmpty || ex['state'] != null || ex['ok'] == false) {
      text = 'Auto-trade: not available in this backend. OwlSniper is watch only.';
      c = p.textMuted;
    } else if (kill) {
      text = 'Auto-trade: STOPPED by the kill switch (${(ex['kill'] as Map)['reason'] ?? ''}).';
      c = p.loss;
    } else if (armed) {
      text = 'Auto-trade: ARMED in paper mode only. It opens a paper trade only when every check passes (85% or more, proven on the TEST days).';
      c = p.warning;
    } else {
      text = 'Real auto-trade: OFF. It stays off until you arm it in two steps from Termux. Paper mode only, live orders do not exist. LEARN paper trades run on their own (see the card on top).';
      c = p.textSecondary;
    }
    return OWLCard(edge: armed || kill ? c : null, child: Text(text, style: TextStyle(fontSize: 12, color: c)));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [LoadSpinner(onRetry: () => _load())];
    } else if (_bad(r)) {
      kids = [OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = [
        UpdatedLine(lg: _lg, onRetry: () => _load()),
        SniperStateBanner(r: r!, learn: _learn, auto: _ap),
        OwlFold(title: 'WHY QUIET', headline: 'LEARN progress and the plain reasons', bare: true, children: [SniperQuiet(r: r, learn: _learn)]),
        SniperVolatilityGuard(r: r),
        SniperSignalList(r: r, showAll: _all, onToggle: () => setState(() => _all = !_all)),
        SniperRiskBoxFold(r: r), // R17: Risk Box moved up, shows only when an order card exists
        SniperLearnSection(refresh: _tick),
        // R17a: the older panels sit behind ONE fold so the page answers first (R17b adds the four learning cards and moves the Risk Box up).
        OwlFold(title: 'MORE SNIPER PANELS', headline: 'Terminal insight, vs Main Bot, capital, equity, floor, report', bare: true, children: [
          SniperExtras(r: r),
          SniperInsightConsole(r: r),
          SniperComparePanel(r: r),
          SniperCapitalShield(r: r),
          SniperEquity(r: r),
          SniperFloor(r: r),
          SniperReport(r: r),
        ]),
        _auto(p, r),
        Text('${r['note'] ?? 'WATCH ONLY: this page never sends an order.'}', style: TextStyle(fontSize: 11, color: p.textMuted)),
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
