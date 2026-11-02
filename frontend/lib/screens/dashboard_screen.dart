import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/verdict_card.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/btc_live_tile.dart';
import '../widgets/dashboard_bits.dart';
import '../widgets/dashboard_equity.dart';
import '../widgets/dashboard_pairs.dart';
import '../widgets/diag_pinned_strip.dart';
import '../widgets/diagnostics_card.dart';
import '../widgets/live_status_chip.dart';
import '../widgets/live_wallet_card.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_connection_indicator.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/pnl_calendar.dart';
import '../widgets/stat_tile.dart';
import '../widgets/system_load_card.dart';
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
///   4 THE RESULT: the 30-day total is the headline, today / 7 days / open P&L / win rate sit under it
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
              const DiagPinnedStrip(),
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
                      Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                        Text('Dashboard', style: context.type.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
                        Row(mainAxisSize: MainAxisSize.min, children: [
                          MasterTradingTogglePill(
                            enabled: (provider.settings['trading_enabled'] as bool?) ?? true,
                            onToggle: (next) => provider.updateSettings({'trading_enabled': next}).then((r) => r != null && r['trading_enabled'] == next),
                          ),
                          const SizedBox(width: 8),
                          Selector<AppProvider, int>(
                            selector: (_, p) => Object.hash(p.error == null, p.wsConnected, p.wsLatencyMs),
                            builder: (context, _, __) {
                              final p = context.read<AppProvider>();
                              return OWLConnectionIndicator(isBackendLive: p.error == null, isWsLive: p.wsConnected, latency: p.wsLatencyMs);
                            },
                          ),
                        ]),
                      ]),
                      const SizedBox(height: AppSpacing.s),
                      Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 10, runSpacing: 4, children: [
                        const LiveStatusChip(),
                        Text('${status['symbols_tracked'] ?? 0} coins watched', style: context.type.metadata),
                      ]),
                      if (status['last_reconcile'] is Map) CatchUpLine(Map<String, dynamic>.from(status['last_reconcile'] as Map)),
                      const SizedBox(height: AppSpacing.l),
                      _ResultHero(isLive: isLive, todayPnl: todayPnl, winRate: ((status['win_rate'] ?? 0.0) as num).toDouble(), openCount: ((status['open_count'] ?? 0) as num).toInt()),
                      if (isLive) ...[const SizedBox(height: AppSpacing.cardGap), const LiveWalletCard()],
                      const SizedBox(height: AppSpacing.cardGap),
                      const _ResultsVerdictLine(),
                      const SizedBox(height: AppSpacing.cardGap),
                      const DashboardPairs(),
                      const BtcLiveTile(),
                      const DualBotTile(),
                      const SizedBox(height: AppSpacing.cardGap),
                      DashboardEquityChart(provider.equityCurve, provider.equityTf, (tf) => provider.fetchEquity(tf: tf)),
                      const SizedBox(height: AppSpacing.cardGap),
                      // UI rule 7: calendar, movers, studies and health sit behind ONE tap, so the page answers first.
                      OwlFold(
                        title: 'MORE',
                        headline: 'Calendar, top movers, Tag Lab, system health',
                        bare: true,
                        children: [
                          PnlCalendar(data: provider.calendarData, onMonthChanged: (m) => provider.fetchCalendar(month: m)),
                          const SizedBox(height: AppSpacing.cardGap),
                          const TopMoversCard(),
                          const TagLabTile(),
                          const DiagnosticsCard(),
                          const SystemLoadCard(),
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

/// THE RESULT card. Paper mode: the headline is the 30-day total (UI rule 6: today must not hide the month),
/// tiles under it: Today, 7 days, Open P&L, Win rate. Live mode: the headline is the live open P&L and the
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
    final p = context.palette;
    final prov = context.read<AppProvider>();
    return Selector<AppProvider, String>(
      selector: (_, x) => '${(x.openPnl * 100).round()}|${(x.pnl30d * 100).round()}',
      builder: (context, _, __) {
        final open = prov.openPnl;
        final head = isLive ? open : prov.pnl30d;
        final color = head > 0 ? p.profit : (head < 0 ? p.loss : p.textPrimary);
        final n30 = prov.trades30d;
        final label = isLive ? 'Open P&L now (live account)' : 'Last 30 days, closed trades after fees';
        final sub = isLive ? '$openCount open positions' : (n30 > 0 ? '$n30 trades' : 'no closed trades in 30 days yet');
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(AppSpacing.l),
          decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: context.type.label),
            const SizedBox(height: 4),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text('${fmtSigned(head)} USDT', maxLines: 1, style: context.type.number.copyWith(fontSize: 36, fontWeight: FontWeight.w800, color: color)),
            ),
            const SizedBox(height: 2),
            Text(sub, style: context.type.metadata),
            const SizedBox(height: AppSpacing.m),
            Row(children: [
              if (isLive) ...[
                Expanded(child: StatTile(label: 'Margin used', value: prov.openMarginUsed.toStringAsFixed(2))),
                const SizedBox(width: AppSpacing.s),
                Expanded(child: StatTile(label: 'Open positions', value: '$openCount')),
              ] else ...[
                Expanded(child: StatTile(label: 'Today', value: fmtSigned(todayPnl), tone: _tone(todayPnl))),
                const SizedBox(width: AppSpacing.s),
                Expanded(child: StatTile(label: '7 days', value: fmtSigned(prov.pnl7d), tone: _tone(prov.pnl7d))),
              ],
            ]),
            if (!isLive) ...[
              const SizedBox(height: AppSpacing.s),
              Row(children: [
                Expanded(child: StatTile(label: 'Open P&L', value: fmtSigned(open), tone: _tone(open))),
                const SizedBox(width: AppSpacing.s),
                Expanded(child: StatTile(label: 'Win rate', value: '${winRate.toStringAsFixed(1)}%', sub: '$openCount open')),
              ]),
            ],
          ]),
        );
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
