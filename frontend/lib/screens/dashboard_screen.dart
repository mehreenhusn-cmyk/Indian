import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../theme/app_active.dart';
import '../models/verdict_card.dart';
import '../config_flags.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../widgets/brain_strip.dart';
import '../widgets/btc_live_tile.dart';
import '../widgets/compare_books.dart';
import '../widgets/dash_today_signals.dart';
import '../widgets/dashboard_bits.dart';
import '../widgets/dashboard_equity.dart';
import '../widgets/dashboard_pairs.dart';
import '../widgets/diag_load_row.dart';
import '../widgets/diag_section.dart';
import '../widgets/live_wallet_card.dart';
import '../widgets/main_sniper_table.dart';
import '../widgets/owl_card.dart' hide OwlStat, OwlStatRow; // Part 17f: owl_number.dart has the OwlStat data class used here; owl_card.dart has a widget with the same name. Part 10: OwlStatRow comes from the new kit (owl_kit_parts.dart), so the old one is hidden
import '../widgets/owl_hero_card.dart'; // Part 10: shared UI kit (Parts 8 + 9)
import '../widgets/owl_kit_extras.dart';
import '../widgets/owl_kit_parts.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_number.dart';
import '../widgets/owl_status_header.dart';
import '../widgets/pnl_calendar.dart';
import '../widgets/recent_activity.dart';
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
    p.settings['daily_loss_limit_usdt'], p.settings['inr_rate'], p.settings['trading_enabled'], (p.openMarginUsed * 100).round(),
    (p.pnl7d * 100).round(), (p.pnl30d * 100).round(), p.trades30d, p.liveWallet?['ok'],
    (p.mainToday * 100).round(), p.mainOpenCount, (p.main7d * 100).round(), (p.main30d * 100).round(), p.main7dPartial, p.main30dPartial, // Part 18B: Main-only numbers
    p.splitBlock?['generated'],
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
            if (status.isEmpty && provider.error == null) return const OwlShimmerList(count: 3); // Part 10: kit shimmer (the old DashboardSkeleton class stays in dashboard_bits.dart)
            // STRICT STATE ISOLATION (unchanged): in LIVE mode the paper-only numbers come back null, so the hero shows real open P&L.
            final isLive = provider.statsMode == 'live';
            // Part 18B: the BIG number and the target ring are MAIN only. The 'paused' banners below keep the all-in-one book number, because that is the number the bot itself uses to pause (backend unchanged).
            final bookPnl = ((status['today_pnl_usdt'] ?? 0.0) as num).toDouble();
            final todayPnl = isLive ? bookPnl : provider.mainToday;
            final mainOpenCount = provider.mainOpenCount;
            final target = (provider.settings['daily_target_usdt'] as num?)?.toDouble() ?? 0.0;
            final lossLimit = (provider.settings['daily_loss_limit_usdt'] as num?)?.toDouble() ?? 0.0;
            // Plan A: the fixed setting inr_rate (not a live rate). 0 = not set = no INR line.
            final inrRate = (provider.settings['inr_rate'] as num?)?.toDouble() ?? 0.0;
            final targetHit = !isLive && target > 0 && bookPnl >= target;
            final lossHit = !isLive && lossLimit > 0 && bookPnl <= -lossLimit;
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
                      // Part 7: the status header above is the always-visible health line: BE, WS, ms, LIVE age, coins, LEARN n/30 (tap = details). Order below = see Part 3.
                      // Plan B (picture ref3), top to bottom: 1 hero TODAY P&L (+ INR small, target ring only if a target is set)  2 four-column strip (Open P&L, BTC, Open positions, Signals; taps)
                      // 3 calendar  4 7 / 30 days  5 Diagnostics + System Load side by side  6 Dual / Brain / Sniper rows  7 Recent Activity  8 Equity curve  9 MORE fold (nothing deleted).
                      _ResultHeroKit(isLive: isLive, todayPnl: todayPnl, openCount: mainOpenCount, target: target, inrRate: inrRate, stale: connError != null),
                      if (isLive) ...[const SizedBox(height: AppSpacing.cardGap), const LiveWalletCard()],
                      const SizedBox(height: AppSpacing.m),
                      _ResultStrip(isLive: isLive, openCount: mainOpenCount),
                      if (!isLive && !kLite) Padding(padding: const EdgeInsets.only(top: 6), child: Text('These numbers are the MAIN bot only. Sniper trades share the same book but are shown apart in the table below. Dual and Brain are separate. The pause on daily target / loss limit still uses the whole book (Main + Sniper).', style: context.type.metadata.copyWith(color: context.palette.textMuted))),
                      // Part 3 order (owner: calendar lower): result > 7 / 30 days > Diagnostics + load > the three books > Recent Activity > Equity > P&L calendar > MORE.
                      const SizedBox(height: AppSpacing.l),
                      // E6: the bots one by one come FIRST (owner: no scrolling to find them), then 7 / 30 days. Diagnostics + load moved into MORE.
                      if (!isLive && !kLite) ...[const BrainStrip(), const SizedBox(height: AppSpacing.l)], // PHONE LITE: no Brain / Dual / Sniper rows
                      if (!isLive) ...[const _PeriodRow(), const SizedBox(height: AppSpacing.l), if (!kLite) const MainSniperTable(), if (!kLite) const SizedBox(height: AppSpacing.l)],
                      if (kLite) ...[const DashboardPairs(), const SizedBox(height: AppSpacing.l)], // Round G: open trades first
                      if (kLite) const DashTodaySignals() else const RecentActivity(), // Round D: LITE shows today's signals only, not the old Brain timeline
                      const SizedBox(height: AppSpacing.cardGap),
                      DashboardEquityChart(provider.equityCurve, provider.equityTf, (tf) => provider.fetchEquity(tf: tf)),
                      const SizedBox(height: AppSpacing.cardGap),
                      if (!kLite) ...[PnlCalendar(data: provider.calendarData, onMonthChanged: (m) => provider.fetchCalendar(month: m)), const SizedBox(height: AppSpacing.cardGap)], // Round D: in LITE the calendar sits in the MORE fold
                      // UI rule 7: everything that moved out of the main order sits behind ONE tap (nothing deleted).
                      if (!kLite) OwlFold( // Round G: no MORE fold in LITE (calendar = More > Month Calendar, BTC is in the strip)
                        title: 'MORE',
                        headline: kLite ? 'P&L calendar, BTC chart, open pairs, top movers' : 'Backend health and load, BTC chart, open pairs, Study Lab verdict, top movers, Tag Lab',
                        bare: true,
                        children: [
                          if (!kLite) ...[const DiagLoadRow(), const SizedBox(height: AppSpacing.cardGap), const _ResultsVerdictLine(), const SizedBox(height: AppSpacing.cardGap)],
                          if (kLite) ...[PnlCalendar(data: provider.calendarData, onMonthChanged: (m) => provider.fetchCalendar(month: m)), const SizedBox(height: AppSpacing.cardGap)],
                          const DashboardPairs(),
                          const BtcLiveTile(),
                          const SizedBox(height: AppSpacing.cardGap),
                          const TopMoversCard(),
                          if (!kLite) ...[const TagLabTile(), const SizedBox(height: AppSpacing.cardGap)],
                          // R28c (Part 10): the organized Diagnostics section (connections, leaks, this app, Sniper) with the old engineering cards in its DETAILS fold.
                          if (!kLite) const DiagSection(),
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

/// THE RESULT, Plan B (picture ref3). Paper mode: the headline is the MAIN BOT's TODAY (closed trades only, the day starts 5:30 AM IST = 00:00 UTC), big, with the small INR line under it
/// (fixed setting inr_rate, so the text says "approx."). A target ring shows only when a daily target is set (no target = no ring). Live mode: the headline is the live open P&L.
/// If the last refresh failed the old numbers stay on screen with a small "stale" mark (never blank, never 0). Every number is printed once: 7 / 30 days are in _PeriodRow, Open P&L / Win rate / Signals in _ResultStrip.
class _ResultHero extends StatelessWidget {
  final bool isLive;
  final double todayPnl;
  final int openCount;
  final double target;
  final double inrRate;
  final bool stale;

  const _ResultHero({required this.isLive, required this.todayPnl, required this.openCount, required this.target, required this.inrRate, required this.stale});

  @override
  Widget build(BuildContext context) {
    final prov = context.read<AppProvider>();
    final p = context.palette;
    return Selector<AppProvider, int>(
      selector: (_, x) => Object.hash((x.openPnl * 100).round(), (x.mainToday * 100).round()),
      builder: (context, _, __) {
        final head = isLive ? prov.openPnl : todayPnl;
        final label = isLive ? 'Open P&L now (live account)' : 'Today P&L - Main bot';
        final sub = isLive ? '$openCount open positions' : 'Closed trades only. Today = since 5:30 AM IST.';
        final showRing = !isLive && target > 0;
        final pct = showRing ? todayPnl / target : 0.0;
        return Container(
          padding: const EdgeInsets.all(AppSpacing.l),
          decoration: BoxDecoration(
            gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [p.accent.withOpacity(0.07), p.surface]), // Round E: hero card (Round G: calmer tint, the text stays readable)
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: p.accent.withOpacity(0.25)),
            boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.08), blurRadius: 12, offset: const Offset(0, 4))],
          ),
          child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(letterSpacing: 1.0, fontWeight: FontWeight.w700))),
                if (stale) Padding(padding: const EdgeInsets.only(left: 8), child: OwlPill('stale', tone: 'warn')),
              ]),
              const SizedBox(height: 6),
              OwlNumber(head, suffix: 'USDT', size: 34, animate: true),
              OwlInr(head, inrRate),
              const SizedBox(height: 2),
              Text(sub, style: context.type.metadata.copyWith(color: p.textMuted)),
            ]),
          ),
          if (showRing) ...[
            const SizedBox(width: AppSpacing.m),
            OwlRing(fraction: pct, center: '${(pct * 100).round()}%', caption: 'target', tone: todayPnl >= target ? 'good' : '', size: 72),
          ],
        ]));
      },
    );
  }
}

/// Part 10 (D2a, 28 Nov 2026): the Dashboard hero on the shared kit (OwlHeroCard). Same numbers, same rules as the old _ResultHero below it
/// (which stays in the file, unused, nothing deleted): Main bot TODAY, closed trades only; live mode shows the live open P&L; a target ring only when a target is set;
/// a small "stale" pill if the last refresh failed; the approx. INR line under the number. The big number is tinted green / red by its sign.
class _ResultHeroKit extends StatelessWidget {
  final bool isLive;
  final double todayPnl;
  final int openCount;
  final double target;
  final double inrRate;
  final bool stale;

  const _ResultHeroKit({required this.isLive, required this.todayPnl, required this.openCount, required this.target, required this.inrRate, required this.stale});

  @override
  Widget build(BuildContext context) {
    final prov = context.read<AppProvider>();
    return Selector<AppProvider, int>(
      selector: (_, x) => Object.hash((x.openPnl * 100).round(), (x.mainToday * 100).round()),
      builder: (context, _, __) {
        final head = isLive ? prov.openPnl : todayPnl;
        final label = isLive ? 'Open P&L now (live account)' : 'Today P&L - Main bot';
        var sub = isLive ? '$openCount open positions' : 'Closed trades only. Today = since 5:30 AM IST.';
        final inr = fmtInr(head, inrRate);
        if (inr != null) sub = 'approx. $inr  -  $sub';
        final showRing = !isLive && target > 0;
        final pct = showRing ? todayPnl / target : 0.0;
        final tone = head > 0 ? 'good' : (head < 0 ? 'bad' : '');
        Widget? trailing;
        if (showRing || stale) {
          trailing = Row(mainAxisSize: MainAxisSize.min, children: [
            if (stale) const OwlPill('stale', tone: 'warn'),
            if (showRing) ...[
              if (stale) const SizedBox(width: 8),
              OwlRing(fraction: pct, center: '${(pct * 100).round()}%', caption: '', tone: todayPnl >= target ? 'good' : '', size: 52),
            ],
          ]);
        }
        return OwlHeroCard(
          label: label.toUpperCase(),
          value: '${fmtSigned(head)} USDT',
          sub: sub,
          tone: tone,
          trailing: trailing,
        );
      },
    );
  }
}

/// Part 10: turns a list of OwlStat (value, label, tone, tap) into kit tiles, two per row. A tile with a tap is wrapped so the whole tile is tappable.
Widget _kitStatGrid(List<OwlStat> stats) {
  Widget tile(OwlStat s) {
    final t = OwlStatTile(label: s.label, value: s.value, sub: s.sub, tone: s.tone);
    if (s.onTap == null) return t;
    return GestureDetector(onTap: s.onTap, behavior: HitTestBehavior.opaque, child: t);
  }

  final rows = <Widget>[];
  for (var i = 0; i < stats.length; i += 2) {
    if (i > 0) rows.add(const SizedBox(height: AppSpacing.s));
    final pair = [tile(stats[i]), if (i + 1 < stats.length) tile(stats[i + 1])];
    rows.add(OwlStatRow(tiles: pair));
  }
  return Column(children: rows);
}

/// Plan B: the 4-column strip under the hero: OPEN P&L, BTC price, OPEN POSITIONS, SIGNALS (live mode: margin used + open positions, no paper stats).
/// Owner (5 Nov 2026): Win rate is out, the live BTC price is in (green/red by its last move; "--" until the first real price arrives).
/// BTC is read from the same light GET /api/btc/live the BTC tile uses, every 3 s, only while the Dashboard is on screen, one call at a time.
/// Taps: Open P&L and Open positions -> Positions (Live is its first tab), Signals -> Signals / Alerts screen, BTC -> Signals with the BTC chip on.
class _ResultStrip extends StatefulWidget {
  final bool isLive;
  final int openCount;

  const _ResultStrip({required this.isLive, required this.openCount});

  @override
  State<_ResultStrip> createState() => _ResultStripState();
}

class _ResultStripState extends State<_ResultStrip> {
  Timer? _timer;
  bool _busy = false;
  double? _btc;
  bool _up = true;

  @override
  void initState() {
    super.initState();
    _tick();
    _timer = AppActive.every(const Duration(seconds: 5), () => _tick()); // Part 7b: 3 s -> 5 s, none in the background
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _tick() async {
    if (_busy || !mounted || !TickerMode.of(context)) return;
    _busy = true;
    final d = await context.read<AppProvider>().getBtcJson('/api/btc/live');
    _busy = false;
    if (!mounted || d == null) return;
    final v = d['price'];
    final px = v is num ? v.toDouble() : double.tryParse('$v');
    if (px == null) return;
    setState(() {
      if (_btc != null && px != _btc) _up = px > _btc!;
      _btc = px;
    });
  }

  String _btcText() {
    final v = _btc;
    if (v == null) return '--';
    final s = (v >= 1000 ? v.round().toString() : v.toStringAsFixed(2));
    return s.replaceAllMapped(RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => '${m[1]},');
  }

  String _tone(double v) => v > 0 ? 'good' : (v < 0 ? 'bad' : '');

  @override
  Widget build(BuildContext context) {
    final prov = context.read<AppProvider>();
    void toPositions() => prov.goToRoute(AppRoute.positions);
    final openCount = widget.openCount;
    return Selector<AppProvider, String>(
      selector: (_, x) => '${(x.mainOpenPnl * 100).round()}|${x.mainOpenCount}|${x.signals.length}|${(x.openMarginUsed * 100).round()}',
      builder: (context, _, __) {
        final open = prov.mainOpenPnl;
        final stats = widget.isLive
            ? [
                OwlStat(prov.openMarginUsed.toStringAsFixed(2), 'Margin used'),
                OwlStat('$openCount', 'Open positions', onTap: toPositions),
              ]
            : [
                OwlStat(fmtSigned(open), 'Open P&L', tone: _tone(open), onTap: toPositions),
                OwlStat(_btcText(), 'BTC', tone: _btc == null ? '' : (_up ? 'good' : 'bad'), onTap: prov.openBtcSignals),
                OwlStat('$openCount', 'Positions', onTap: toPositions),
                OwlStat('${kLite ? DashTodaySignals.countToday(prov.signals) : prov.signals.length}', kLite ? 'Signals today' : 'Signals', onTap: () => prov.goToRoute(AppRoute.signals)),
              ];
        return _kitStatGrid(stats);
      },
    );
  }
}

/// Plan B: 7 days and 30 days, small, one row (paper mode). The numbers come from the same backend period totals as before.
class _PeriodRow extends StatelessWidget {
  const _PeriodRow();

  @override
  Widget build(BuildContext context) {
    final prov = context.read<AppProvider>();
    return Selector<AppProvider, String>(
      selector: (_, x) => '${(x.main7d * 100).round()}|${(x.main30d * 100).round()}|${x.main7dPartial}|${x.main30dPartial}',
      builder: (context, _, __) {
        // Part 10: two kit tiles under a small section header. The FULL signed number is printed (no "USDT" word beside it, so it is never cut).
        String tone(double v) => v > 0 ? 'good' : (v < 0 ? 'bad' : '');
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const OwlSectionHeader(title: 'Main bot', sub: 'last 7 and 30 days, USDT'),
          OwlStatRow(tiles: [
            OwlStatTile(label: prov.main7dPartial ? '7 days (partial)' : '7 days', value: fmtSigned(prov.main7d), tone: tone(prov.main7d)),
            OwlStatTile(label: prov.main30dPartial ? '30 days (partial)' : '30 days', value: fmtSigned(prov.main30d), tone: tone(prov.main30d)),
          ]),
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
