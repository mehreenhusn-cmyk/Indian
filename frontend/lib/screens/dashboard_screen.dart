import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:fl_chart/fl_chart.dart';
import 'package:intl/intl.dart';
import '../providers/app_provider.dart';
import '../config_flags.dart';
import 'strategy_doctor_screen.dart';
import '../widgets/top_movers_card.dart';
import '../widgets/glass_card.dart';
import '../widgets/dashboard_cockpit.dart';
import '../widgets/diagnostics_card.dart';
import '../widgets/system_load_card.dart';
import '../widgets/tag_lab_tile.dart';
import '../widgets/btc_live_tile.dart';
import '../widgets/live_wallet_card.dart';
import '../widgets/owl_animated_pnl.dart';
import '../widgets/owl_connection_indicator.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_skeleton.dart';
import '../widgets/pnl_calendar.dart';
import '../theme/app_theme.dart';

/// Everything the dashboard BODY shows that is NOT a per-tick price number.
/// The body only rebuilds when this value changes - a plain 250ms price tick
/// leaves it untouched, so the whole 1000-line page stops rebuilding on every
/// tick. The fast-moving parts (hero P&L card, connection indicator) have
/// their own small Selectors below.
int _dashBodySig(AppProvider p) {
  final s = p.status;
  return Object.hashAll([
    s.isEmpty,
    p.error,
    s['last_error'],
    p.statsMode,
    s['today_pnl_usdt'],
    s['open_count'],
    s['win_rate'],
    s['signals_today'],
    s['symbols_tracked'],
    s['last_reconcile']?.toString(),
    p.settings['daily_target_usdt'],
    p.settings['daily_loss_limit_usdt'],
    p.settings['trading_enabled'],
    (p.openMarginUsed * 100).round(),
    p.liveWallet?['ok'],
    identityHashCode(p.equityCurve),
    p.equityTf,
    identityHashCode(p.calendarData),
    p.signalsRev,
  ]);
}

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
            // First load only: no status yet and no error -> shimmer placeholders
            // instead of a screen of zeros. A failed connect (error != null) falls
            // through to the normal error banner.
            if (status.isEmpty && provider.error == null) {
              return const _DashboardSkeleton();
            }
            // STRICT STATE ISOLATION (see api_server.py's _display_status()):
            // today_pnl_usdt/win_rate are PAPER-only stats and come back as
            // `null` from the backend whenever live trading is on -
            // provider.statsMode tells this screen which case it's in, so
            // it can show real live-derived numbers instead of a stale/
            // irrelevant paper figure (e.g. a leftover paper loss) sitting
            // next to real Binance positions.
            final isLiveStats = provider.statsMode == 'live';
            final pnl = status['today_pnl_usdt'] ?? 0.0;
            final openCount = status['open_count'] ?? 0;
            final winRate = status['win_rate'] ?? 0.0;
            final signalsToday = status['signals_today'] ?? 0;
            // Real, backend-computed aggregate from whichever open_positions
            // set is actually being shown (paper or live) - see AppProvider's
            // openPnl/openMarginUsed docs. Previously `status['open_pnl']`
            // was read here but NEVER populated by the backend at all, so
            // this card silently always showed 0.00 regardless of mode.
            final connError = provider.error;
            final botError = status['last_error'];

            // Daily risk guardrails - same formula app.py's own
            // _daily_target_hit()/_daily_loss_limit_hit() use server-side
            // to actually pause auto-trading, mirrored here purely for
            // display so the user can SEE why new signals stopped opening
            // trades instead of it looking like the bot silently died.
            // Skipped entirely in LIVE mode - the PAPER today_pnl_usdt this
            // compares against is blocked to null/0 here on purpose (see
            // isLiveStats above), so a target/loss-limit reading computed
            // from it would be meaningless, not just stale.
            final dailyTarget = (provider.settings['daily_target_usdt'] as num?)?.toDouble() ?? 0.0;
            final dailyLossLimit = (provider.settings['daily_loss_limit_usdt'] as num?)?.toDouble() ?? 0.0;
            final todayPnl = (pnl as num).toDouble();
            final targetHit = !isLiveStats && dailyTarget > 0 && todayPnl >= dailyTarget;
            final lossLimitHit = !isLiveStats && dailyLossLimit > 0 && todayPnl <= -dailyLossLimit;

            return OWLRefresh(
              onRefresh: () => provider.fetchStatus().timeout(const Duration(seconds: 6), onTimeout: () {}),
              child: SingleChildScrollView(
              physics: owlPullPhysics,
              padding: const EdgeInsets.all(AppSpacing.l),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Connection / bot error banner — previously provider.error
                  // was tracked but never shown anywhere, so a dead backend
                  // or a stuck watchlist looked identical to "fresh start,
                  // 0 coins" with no way to tell them apart from the app.
                  if (connError != null)
                    _ErrorBanner(
                      icon: Icons.cloud_off,
                      text: connError,
                    ),
                  if (connError == null && botError != null)
                    _ErrorBanner(
                      icon: Icons.warning_amber_rounded,
                      text: 'Bot: $botError',
                    ),
                  if (connError != null || botError != null) const SizedBox(height: 12),
                  // Discipline / risk guardrail banner - new auto-trades stop
                  // opening the moment either of these is true (see app.py's
                  // _open_signal gate); shown here so it's visible, not just
                  // an invisible reason signals are being skipped.
                  if (lossLimitHit)
                    const _RiskBanner(
                      icon: Icons.lock_clock,
                      text: 'Daily loss limit hit - auto-trading paused for today',
                      isLoss: true,
                    ),
                  if (!lossLimitHit && targetHit)
                    const _RiskBanner(
                      icon: Icons.emoji_events,
                      text: 'Daily target hit - auto-trading paused for today',
                      isLoss: false,
                    ),
                  if (targetHit || lossLimitHit) const SizedBox(height: 12),
                  // Header
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Dashboard',
                        style: AppTypography.heroNumber.copyWith(
                          fontSize: 24,
                          color: context.palette.textPrimary,
                        ),
                      ),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          // FINAL ROUND: master trading pause/resume pill -
                          // separate from LiveTickerBar's PAPER/LIVE mode
                          // pill and from the LINK badge below (websocket
                          // health only). This one reflects/toggles
                          // settings['trading_enabled'] (default ON when
                          // the key hasn't been set yet - see
                          // execution_router.py's is_trading_enabled()).
                          // Tapping it pauses/resumes NEW order placement
                          // server-side while market data/LTP polling and
                          // manual closes keep running exactly as before.
                          _MasterTradingTogglePill(
                            enabled: (provider.settings['trading_enabled'] as bool?) ?? true,
                            onToggle: (next) => provider.updateSettings({'trading_enabled': next})
                                .then((result) => result != null && result['trading_enabled'] == next),
                          ),
                          const SizedBox(width: 8),
                          // Real link health (was the hand-rolled LINK badge):
                          // BE = last REST call had no error, WS = socket
                          // state, latency = real WS round-trip.
                          Selector<AppProvider, int>(
                            selector: (_, p) => Object.hash(p.error == null, p.wsConnected, p.wsLatencyMs),
                            builder: (context, _, __) {
                              final p = context.read<AppProvider>();
                              return OWLConnectionIndicator(
                                isBackendLive: p.error == null,
                                isWsLive: p.wsConnected,
                                latency: p.wsLatencyMs,
                              );
                            },
                          ),
                        ],
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Bot is running and monitoring ${status['symbols_tracked'] ?? 0} coins',
                    style: AppTypography.primaryData.copyWith(color: context.palette.textSecondary, fontSize: 14),
                  ),
                  if (status['last_reconcile'] is Map)
                    _CatchUpLine(Map<String, dynamic>.from(status['last_reconcile'] as Map)),
                  const SizedBox(height: 16),

                  // DASHBOARD MOUNTING - real feed/latency/guard/error
                  // telemetry, wired straight to AppProvider (see
                  // diagnostics_card.dart). Kept at the top, right under the
                  // header, so ops health is always the first thing visible.
                  const DiagnosticsCard(),

                  // Backend load (CPU/RAM/disk, Binance feed, broadcaster,
                  // candle polling, AI assistant) - see system_load_card.dart.
                  const SystemLoadCard(),

                  // Tag Lab - which mix of both indicators makes money (read-only, opens tag_lab_screen.dart)
                  // BTC live price + BTC's own result today (apart from the alt coins)
                  const BtcLiveTile(),
                  const DualBotTile(),
                  const TagLabTile(),

                  // Strategy Doctor - which entries lose / win (read-only, see strategy_doctor_screen.dart)
                  if (kShowStrategyDoctor) const StrategyDoctorCard(),

                  // AI Insights - win rate by SD zone / session / EMA / volume
                  // plus MFE/MAE, straight from ai_stats.py (see
                  // ai_insights_card.dart).
                  // AI Insights card removed (it was built from the old AI's paper stats).
                  // LIVE account: real Binance wallet card instead.
                  if (isLiveStats) ...[
                    const LiveWalletCard(),
                    const SizedBox(height: AppSpacing.cardGap),
                  ],

                  // COCKPIT - one compact card: ring gauge (P&L inside, fills
                  // toward the daily target) + Open P&L / Win / Positions /
                  // Signals. STRICT STATE ISOLATION unchanged: in LIVE mode
                  // the paper-only P&L Today / Win Rate are replaced with
                  // real live-derived numbers (Live Open P&L / Margin Used).
                  DashboardCockpit(
                    isLive: isLiveStats,
                    todayPnl: todayPnl,
                    dailyTarget: dailyTarget,
                    targetHit: targetHit,
                    openCount: (openCount as num).toInt(),
                    winRate: (winRate as num).toDouble(),
                    signalsToday: (signalsToday as num).toInt(),
                    marginUsed: provider.openMarginUsed,
                    goToTab: provider.goToTab,
                  ),
                  if (isLiveStats) ...[
                    const SizedBox(height: 8),
                    Text(
                      'LIVE mode: paper Today P&L / Win Rate are hidden here - shown numbers are real open Binance positions.',
                      style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 10.5),
                    ),
                  ],

                  const TopMoversCard(),

                  const SizedBox(height: 20),

                  // Equity Curve Chart + timeframe selector
                  _EquityChart(provider.equityCurve, provider.equityTf,
                      (tf) => provider.fetchEquity(tf: tf)),

                  const SizedBox(height: 12),

                  // Daily P&L calendar (closed trades, after fee) right under the equity curve
                  PnlCalendar(
                    data: provider.calendarData,
                    onMonthChanged: (m) => provider.fetchCalendar(month: m),
                  ),

                ],
              ),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// One modular box of the dashboard bento grid: icon + small label on top,
/// big value below, optional thin progress bar. Tappable tiles get the same
/// press-scale + haptic as every other OWLPressable.
class _BentoTile extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color? valueColor;
  final double? progress; // 0..1, null = no bar
  final VoidCallback? onTap;

  /// Optional numeric form of [value]: when given, the big number counts
  /// smoothly to its new value instead of jumping.
  final double? number;
  final int digits;
  final String suffix;

  const _BentoTile({
    required this.icon,
    required this.label,
    required this.value,
    this.valueColor,
    this.progress,
    this.onTap,
    this.number,
    this.digits = 0,
    this.suffix = '',
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final tile = GlassCard(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.cardPad),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Icon(icon, size: 14, color: p.textMuted),
                const SizedBox(width: 6),
                Expanded(
                  child: Text(
                    label.toUpperCase(),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: t.label.copyWith(letterSpacing: 0.6),
                  ),
                ),
                if (onTap != null)
                  Icon(Icons.chevron_right_rounded, size: 16, color: p.textMuted),
              ],
            ),
            const SizedBox(height: AppSpacing.s),
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: number == null
                  ? Text(
                      value,
                      maxLines: 1,
                      style: AppTypography.numberLarge.copyWith(color: valueColor ?? p.textPrimary),
                    )
                  : TweenAnimationBuilder<double>(
                      tween: Tween<double>(end: number),
                      duration: const Duration(milliseconds: 450),
                      curve: Curves.easeOutCubic,
                      builder: (context, v, _) => Text(
                        '${v.toStringAsFixed(digits)}$suffix',
                        maxLines: 1,
                        style: AppTypography.numberLarge.copyWith(color: valueColor ?? p.textPrimary),
                      ),
                    ),
            ),
            if (progress != null) ...[
              const SizedBox(height: AppSpacing.s),
              ClipRRect(
                borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 4,
                  backgroundColor: p.border,
                  valueColor: AlwaysStoppedAnimation<Color>(p.profit),
                ),
              ),
            ],
          ],
        ),
      ),
    );
    if (onTap == null) return tile;
    return OWLPressable(pressedScale: 0.98, onTap: onTap, child: tile);
  }
}

class _RiskBanner extends StatelessWidget {
  final IconData icon;
  final String text;
  final bool isLoss;

  const _RiskBanner({required this.icon, required this.text, required this.isLoss});

  @override
  Widget build(BuildContext context) {
    final color = isLoss ? context.palette.loss : context.palette.profit;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: color.withOpacity(0.15),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: color.withOpacity(0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: AppTypography.secondaryData.copyWith(color: color, fontSize: 12, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }
}

class _ErrorBanner extends StatelessWidget {
  final IconData icon;
  final String text;

  const _ErrorBanner({required this.icon, required this.text});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: context.palette.loss.withOpacity(0.15),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: context.palette.loss.withOpacity(0.4)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: context.palette.loss, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: AppTypography.secondaryData.copyWith(color: context.palette.loss, fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatCard extends StatelessWidget {
  final String title;
  final String value;
  final Color color;
  final VoidCallback? onTap;

  const _StatCard({required this.title, required this.value, required this.color, this.onTap});

  @override
  Widget build(BuildContext context) {
    final card = GlassCard(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.l - 2),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: AppTypography.secondaryData.copyWith(color: context.palette.textSecondary, fontSize: 12),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              style: AppTypography.primaryData.copyWith(color: color, fontSize: 18, fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
    if (onTap == null) return card;
    // Issue #3: "Open Positions" tap -> Positions tab (index 1). Wrapped
    // here (rather than only on that one call site) so ANY _StatCard can
    // become tappable the same way, with a visible ink-splash so it reads
    // as interactive rather than looking identical to the non-tappable
    // cards next to it.
    return ClipRRect(
      borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
      child: Material(
        color: Colors.transparent,
        child: InkWell(onTap: onTap, child: card),
      ),
    );
  }
}

/// "Last catch-up" line: shows when the bot last re-checked open trades
/// after a restart / data gap / reconnect and what it found.
class _CatchUpLine extends StatelessWidget {
  final Map<String, dynamic> info;
  const _CatchUpLine(this.info);

  @override
  Widget build(BuildContext context) {
    final ts = (info['ts'] as num?)?.toDouble();
    if (ts == null) return const SizedBox.shrink();
    final at = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round());
    final hh = at.hour.toString().padLeft(2, '0');
    final mm = at.minute.toString().padLeft(2, '0');
    final checked = (info['checked'] as num?)?.toInt() ?? 0;
    final closed = (info['closed'] as num?)?.toInt() ?? 0;
    final gap = (info['gap_s'] as num?)?.toInt() ?? 0;
    final gapText = gap >= 60 ? '${gap ~/ 60}m gap' : '${gap}s gap';
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Text(
        'Last catch-up $hh:$mm · $gapText · $checked open checked'
        '${closed > 0 ? ' · $closed closed while away' : ''}',
        style: AppTypography.metadata.copyWith(color: closed > 0 ? context.palette.warning : context.palette.textMuted, fontSize: 11),
      ),
    );
  }
}

const _equityTfOptions = ['15m', '1h', '2h', '1d', '3d', '7d'];

class _EquityChart extends StatelessWidget {
  final List<Map<String, dynamic>> data;
  final String selectedTf;
  final ValueChanged<String> onTfChanged;

  const _EquityChart(this.data, this.selectedTf, this.onTfChanged);

  double _num(dynamic v) => (v is num) ? v.toDouble() : 0.0;

  String _label(dynamic v) {
    final d = (v ?? '').toString();
    if (d == 'start') return 'start';
    // "2026-09-24" -> "09-24"; "14:30" stays as is.
    return (d.length == 10 && d[4] == '-') ? d.substring(5) : d;
  }

  @override
  Widget build(BuildContext context) {
    final tfRow = SizedBox(
      height: 32,
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: _equityTfOptions.map((tf) {
          final isSelected = tf == selectedTf;
          return Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(
              label: Text(tf),
              selected: isSelected,
              // No check-mark: it made the selected chip wider and pushed
              // the last chip ("7d") half off-screen.
              showCheckmark: false,
              onSelected: (_) => onTfChanged(tf),
              backgroundColor: context.palette.glassFill,
              selectedColor: context.palette.accent.withOpacity(0.25),
              labelStyle: AppTypography.secondaryData.copyWith(color: isSelected ? context.palette.accent : context.palette.textSecondary, fontSize: 12, fontWeight: isSelected ? FontWeight.w700 : FontWeight.normal),
              side: BorderSide(
                color: isSelected ? context.palette.accent : Colors.transparent,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 4),
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              visualDensity: VisualDensity.compact,
            ),
          );
        }).toList(),
      ),
    );

    Widget shell(List<Widget> children) => GlassCard(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.l),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
          ),
        );

    if (data.isEmpty) {
      return shell([
        Text('Equity Curve',
            style: AppTypography.primaryData.copyWith(color: context.palette.textPrimary, fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        tfRow,
        Padding(
          padding: const EdgeInsets.all(AppSpacing.section),
          child: Center(
            child: Text('No trades yet - baseline will fill in once trading starts',
                textAlign: TextAlign.center,
                style: context.type.secondary.copyWith(color: context.palette.textMuted)),
          ),
        ),
      ]);
    }

    // Values can arrive as int (e.g. 0) - always go through _num, a raw
    // `?? 0.0` handed an int to FlSpot and silently broke the whole chart.
    final ys = data.map((e) => _num(e['cumulative'])).toList();
    // A single point draws nothing; duplicate it so a flat line still shows.
    final plotYs = ys.length == 1 ? [ys.first, ys.first] : ys;
    final spots = <FlSpot>[
      for (int i = 0; i < plotYs.length; i++) FlSpot(i.toDouble(), plotYs[i]),
    ];

    final maxY = plotYs.fold<double>(0, (a, b) => a > b ? a : b);
    final minY = plotYs.fold<double>(0, (a, b) => a < b ? a : b);
    final range = (maxY - minY).abs() < 0.01 ? 1.0 : (maxY - minY).abs();
    final total = ys.last;
    final totalColor = total >= 0 ? context.palette.profit : context.palette.loss;
    final lineColor = total >= 0 ? context.palette.accent : context.palette.loss;
    final lastIdx = spots.length - 1;
    final hasTrades = data.any((e) => _num(e['pnl']) != 0);

    return shell([
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Equity Curve',
              style: AppTypography.primaryData.copyWith(color: context.palette.textPrimary, fontSize: 16, fontWeight: FontWeight.w700)),
          Text(
            '${total >= 0 ? '+' : ''}${total.toStringAsFixed(2)} USDT',
            style: AppTypography.primaryData.copyWith(color: totalColor, fontSize: 14, fontWeight: FontWeight.w700),
          ),
        ],
      ),
      const SizedBox(height: 8),
      tfRow,
      const SizedBox(height: 12),
      SizedBox(
        height: 160,
        child: LineChart(
          LineChartData(
            gridData: FlGridData(show: false),
            borderData: FlBorderData(show: false),
            titlesData: FlTitlesData(
              show: true,
              leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 20,
                  interval: 1,
                  getTitlesWidget: (value, meta) {
                    final i = value.toInt();
                    if (value != i.toDouble() || i < 0 || i >= data.length) {
                      return const SizedBox.shrink();
                    }
                    // Only first / middle / last label so they never overlap.
                    if (i != 0 && i != data.length - 1 && i != data.length ~/ 2) {
                      return const SizedBox.shrink();
                    }
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(_label(data[i]['date']),
                          style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 9)),
                    );
                  },
                ),
              ),
            ),
            extraLinesData: ExtraLinesData(horizontalLines: [
              HorizontalLine(
                y: 0,
                color: context.palette.textMuted.withOpacity(0.35),
                strokeWidth: 1,
                dashArray: [4, 4],
              ),
            ]),
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                tooltipBgColor: const Color(0xFF1B222C),
                getTooltipItems: (touched) => touched.map((t) {
                  final i = t.x.toInt().clamp(0, data.length - 1).toInt();
                  final pnl = _num(data[i]['pnl']);
                  return LineTooltipItem(
                    '${_label(data[i]['date'])}\n'
                    'total ${t.y >= 0 ? '+' : ''}${t.y.toStringAsFixed(2)}\n'
                    'this bucket ${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)}',
                    AppTypography.metadata.copyWith(color: Colors.white, fontSize: 11),
                  );
                }).toList(),
              ),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: spots,
                isCurved: spots.length > 3,
                curveSmoothness: 0.2,
                preventCurveOverShooting: true,
                color: lineColor,
                barWidth: 2.5,
                dotData: FlDotData(
                  show: true,
                  checkToShowDot: (spot, barData) =>
                      spots.length <= 12 || spot.x.toInt() == lastIdx,
                ),
                belowBarData: BarAreaData(
                  show: true,
                  color: lineColor.withOpacity(0.12),
                ),
              ),
            ],
            minY: minY - range * 0.15,
            maxY: maxY + range * 0.15,
          ),
        ),
      ),
      if (!hasTrades)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('No closed trades in this window yet - flat baseline shown',
              style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 11)),
        ),
    ]);
  }
}

/// FINAL ROUND: master ON/OFF pill for auto-trading, header row of
/// DashboardScreen. Reflects settings['trading_enabled'] (server default
/// True/ON when the key hasn't been explicitly set yet - see
/// execution_router.py's is_trading_enabled()). Tapping calls
/// `onToggle` (wired to provider.updateSettings in DashboardScreen's
/// build()) and shows a tiny inline spinner while the request is in
/// flight, so a slow/dropped connection can't look like a silent no-op or
/// let a double-tap fire two toggles in a row. Market data/LTP polling
/// and manual position closes are NOT gated by this pill - only new
/// order placement is (server-side, execution_router.py).
class _MasterTradingTogglePill extends StatefulWidget {
  final bool enabled;
  final Future<bool> Function(bool next) onToggle;

  const _MasterTradingTogglePill({required this.enabled, required this.onToggle});

  @override
  State<_MasterTradingTogglePill> createState() => _MasterTradingTogglePillState();
}

class _MasterTradingTogglePillState extends State<_MasterTradingTogglePill> {
  bool _busy = false;

  Future<void> _handleTap() async {
    if (_busy) return;
    final next = !widget.enabled;
    setState(() => _busy = true);
    bool ok = false;
    try {
      ok = await widget.onToggle(next);
    } catch (_) {
      ok = false;
    }
    if (!mounted) return;
    setState(() => _busy = false);
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            next
                ? 'Could not resume the bot - check your connection and try again'
                : 'Could not pause the bot - check your connection and try again',
          ),
          backgroundColor: context.palette.loss,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final isOn = widget.enabled;
    final color = isOn ? context.palette.profit : context.palette.warning;
    return GestureDetector(
      onTap: _handleTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: color.withOpacity(0.18),
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: color.withOpacity(0.55), width: 1),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (_busy)
              SizedBox(
                width: 12,
                height: 12,
                child: CircularProgressIndicator(strokeWidth: 2, color: color),
              )
            else
              isOn
                  ? _PulseDot(color: color)
                  : Icon(Icons.pause_circle_filled, size: 14, color: color),
            const SizedBox(width: 6),
            Text(
              isOn ? 'BOT ON' : 'BOT PAUSED',
              style: AppTypography.secondaryData.copyWith(color: color, fontSize: 12, fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }
}


/// Shimmer placeholder for the Dashboard's very first load.
class _DashboardSkeleton extends StatelessWidget {
  const _DashboardSkeleton();

  @override
  Widget build(BuildContext context) {
    return const SingleChildScrollView(
      physics: NeverScrollableScrollPhysics(),
      padding: EdgeInsets.all(AppSpacing.l),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          OWLSkeleton(width: 140, height: 26),
          SizedBox(height: AppSpacing.l),
          OWLSkeleton.card(height: 90),
          SizedBox(height: AppSpacing.l),
          OWLSkeleton(width: 90, height: 12),
          SizedBox(height: AppSpacing.s),
          OWLSkeleton(width: 200, height: 40),
          SizedBox(height: AppSpacing.xxl),
          Row(
            children: [
              Expanded(child: OWLSkeleton.card(height: 70)),
              SizedBox(width: AppSpacing.m),
              Expanded(child: OWLSkeleton.card(height: 70)),
            ],
          ),
          SizedBox(height: AppSpacing.xl),
          OWLSkeleton.card(height: 180),
          SizedBox(height: AppSpacing.xl),
          OWLSkeleton.card(height: 64),
          SizedBox(height: AppSpacing.s),
          OWLSkeleton.card(height: 64),
        ],
      ),
    );
  }
}


/// Small breathing dot for the "BOT ON" pill - a calm live-heartbeat cue.
class _PulseDot extends StatefulWidget {
  final Color color;
  const _PulseDot({required this.color});

  @override
  State<_PulseDot> createState() => _PulseDotState();
}

class _PulseDotState extends State<_PulseDot> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1400))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 14,
      height: 14,
      child: AnimatedBuilder(
        animation: _c,
        builder: (context, _) => Center(
          child: Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              color: widget.color,
              shape: BoxShape.circle,
              boxShadow: [BoxShadow(color: widget.color.withOpacity(0.25 + 0.45 * _c.value), blurRadius: 3 + 6 * _c.value, spreadRadius: 0.5 + 1.5 * _c.value)],
            ),
          ),
        ),
      ),
    );
  }
}


/// Tiny equity line inside the hero card (no axes, no touch). Green when the
/// curve ends positive, red when negative; hidden until there are 2+ points.
class _Sparkline extends StatelessWidget {
  final List<Map<String, dynamic>> data;
  const _Sparkline(this.data);

  @override
  Widget build(BuildContext context) {
    final ys = <double>[
      for (final e in data) (e['cumulative'] is num) ? (e['cumulative'] as num).toDouble() : 0.0,
    ];
    if (ys.length < 2) return const SizedBox.shrink();
    final p = context.palette;
    final color = ys.last >= 0 ? p.profit : p.loss;
    final lo = ys.reduce((a, b) => a < b ? a : b);
    final hi = ys.reduce((a, b) => a > b ? a : b);
    final pad = (hi - lo).abs() < 0.01 ? 1.0 : (hi - lo) * 0.15;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.m),
      child: SizedBox(
        height: 44,
        child: LineChart(
          LineChartData(
            minY: lo - pad,
            maxY: hi + pad,
            gridData: FlGridData(show: false),
            borderData: FlBorderData(show: false),
            titlesData: FlTitlesData(show: false),
            lineTouchData: LineTouchData(enabled: false),
            lineBarsData: [
              LineChartBarData(
                spots: [for (var i = 0; i < ys.length; i++) FlSpot(i.toDouble(), ys[i])],
                isCurved: true,
                color: color,
                barWidth: 2,
                dotData: FlDotData(show: false),
                belowBarData: BarAreaData(
                  show: true,
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [color.withOpacity(0.22), color.withOpacity(0.0)],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
