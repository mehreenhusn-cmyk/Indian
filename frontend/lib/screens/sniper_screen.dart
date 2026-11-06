import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_active.dart';
import '../theme/app_theme.dart';
import '../widgets/last_good.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart' hide OwlStat; // Part 17f: owl_number.dart has the OwlStat data class used here; owl_card.dart has a widget with the same name
import '../widgets/owl_number.dart';
import '../widgets/owl_route.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sub_page.dart';
import '../widgets/skeleton_retry.dart';
import '../widgets/sniper_eva_card.dart';
import '../widgets/sniper_winners_card.dart';
import '../widgets/sniper_days_card.dart';
import '../widgets/sniper_positions.dart';
import '../widgets/signal_card.dart';
import '../widgets/sniper_watch_card.dart';
import 'sniper_compare.dart';
import 'sniper_ctx_card.dart';
import 'sniper_extras.dart';
import 'sniper_gates.dart';
import 'sniper_lessons_card.dart';
import 'sniper_panels.dart';
import 'sniper_pillars.dart';
import 'sniper_quiet.dart';
import 'sniper_riskbox_fold.dart';
import 'sniper_state_banner.dart';
import 'sniper_trade_card.dart';

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
  Map<String, dynamic>? _gates; // R26b: GET /api/v2/sniper_gates (8 gates + mistakes journal)
  Map<String, dynamic>? _ctx; // R30: GET /api/v2/sniper_ctx (BTC + session)
  Map<String, dynamic>? _trades; // R29a: GET /api/v2/sniper_trades (trade record)
  Map<String, dynamic>? _watch; // Part 16: GET /api/v2/sniper_watch (watchlist rows)
  Map<String, dynamic>? _eva; // Part 17a: GET /api/v2/sniper_eva (expected vs actual)
  Map<String, dynamic>? _watchBad; // Part 16: the problem answer, shown only while no good watchlist exists
  Map<String, dynamic>? _ap; // R17a: GET /api/v2/sniper_autopilot (state, reasons, unseen-days compare)
  bool _busy = true;
  bool _all = false;
  int _tick = 0; // R17b: raised on a pull-down so the four learning cards load again
  Timer? _timer;
  final _lg = LastGood();

  @override
  void initState() {
    super.initState();
    // Part 14: show the last good answers at once (a tab switch builds this screen again), then refresh quietly.
    _r = ScreenCache.get('sniper');
    _learn = ScreenCache.get('sniper_learn');
    _ap = ScreenCache.get('sniper_ap');
    _gates = ScreenCache.get('sniper_gates');
    _trades = ScreenCache.get('sniper_trades');
    _ctx = ScreenCache.get('sniper_ctx');
    _watch = ScreenCache.get('sniper_watch');
    _eva = ScreenCache.get('sniper_eva');
    if (_r != null) {
      _lg.take(_r, false);
      _lg.at = ScreenCache.when('sniper');
      _busy = false;
    }
    _load(silent: _r != null);
    _timer = AppActive.every(const Duration(seconds: 30), () => _load(silent: true));
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
    if (!_bad(r)) ScreenCache.put('sniper', r);
    _loadLearn();
  }

  /// Part 13c: the seven side reads run TOGETHER (they were one after the other, so the last card waited for the four before it), one redraw when all are in.
  Future<void> _loadLearn() async {
    final pr = context.read<AppProvider>();
    final out = await Future.wait<Map<String, dynamic>>([
      pr.fetchSniperLearn(),
      pr.fetchSniperAutopilot(),
      pr.fetchSniperGates(),
      pr.fetchSniperTrades(),
      pr.fetchSniperCtx(),
      pr.fetchSniperWatch(),
      pr.fetchSniperEva(),
    ]);
    if (!mounted) return;
    // Part 14: only a real answer replaces what is shown (a failed read keeps the old card) and goes into the cache.
    setState(() {
      if (ScreenCache.put('sniper_learn', out[0])) _learn = out[0];
      if (ScreenCache.put('sniper_ap', out[1])) _ap = out[1];
      if (ScreenCache.put('sniper_gates', out[2])) _gates = out[2];
      if (ScreenCache.put('sniper_trades', out[3])) _trades = out[3];
      if (ScreenCache.put('sniper_ctx', out[4])) _ctx = out[4];
      if (ScreenCache.put('sniper_eva', out[6])) { _eva = out[6]; } else if (_eva == null) { _eva = out[6]; } // Part 17a: a problem shows only while there is nothing good to keep
      // Part 16: only state OK is a good watchlist (the backend also uses NO_DATA / ERROR); a problem shows only while there is nothing good to keep.
      if (out[5]['state'] == 'OK' && ScreenCache.put('sniper_watch', out[5])) {
        _watch = out[5];
        _watchBad = null;
      } else if (_watch == null) {
        _watchBad = out[5];
      }
    });
  }

  int _l0(Object? v) => v is List ? v.length : 0;

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
      kids = [SkeletonRetry(onRetry: () => _load(), what: 'the Sniper')];
    } else if (_bad(r)) {
      kids = [OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = [
        UpdatedLine(lg: _lg, onRetry: () => _load()),
        SniperStateBanner(r: r!, learn: _learn, auto: _ap),
        const SniperDaysCard(), // E6: Today / 7 days of the Sniper at the top, same idea as the Dashboard
        SniperWatchCard(w: _watch ?? _watchBad), // Part 16: watchlist cards (skeleton until the first answer)
        // Part 13: GATES and WHY QUIET said the same thing twice (what stops the Sniper), so they are ONE fold now.
        OwlFold(title: 'WHY QUIET AND GATES', headline: _gates?['reason'] == null ? 'LEARN progress, plain reasons, which checks pass' : '${_gates!['reason']}', bare: true, children: [SniperQuiet(r: r, learn: _learn), SniperGates(g: _gates)]),
        SniperVolatilityGuard(r: r),
        SniperSignalList(r: r, showAll: _all, onToggle: () => setState(() => _all = !_all)),
        // R29b + P-F: open Sniper trades with live P&L and a chart (same list as the Sniper tab of Positions); one flat row, page push with the premium transition.
        OwlListCard(children: [
          OwlRow(
            title: 'Sniper positions',
            sub: 'Live P&L and chart',
            trailing: _trades == null ? null : OwlPill('${_l0(_trades!['open'])} open', tone: _l0(_trades!['open']) > 0 ? 'warn' : ''),
            onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => const OwlSubPage(title: 'Sniper positions', child: SniperPositions()))),
          ),
        ]),
        OwlFold(title: 'TRADE RECORD', headline: _trades == null ? 'Signal, why, entry, TP, SL, expected profit, result' : '${_l0(_trades!['open'])} open, ${_l0(_trades!['closed'])} closed', bare: true, children: [SniperTradeRecord(g: _trades)]),
        OwlFold(title: 'EXPECTED VS ACTUAL', headline: SniperEvaCard.headline(_eva), bare: true, children: [SniperEvaCard(e: _eva)]), // Part 17a
        OwlFold(title: 'MARKET CONTEXT', headline: _ctx == null ? 'BTC move, trend and session the Sniper learns from' : 'BTC ${_ctx!['ctx'] is Map ? (_ctx!['ctx'] as Map)['btc_3'] ?? '--' : '--'}% (3 candles), ${_ctx!['session'] ?? '--'}', bare: true, children: [SniperCtxCard(g: _ctx)]),
        SniperRiskBoxFold(r: r), // R17: Risk Box moved up, shows only when an order card exists
        SniperLearnSection(refresh: _tick),
        OwlFold(title: 'WHAT SNIPER LEARNED AND READY FOR REAL MONEY?', headline: 'Winners vs losers, and the readiness checklist in plain words', bare: true, children: const [SniperWinnersCard()]),
        OwlFold(title: 'MISTAKES LEARNED', headline: 'Every closed trade tagged, losing combos rest', bare: true, children: [SniperMistakes(g: _gates)]),
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
    final body = RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.screenPad),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.cardGap), child: k)],
      ),
    );
    // P-F: pinned summary line (source = Sniper, paper): open and closed trades. Only when the trade list has answered.
    final tr = _trades;
    if (tr == null || _bad(r)) return body;
    return Column(children: [
      OwlSummaryLine(source: 'Sniper - paper', facts: [OwlStat('${_l0(tr['open'])}', 'open'), OwlStat('${_l0(tr['closed'])}', 'closed')]),
      Expanded(child: body),
    ]);
  }
}
