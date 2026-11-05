import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/verdict_card.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/brain_strip.dart';
import '../widgets/btc_live_tile.dart';
import '../widgets/compare_books.dart';
import '../widgets/dashboard_bits.dart';
import '../widgets/dashboard_equity.dart';
import '../widgets/dashboard_pairs.dart';
import '../widgets/diag_section.dart';
import '../widgets/live_wallet_card.dart';
import '../widgets/owl_card.dart' hide OwlStat; // Part 17f: owl_number.dart has the OwlStat data class used here; owl_card.dart has a widget with the same name
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_number.dart';
import '../widgets/owl_status_header.dart';
import '../widgets/pnl_calendar.dart';
import '../widgets/sniper_days_card.dart';
import '../widgets/tag_lab_tile.dart';
import '../widgets/top_movers_card.dart';
import '../widgets/verdict_badge.dart';

/// Everything the Dashboard BODY shows that is NOT a per-tick price number (same idea as before Round 12):
/// the body only rebuilds when this value changes. Fast parts (open P&L tile, pairs list) have their own Selectors.
int _dashBodySig(AppProvider p) {
  final s = p.status;
  return Object.hashAll([
    s.isEmpty, p.error, s['last_error'], p.statsMode, s['today_pnl_usdt'], s['open_count'], s['win_rate'],
    s['symbols_tracked'], s['last_reconcile']?.toString(), p.settings['daily_target_usdt'],
    p.settings['daily_loss_limit_usdt'], p.settings['trading_enabled'], (p.openMarginUsed * 100).round(),
    (p.pnl7d * 100).round(), (p.pnl30d * 100).round(), p.trades30d, p.liveWallet?['ok'],
    identityHashCode(p.equityCurve), p.equityTf, identityHashCode(p.calendarData), p.signalsRev,
  ]);
}

/// Round 12: the Dashboard, answer first (UI rules 1, 2, 6, 7).
///   1 banners (only when something is wrong)   2 title + bot pill + link health   3 status line
///   4 THE RESULT: the Main bot's TODAY is the big headline (owner, 3 Nov 2026), 30 days / 7 days / open P&L / win rate sit under it, small
///   5 one verdict line from the Study Lab (what the numbers mean)   6 open pairs, one row per coin + side
///   7 BTC + Brain vs Bot   8 equity curve   9 ONE folded block "More" (calendar, movers, studies, health)
/// Nothing was deleted: the old cards moved into the fold or into widgets/dashboard_bits.dart.
class DashboardScreen extends StatelessWidget {
  const DashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Selector<AppProvider, int>(
          selector: (_, p) => _dashBodySig(p),
          builder: (context, _, child) {
            final provider = context.read<AppProvider>();
            final status = provider.status;
            if (status.isEmpty && provider.error == null) return const DashboardSkeleton();
            // STRICT STATE ISOLATION (unchanged): in LIVE mode the paper-only numbers come back null, so the hero shows real open P&L.
            final isLive = provider.statsMode == 'live';
            final todayPnl = ((status['today_pnl_usdt'] ?? 0.0) as num).toDouble();
            final target = (provider.settings['daily_target_usdt'] as num?)?.toDouble() ?? 0.0;
            final lossLimit = (provider.settings['daily_loss_limit_usdt'] as num?)?.toDouble() ?? 0.0;
            final targetHit = !isLive && target > 0 && todayPnl >= target;
            final lossHit = !isLive && lossLimit > 0 && todayPnl <= -lossLimit;
            final connError = provider.error;
            final botError = status['last_error'];
            return Column(children: [
              Expanded(
                child: OWLRefresh(
                  onRefresh: () => provider.fetchStatus().timeout(const Duration(seconds: 6), onTimeout: () {}),
                  child: SingleChildScrollView(
                    physics: owlPullPhysics,
                    padding: const EdgeInsets.all(AppSpacing.l),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      if (connError != null) ...[DashErrorBanner(icon: Icons.cloud_off, text: connError), const SizedBox(height: AppSpacing.cardGap)],
                      if (connError == null && botError != null) ...[DashErrorBanner(icon: Icons.warning_amber_rounded, text: 'Bot: $botError'), const SizedBox(height: AppSpacing.cardGap)],
                      if (lossHit) ...[const DashRiskBanner(icon: Icons.lock_clock, text: 'Daily loss limit hit - auto-trading paused for today', isLoss: true), const SizedBox(height: AppSpacing.cardGap)],
                      if (!lossHit && targetHit) ...[const DashRiskBanner(icon: Icons.emoji_events, text: 'Daily target hit - auto-trading paused for today', isLoss: false), const SizedBox(height: AppSpacing.cardGap)],
                      // P-D: ONE status header (title, bot pill, one dot row; tap = details sheet with the catch-up in IST) instead of three loose lines.
                      OwlStatusHeader(status: status),
                      const SizedBox(height: AppSpacing.l),
                      _ResultHero(isLive: isLive, todayPnl: todayPnl, winRate: ((status['win_rate'] ?? 0.0) as num).toDouble(), openCount: ((status['open_count'] ?? 0) as num).toInt()),
                      if (isLive) ...[const SizedBox(height: AppSpacing.cardGap), const LiveWalletCard()],
                      const SizedBox(height: AppSpacing.cardGap),
                      // Part 41: the books side by side (Main bot / Dual Bot paper / Brain / Sniper LEARN / Sniper Replay), same columns, never added.
                      if (!isLive) const BrainStrip(),
                      // R28b (Part 9): Sniper Today / Sniper 7 Days (two tabs, paper only, BTC not counted).
                      if (!isLive) ...[const SniperDaysCard(), const SizedBox(height: AppSpacing.cardGap)],
                      const _ResultsVerdictLine(),
                      const SizedBox(height: AppSpacing.cardGap),
                      const DashboardPairs(),
                      const BtcLiveTile(),
                      const SizedBox(height: AppSpacing.cardGap),
                      DashboardEquityChart(provider.equityCurve, provider.equityTf, (tf) => provider.fetchEquity(tf: tf)),
                      const SizedBox(height: AppSpacing.cardGap),
                      // R28c (Part 10): Diagnostics is an organized section here (connections, leaks, this app, Sniper); the old engineering cards sit in its DETAILS fold.
                      const DiagSection(),
                      const SizedBox(height: AppSpacing.cardGap),
                      // UI rule 7: calendar, movers, studies and health sit behind ONE tap, so the page answers first.
                      OwlFold(
                        title: 'MORE',
                        headline: 'Calendar, top movers, Tag Lab',
                        bare: true,
                        children: [
                          PnlCalendar(data: provider.calendarData, onMonthChanged: (m) => provider.fetchCalendar(month: m)),
                          const SizedBox(height: AppSpacing.cardGap),
                          const TopMoversCard(),
                          const TagLabTile(),
                        ],
                      ),
                    ]),
                  ),
                ),
              ),
            ]);
          },
        ),
      ),
    );
  }
}

/// THE RESULT card. Paper mode (Part 18): the headline is the MAIN BOT's today (the day starts 5:30 AM IST = 00:00 UTC), big; the 30-day total is only a small tile (it was the headline before, the owner wants today first).
/// The label says it is the Main bot only: Dual Bot paper and Brain have their own numbers on their own screens, never added here.
/// Tiles under it: 30 days, 7 days, Open P&L, Win rate. Live mode: the headline is the live open P&L and the
/// tiles are margin used and open positions (paper stats do not exist there). Every number is printed once.
class _ResultHero extends StatelessWidget {
  final bool isLive;
  final double todayPnl;
  final double winRate;
  final int openCount;

  const _ResultHero({required this.isLive, required this.todayPnl, required this.winRate, required this.openCount});

  String _tone(double v) => v > 0 ? 'good' : (v < 0 ? 'bad' : '');

  @override
  Widget build(BuildContext context) {
    final prov = context.read<AppProvider>();
    return Selector<AppProvider, String>(
      selector: (_, x) => '${(x.openPnl * 100).round()}|${(x.pnl30d * 100).round()}',
      builder: (context, _, __) {
        final open = prov.openPnl;
        final head = isLive ? open : todayPnl;
        final n30 = prov.trades30d;
        final label = isLive ? 'Open P&L now (live account)' : 'Main bot, today (day starts 5:30 AM IST)';
        final sub = isLive ? '$openCount open positions' : 'Main bot only. Dual Bot paper and Brain are shown apart.';
        // Part 12b: flat hero (no box): small spaced label, ONE big number, one grey line, then ONE thin-lined strip of facts (OwlStatStrip).
        final stats = isLive
            ? [OwlStat(prov.openMarginUsed.toStringAsFixed(2), 'Margin used'), OwlStat('$openCount', 'Open positions')]
            : [
                OwlStat(fmtSigned(prov.pnl30d), '30 days', tone: _tone(prov.pnl30d)),
                OwlStat(fmtSigned(prov.pnl7d), '7 days', tone: _tone(prov.pnl7d)),
                OwlStat(fmtSigned(open), 'Open P&L', tone: _tone(open)),
                OwlStat('${winRate.toStringAsFixed(1)}%', 'Win rate'),
              ];
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(letterSpacing: 1.0, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          OwlNumber(head, suffix: 'USDT', size: 38, animate: true),
          const SizedBox(height: 2),
          Text(sub, style: context.type.metadata),
          if (!isLive && n30 > 0) Text('Last 30 days: $n30 closed trades', style: context.type.metadata),
          const SizedBox(height: AppSpacing.m),
          OwlStatStrip(stats),
        ]);
      },
    );
  }
}

/// One line from the Study Lab (card id "results"): the verdict word + the short headline, tap opens the Study Lab.
/// Loads GET /api/v2/verdicts once. If the route is off or fails, the line simply does not show (nothing breaks).
class _ResultsVerdictLine extends StatefulWidget {
  const _ResultsVerdictLine();

  @override
  State<_ResultsVerdictLine> createState() => _ResultsVerdictLineState();
}

class _ResultsVerdictLineState extends State<_ResultsVerdictLine> {
  VerdictCard? _card;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVerdicts();
    if (!mounted) return;
    for (final c in VerdictCard.listFrom(r['cards'])) {
      if (c.id == 'results' && c.headline.isNotEmpty) setState(() => _card = c);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = _card;
    if (c == null) return const SizedBox.shrink();
    final p = context.palette;
    return OWLPressable(
      pressedScale: 0.99,
      onTap: () => context.read<AppProvider>().goToRoute(AppRoute.studyLab),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.cardPad),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
        child: Row(children: [
          VerdictBadge(verdict: c.verdict, compact: true),
          const SizedBox(width: 8),
          Expanded(child: Text(c.headline, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
          Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
        ]),
      ),
    );
  }
}
