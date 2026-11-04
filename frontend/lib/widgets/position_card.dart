import 'dart:async';
import 'dart:ui';
import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'candle_chart.dart';
import 'position_glance.dart';

const _accent = AppColors.accent;
const _green = AppColors.profit;
const _red = AppColors.loss;
const _tabular = [FontFeature.tabularFigures()];

/// Distance-to-SL threshold (% of current price) below which the card
/// flags itself as "near SL" - red border + warning icon. 0.5% matches
/// what the user asked for.
const _nearSlThresholdPct = 0.5;

/// Tolerance (as % of entry price) within which the resting SL is
/// considered "at breakeven" for the grey BE pill. Both paper and live
/// positions ultimately expose SL only as a plain price (effective_sl) -
/// there's no single boolean flag that survives both modes (paper's own
/// breakeven_auto_shifted is a monitor-loop-internal flag, live's
/// breakeven_done lives in protection_manager's SQLite meta and isn't
/// echoed onto the position dict the frontend receives) - so the BE pill
/// is derived the same way visually, straight from SL vs Entry, which is
/// exactly what "at breakeven" means regardless of which engine moved it
/// there.
const _breakevenTolerancePct = 0.15;

/// OBSIDIAN TERMINAL position card. Same data contract, same TP/SL/close
/// actions, same candle chart + lifecycle track as before - restyled into
/// a frosted glassmorphic surface with a neon ROI pill, a smooth animated
/// chevron drawer for the Entry/SL/TP ladder, a grey 'BE' badge once SL is
/// sitting at breakeven, and a red alert badge when the backend's guard
/// tick reports this symbol as currently unprotected (no resting stop on
/// the exchange).
class PositionCard extends StatefulWidget {
  final Map<String, dynamic> pos;
  const PositionCard({super.key, required this.pos});

  @override
  State<PositionCard> createState() => _PositionCardState();
}

/// ONE shared 1-second clock for every card. Before, each open position had its own Timer that rebuilt
/// the whole card every second (15 positions = 15 full rebuilds/s). Now only the small "Open Xm Ys"
/// text listens to this clock; the rest of the card rebuilds only when its data changes.
class _DurationClock {
  static final ValueNotifier<int> tick = ValueNotifier<int>(0);
  static Timer? _timer;
  static int _users = 0;

  static void join() {
    _users++;
    _timer ??= Timer.periodic(const Duration(seconds: 1), (_) => tick.value++);
  }

  static void leave() {
    _users--;
    if (_users <= 0) {
      _users = 0;
      _timer?.cancel();
      _timer = null;
    }
  }
}

class _PositionCardState extends State<PositionCard> {
  Timer? _chartRefreshTimer;
  Future<List<dynamic>>? _candlesFuture;
  String? _candlesSymbol;

  // Collapsed by default - shows just the header + one compact line (entry
  // price, LTP, P&L). Tapping the chevron expands to the full panel
  // (chart, lifecycle track, TP1-4/Entry/SL ladder, live price row).
  bool _expanded = false;

  @override
  void initState() {
    super.initState();
    // Keeps the "Open Xm Ys" label ticking (shared clock, only that text rebuilds).
    _DurationClock.join();
    // The 120-candle chart lives only in the EXPANDED panel, so candles are fetched when the card is
    // opened (see the chevron taps) and refreshed every 30 s only while it stays open.
    _chartRefreshTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (mounted && _expanded) _loadCandles(force: true);
    });
  }

  void _toggleExpanded([bool? v]) {
    final open = v ?? !_expanded;
    setState(() => _expanded = open);
    if (open) _loadCandles();
  }

  void _loadCandles({bool force = false}) {
    final symbol = widget.pos['symbol'] as String?;
    if (symbol == null) return;
    if (!force && symbol == _candlesSymbol && _candlesFuture != null) return;
    _candlesSymbol = symbol;
    _candlesFuture =
        Provider.of<AppProvider>(context, listen: false).fetchCandles(symbol, limit: 120); // 120 so EMA 30/50 are warmed up; card shows the last 40
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _DurationClock.leave();
    _chartRefreshTimer?.cancel();
    super.dispose();
  }

  String _fmt(num? v, {int digits = 4}) => v == null ? '--' : v.toStringAsFixed(digits);

  Widget _statCell(BuildContext context, String label, String value, {bool alignEnd = false, num? liveOpenedAt}) {
    final p = context.palette;
    return Expanded(
      child: Column(
        crossAxisAlignment: alignEnd ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Text(label, style: context.type.label.copyWith(fontSize: 9.5, color: p.textMuted, letterSpacing: 0.6)),
          const SizedBox(height: 1),
          liveOpenedAt == null
              ? Text(value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: context.type.secondary.copyWith(
                      fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary, fontFeatures: _tabular))
              : ValueListenableBuilder<int>(
                  valueListenable: _DurationClock.tick,
                  builder: (_, __, ___) => Text(_duration(liveOpenedAt),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.type.secondary.copyWith(
                          fontSize: 12.5, fontWeight: FontWeight.w600, color: p.textPrimary, fontFeatures: _tabular)),
                ),
        ],
      ),
    );
  }

  String _duration(num? openedAtTs) {
    if (openedAtTs == null) return '';
    final secs = (DateTime.now().millisecondsSinceEpoch / 1000 - openedAtTs).round();
    return fmtSpan(secs, withSeconds: true);
  }

  @override
  Widget build(BuildContext context) {
    // LIVE-SYNC SAFETY NET (freeze fix): re-resolve THIS card's position
    // straight from AppProvider.positions by id on every rebuild, instead
    // of trusting only whatever `widget.pos` the parent happened to pass
    // this pass. Provider.of(context) (listen: true) also subscribes this
    // card directly to every notifyListeners() the provider fires - so a
    // fresh WS/status tick updates this card's mark price/P&L immediately,
    // even in the (normally impossible, but no longer load-bearing) case
    // where some ancestor skips a rebuild. Falls back to widget.pos if the
    // position isn't found any more (just closed) so the card still renders
    // its last-known values for the brief frame before it's removed from
    // the list, instead of throwing.
    // SMOOTHNESS: subscribe through a Selector-style select() instead of
    // Provider.of(listen: true). The card now rebuilds ONLY when ITS OWN
    // position data (or its unprotected flag) actually changed - not on every
    // 250ms tick for every other position. The signature is the position's
    // whole map text, so no displayed field can ever be missed.
    final liveProvider = Provider.of<AppProvider>(context, listen: false);
    final cardId = widget.pos['id'];
    context.select<AppProvider, int>((p) {
      Object? mine;
      for (final x in p.positions) {
        if (x is Map && x['id'] == cardId) {
          mine = x;
          break;
        }
      }
      final sym = mine is Map ? mine['symbol'] : widget.pos['symbol'];
      return Object.hash('${mine ?? ''}', p.unprotectedPositions.any((u) => u['symbol'] == sym));
    });
    final pos = liveProvider.positions.firstWhere(
      (p) => p is Map && p['id'] == widget.pos['id'],
      orElse: () => widget.pos,
    ) as Map<String, dynamic>;
    // Symbol changed under us (shouldn't normally happen - cards are keyed
    // by trade - but guards against a stale chart if it ever does).
    if (_expanded && pos['symbol'] != _candlesSymbol) _loadCandles();

    // PART 1 HARDENING FIX: `id` is an int trade_id in PAPER mode, but the
    // exchange's *symbol* (a String, e.g. "BTCUSDT") in LIVE mode - see
    // kucoin_trader.py/binance_trader.py get_open_positions(), which sets
    // "id": p.get("symbol") because a live position has no local integer
    // id at all. The old `as int?` cast here threw on every live position
    // and crashed this screen the moment live_trading_enabled was on.
    final tradeId = pos['id'];
    final symbol = pos['symbol'] ?? '--';
    final action = pos['action'] ?? '--';
    final isLong = action == 'BUY';
    final entry = (pos['entry_price'] as num?)?.toDouble();
    final openedTs = (pos['opened_at_ts'] as num?)?.toDouble();
    final int? entryTsMs = openedTs != null ? (openedTs * 1000).round() : null;
    final ltp = (pos['ltp'] as num?)?.toDouble();
    final pnl = (pos['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
    final roi = (pos['roi_pct'] as num?)?.toDouble() ?? 0.0;
    final invest = (pos['invest_usdt'] as num?)?.toDouble();
    final isProfit = pnl >= 0;
    // Leverage: taken from the position when the backend sends it, else
    // derived from ROI / raw price move, else 1 - used only to show the
    // per-level USDT profit in the ladder (invest x price-move% x leverage).
    double lev = (pos['leverage'] as num?)?.toDouble() ?? 0.0;
    if (lev <= 0 && entry != null && entry != 0 && ltp != null && ltp != entry) {
      final raw = (isLong ? (ltp - entry) / entry : (entry - ltp) / entry) * 100.0;
      if (raw != 0) lev = (roi / raw).abs();
    }
    if (lev <= 0 || lev.isNaN || lev.isInfinite) lev = 1.0;
    double? profitAt(double? pct) =>
        (pct == null || invest == null) ? null : invest * (pct / 100.0) * lev;

    var sl = (pos['effective_sl'] as num?)?.toDouble();
    final userTarget = pos['user_target_tp'] as int?;

    // TP levels present on this position, in order 1->4. Comes straight
    // from the backend's effective_tp1-4 (strategy signal levels, or this
    // position's own synthesized TP1/TP2 if it's a percent-mode trade) -
    // no client-side re-synthesis needed, so this can never drift from
    // what the monitor loop is actually checking against.
    final tpLevels = <int, double?>{
      1: (pos['effective_tp1'] as num?)?.toDouble(),
      2: (pos['effective_tp2'] as num?)?.toDouble(),
      3: (pos['effective_tp3'] as num?)?.toDouble(),
      4: (pos['effective_tp4'] as num?)?.toDouble(),
    };
    final effectiveTarget =
        userTarget ?? tpLevels.entries.where((e) => e.value != null).map((e) => e.key).fold<int>(0, (a, b) => b > a ? b : a);

    // Distance to SL, as % of current price - drives the near-SL warning.
    double? slDistancePct;
    if (sl != null && ltp != null && ltp != 0) {
      slDistancePct = (isLong ? (ltp - sl) / ltp : (sl - ltp) / ltp).abs() * 100;
    }
    final nearSl = slDistancePct != null && slDistancePct <= _nearSlThresholdPct;

    // Grey 'BE' pill - SL sitting within tolerance of entry price. See
    // _breakevenTolerancePct's doc comment above for why this is derived
    // visually rather than from a mode-specific backend flag.
    final atBreakeven = sl != null &&
        entry != null &&
        entry != 0 &&
        ((sl - entry).abs() / entry * 100) <= _breakevenTolerancePct;

    // Red alert badge - this symbol's most recent guard_tick() found NO
    // resting protective stop on the exchange (live mode only; paper
    // positions are protected locally by the monitor loop, not by a
    // resting exchange order, so they're never in this list).
    final isUnprotected =
        liveProvider.unprotectedPositions.any((u) => u['symbol'] == symbol);

    // Backend flags (paper_trader.flag_outdated / catch-up): OUTDATED = an
    // opposite signal came but was missed or skipped, so this position no longer
    // matches the strategy; GAP = a restart / data gap happened while it was
    // open, so its peak and drawdown are estimated. Flags only - nothing closes.
    final outdatedReason = (pos['outdated_reason'] as String?)?.trim();
    final isOutdated = outdatedReason != null && outdatedReason.isNotEmpty;
    final hadGap = !isOutdated && pos['restart_affected'] == true;
    // AI badge (advice only): backend ai_miner.open_flags() adds `ai_flag` when this
    // open trade matches a CONFIRMED AVOID pattern. The bot never skips anything.
    final aiFlag = pos['ai_flag'] is Map ? Map<String, dynamic>.from(pos['ai_flag'] as Map) : null;
    final aiAvoid = aiFlag != null && aiFlag['verdict'] == 'AVOID';
    final aiLabels = aiFlag?['labels'];
    final aiAvoidWhy = aiAvoid && aiLabels is List ? aiLabels.join(' | ') : '';
    // ML badge (advice only): backend ai_ml.open_badges() adds `ml_flag` ONLY after the shadow
    // log proved the model (LEARNED) and this trade is in its weakest third. No number is shown.
    final mlFlag = pos['ml_flag'] is Map ? Map<String, dynamic>.from(pos['ml_flag'] as Map) : null;
    final mlAvoid = mlFlag != null && mlFlag['verdict'] == 'AVOID';

    // Dead/stale price feed detection (the 2U2USDTM bug class) - last_ok_ts
    // is set by the backend monitor loop every time it actually gets a live
    // price for this position; if it hasn't moved in a while, P&L is frozen
    // and the exchange is genuinely not giving us data for this symbol.
    // Falls back to opened_at_ts so a position isn't flagged in the few
    // seconds before its very first successful price tick.
    final lastOkTs = (pos['last_ok_ts'] as num?)?.toDouble() ?? (pos['opened_at_ts'] as num?)?.toDouble();
    final staleFeed = lastOkTs != null &&
        (DateTime.now().millisecondsSinceEpoch / 1000 - lastOkTs) > 120;

    // Ladder rows, farthest TP first (top) down to SL (bottom) - same order
    // as the old app. Every row shows price, price-move % and USDT profit.
    // No separate LTP row (LTP is already in the summary line): instead each
    // TP row is FILLED green from the left in proportion to how far the live
    // price has travelled from the previous level (Entry / previous TP) to
    // that TP - fully filled once the TP is reached. Same as the old app.
    final double? livePct = (entry != null && entry != 0 && ltp != null)
        ? (isLong ? (ltp - entry) / entry * 100 : (entry - ltp) / entry * 100)
        : null;
    double pctOf(double price) =>
        isLong ? (price - entry!) / entry! * 100 : (entry! - price) / entry! * 100;
    final tpPct = <int, double>{};
    if (entry != null && entry != 0) {
      for (final level in [1, 2, 3, 4]) {
        final price = tpLevels[level];
        if (price != null) tpPct[level] = pctOf(price);
      }
    }
    final tpFill = <int, double>{};
    var prevPct = 0.0;
    for (final level in [1, 2, 3, 4]) {
      final pct = tpPct[level];
      if (pct == null) continue;
      double f = 0.0;
      if (livePct != null) {
        final span = pct - prevPct;
        f = span > 0 ? ((livePct - prevPct) / span).clamp(0.0, 1.0) : (livePct >= pct ? 1.0 : 0.0);
      }
      tpFill[level] = f;
      if (pct > prevPct) prevPct = pct;
    }
    final rows = <_LadderRow>[];
    for (final level in [4, 3, 2, 1]) {
      final price = tpLevels[level];
      if (price == null) continue;
      final pct = tpPct[level];
      rows.add(_LadderRow(
        label: 'TP$level',
        price: price,
        pct: pct,
        profit: profitAt(pct),
        isTarget: level == effectiveTarget,
        fill: tpFill[level] ?? 0.0,
        onTap: tradeId == null
            ? null
            : () => _onTapTp(context, tradeId, level, price, ltp, isLong),
      ));
    }
    rows.add(_LadderRow(label: 'ENTRY', price: entry, pct: 0.0, isEntry: true));
    if (sl != null) {
      final slPct = (entry != null && entry != 0) ? pctOf(sl) : null;
      rows.add(_LadderRow(
          label: 'SL', price: sl, pct: slPct, profit: profitAt(slPct), isSl: true, isBreakeven: atBreakeven));
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: _GlassmorphicSurface(
        stripColor: isProfit ? _green : _red,
        highlightBorder: nearSl ? _red : (isUnprotected ? _red : null),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.s),
          // Only the HEADER (title / ROI pill / chevron), the one-line summary
          // and the collapsed P&L row toggle expand/collapse. The expanded
          // panel (chart, TP/Entry/SL ladder, live-price row) is NOT wrapped,
          // so tapping around the ladder never collapses the card.
          child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
              GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => _toggleExpanded(),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                // Header row
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Expanded(
                    child: Wrap(
                      crossAxisAlignment: WrapCrossAlignment.center,
                      spacing: 6,
                      runSpacing: 4,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.s, vertical: AppSpacing.xs),
                          decoration: BoxDecoration(
                            color: (isLong ? _green : _red).withOpacity(0.16),
                            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                            border: Border.all(color: (isLong ? _green : _red).withOpacity(0.4), width: 0.5),
                          ),
                          child: Text(action,
                              style: AppTypography.secondaryData.copyWith(
                                  color: isLong ? _green : _red,
                                  fontWeight: FontWeight.w700,
                                  fontSize: 11)),
                        ),
                        Text(
                            // A live tradeId IS the symbol already -
                            // showing "#BTCUSDT BTCUSDT" would be
                            // redundant, so only prefix with "#" for
                            // the PAPER int id.
                            tradeId is int ? '#$tradeId $symbol' : '$symbol',
                            overflow: TextOverflow.ellipsis,
                            style: context.type.section.copyWith(fontSize: 14, fontWeight: FontWeight.w700)),
                        if (atBreakeven) const _BadgePill(text: 'BE', color: AppColors.textSecondary),
                        if (isUnprotected)
                          const _BadgePill(text: 'UNPROTECTED', color: _red, filled: true),
                        if (nearSl) const Icon(Icons.warning_amber_rounded, size: 15, color: _red),
                        if (staleFeed) const _BadgePill(text: 'NO LIVE FEED', color: AppColors.warning),
                        if (isOutdated)
                          Tooltip(
                            message: 'Opposite ${pos['outdated_signal'] ?? ''} signal not acted on: $outdatedReason',
                            triggerMode: TooltipTriggerMode.tap,
                            showDuration: const Duration(seconds: 6),
                            child: const _BadgePill(text: 'OUTDATED', color: _red, filled: true),
                          ),
                        if (aiAvoid)
                          Tooltip(
                            message: 'AI advice (the bot still keeps this trade): this setup was weak on new trades before too - $aiAvoidWhy',
                            triggerMode: TooltipTriggerMode.tap,
                            showDuration: const Duration(seconds: 6),
                            child: const _BadgePill(text: 'AI: AVOID', color: AppColors.warning),
                          ),
                        if (mlAvoid)
                          Tooltip(
                            message: 'ML advice (the bot still keeps this trade): the model learned from real results on new trades and rates this setup weak',
                            triggerMode: TooltipTriggerMode.tap,
                            showDuration: const Duration(seconds: 6),
                            child: const _BadgePill(text: 'ML: AVOID', color: AppColors.warning),
                          ),
                        if (hadGap)
                          Tooltip(
                            message: 'The bot restarted or lost data while this trade was open. Its highest profit and deepest loss are estimated from candles.',
                            triggerMode: TooltipTriggerMode.tap,
                            child: const _BadgePill(text: 'RESTARTED', color: AppColors.warning),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 6),
                  _ProfitBlock(pnl: pnl, isProfit: isProfit),
                  const SizedBox(width: 2),
                  InkWell(
                    borderRadius: BorderRadius.circular(16),
                    onTap: () => _toggleExpanded(),
                    child: Padding(
                      padding: const EdgeInsets.all(4),
                      // Smooth 180° turn instead of an instant icon swap -
                      // matches the Alerts tab's expand/collapse feel.
                      child: AnimatedRotation(
                        turns: _expanded ? 0.5 : 0,
                        duration: AppMotion.base,
                        curve: AppMotion.standard,
                        child: Icon(
                          Icons.keyboard_arrow_down_rounded,
                          color: context.palette.textSecondary,
                        ),
                      ),
                    ),
                  ),
                ],
              ),
              // Compact one-line summary - always visible even when
              // collapsed, so "where's the entry/price" is answered
              // without expanding.
              const SizedBox(height: 6),
              Row(
                children: [
                  _statCell(context, 'ENTRY', _fmt(entry)),
                  _statCell(context, 'LTP', _fmt(ltp)),
                  _statCell(context, 'OPEN', '', alignEnd: true, liveOpenedAt: pos['opened_at_ts'] as num?),
                ],
              ),
              if (livePct != null && tpPct[effectiveTarget] != null && tpPct[effectiveTarget]! > 0)
                _ProgressToTarget(
                  livePct: livePct,
                  targetPct: tpPct[effectiveTarget]!,
                  slPct: (sl != null && entry != null && entry != 0) ? pctOf(sl) : null,
                  targetLabel: 'TP$effectiveTarget',
                ),
                  ],
                ),
              ),
              // Smooth height animation between the collapsed one-liner
              // and the full expanded panel, instead of an abrupt jump.
              AnimatedSize(
                duration: AppMotion.base,
                curve: AppMotion.standard,
                alignment: Alignment.topCenter,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (!_expanded) ...[
                      // Plain-words risk/target bar: stop <- price -> target.
                      PositionGlanceBar(
                        entry: entry,
                        ltp: ltp,
                        sl: sl,
                        target: effectiveTarget > 0 ? tpLevels[effectiveTarget] : null,
                        targetLabel: 'TP$effectiveTarget',
                        fmt: (v) => _fmt(v),
                      ),
                      const SizedBox(height: 2),
                      GestureDetector(
                        behavior: HitTestBehavior.opaque,
                        onTap: () => _toggleExpanded(true),
                        child: Row(
                        mainAxisAlignment: MainAxisAlignment.end,
                        children: [
                          if (tradeId != null)
                            TextButton(
                              style: TextButton.styleFrom(
                                foregroundColor: _red,
                                padding: const EdgeInsets.symmetric(horizontal: 8),
                                minimumSize: Size.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                              onPressed: () => _confirmClose(context, tradeId, symbol),
                              child: Text(staleFeed ? 'Force Close' : 'Close'),
                            ),
                        ],
                      ),
                      ),
                    ],
                    if (_expanded) ...[
                      if (staleFeed) ...[
                        const SizedBox(height: 4),
                        const Text(
                          'No live price update in a while - P&L is frozen. Closing will '
                          'force-close at the last-known price.',
                          style: TextStyle(color: AppColors.warning, fontSize: 11, fontWeight: FontWeight.w600),
                        ),
                      ],
                      if (isUnprotected) ...[
                        const SizedBox(height: 4),
                        const Text(
                          'No resting stop found on the exchange for this position - it is '
                          'currently unprotected. The guard loop will re-attempt shortly.',
                          style: TextStyle(color: _red, fontSize: 11, fontWeight: FontWeight.w600),
                        ),
                      ],
                      if (nearSl) ...[
                        const SizedBox(height: 4),
                        Text(
                          'Price is only ${slDistancePct!.toStringAsFixed(2)}% from SL',
                          style: const TextStyle(color: _red, fontSize: 11, fontWeight: FontWeight.w600),
                        ),
                      ],
                      const SizedBox(height: 2),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('LTP: ${_fmt(ltp)}',
                              style: context.type.secondary.copyWith(fontSize: 12)),
                          if (invest != null)
                            Text('Invest ${invest.toStringAsFixed(0)}',
                                style: context.type.metadata.copyWith(fontSize: 12)),
                        ],
                      ),

                      // Inline mini candle chart - tap to still open the full-size
                      // sheet if the person wants to zoom in.
                      const SizedBox(height: 8),
                      GestureDetector(
                        onTap: () => showCandleChartSheet(
                          context,
                          symbol,
                          entry: entry,
                          sl: sl,
                          tpLevels: tpLevels,
                          isLong: isLong,
                          entryTsMs: entryTsMs,
                        ),
                        child: SizedBox(
                          height: 80,
                          width: double.infinity,
                          child: FutureBuilder<List<dynamic>>(
                            future: _candlesFuture,
                            builder: (context, snapshot) {
                              if (snapshot.connectionState != ConnectionState.done) {
                                return const Center(
                                  child: SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(strokeWidth: 2, color: _accent),
                                  ),
                                );
                              }
                              return CandleChart(
                                candles: snapshot.data ?? [],
                                entry: entry,
                                sl: sl,
                                tpLevels: tpLevels,
                                entryTsMs: entryTsMs,
                                showEma: true,
                                visibleCount: 40,
                                errorText: (snapshot.data?.isEmpty ?? true)
                                    ? Provider.of<AppProvider>(context, listen: false).lastCandleError
                                    : null,
                              );
                            },
                          ),
                        ),
                      ),

                      const SizedBox(height: 10),

                      // TP/Entry/SL ladder - tap a TP box to set/trail target
                      ...rows,

                      const SizedBox(height: 8),
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          ValueListenableBuilder<int>(
                              valueListenable: _DurationClock.tick,
                              builder: (_, __, ___) => Text('Open ${_duration(pos['opened_at_ts'] as num?)}',
                                  style: context.type.metadata.copyWith(fontSize: 12))),
                          Row(
                            children: [
                              // Move SL to Break-Even - only worth showing once
                              // there's an SL that isn't already at/through entry
                              // (backend's move_sl_to_breakeven() would just
                              // refuse as a no-op past that point anyway).
                              if (tradeId != null &&
                                  sl != null &&
                                  entry != null &&
                                  (isLong ? sl < entry : sl > entry))
                                Padding(
                                  padding: const EdgeInsets.only(right: 8),
                                  child: OutlinedButton(
                                    style: OutlinedButton.styleFrom(
                                      foregroundColor: _accent,
                                      side: const BorderSide(color: _accent),
                                      minimumSize: const Size(0, 32),
                                      padding: const EdgeInsets.symmetric(horizontal: 10),
                                    ),
                                    onPressed: () => _onMoveToBreakeven(context, tradeId),
                                    child: const Text('SL → BE', style: TextStyle(fontSize: 12)),
                                  ),
                                ),
                              if (tradeId != null)
                                ElevatedButton(
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: staleFeed ? AppColors.warning : _red,
                                    minimumSize: const Size(72, 32),
                                    padding: const EdgeInsets.symmetric(horizontal: 14),
                                  ),
                                  onPressed: () => _confirmClose(context, tradeId, symbol),
                                  child: Text(staleFeed ? 'Force Close' : 'Close',
                                      style: const TextStyle(color: Colors.white)),
                                ),
                            ],
                          ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ],
            ),
          ),
        ),
    );
  }

  Future<void> _onTapTp(BuildContext context, Object tradeId, int level, double tpPrice,
      double? ltp, bool isLong) async {
    AppHaptics.light();
    final provider = Provider.of<AppProvider>(context, listen: false);
    // If price has already passed this level, tapping trails the SL up to
    // it instead of setting a future target (matches the old app: tapping
    // an already-hit TP box locks in profit rather than doing nothing).
    final alreadyHit = ltp != null &&
        ((isLong && ltp >= tpPrice) || (!isLong && ltp <= tpPrice));
    if (alreadyHit) {
      final moved = await provider.trailSlToLevel(tradeId, level);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(moved
              ? 'SL trailed to TP$level'
              : 'TP$level already behind current SL - no change'),
          duration: const Duration(seconds: 2),
        ));
      }
    } else {
      await provider.setTargetTp(tradeId, level);
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Target set to TP$level'),
          duration: const Duration(seconds: 2),
        ));
      }
    }
  }

  Future<void> _onMoveToBreakeven(BuildContext context, Object tradeId) async {
    AppHaptics.light();
    final provider = Provider.of<AppProvider>(context, listen: false);
    final moved = await provider.moveSlToBreakeven(tradeId);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(moved ? 'SL moved to break-even' : 'SL already at/past entry - no change'),
        duration: const Duration(seconds: 2),
      ));
    }
  }

  Future<void> _confirmClose(BuildContext context, Object tradeId, String symbol) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: ctx.palette.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
          side: BorderSide(color: ctx.palette.border, width: 0.5),
        ),
        title: Text('Close position?', style: ctx.type.section),
        content: Text('Close $symbol now at market price?',
            style: ctx.type.secondary),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Close', style: TextStyle(color: _red))),
        ],
      ),
    );
    if (confirm == true && context.mounted) {
      final result = await Provider.of<AppProvider>(context, listen: false).closePosition(tradeId);
      if (!context.mounted) return;
      if (result['ok'] == true) AppHaptics.medium();
      if (result['ok'] != true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not close $symbol: ${result['error'] ?? 'unknown error'}'),
          duration: const Duration(seconds: 3),
          backgroundColor: _red,
        ));
      } else if (result['forced'] == true) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('$symbol closed (dead price feed - used last-known price)'),
          duration: const Duration(seconds: 3),
        ));
      }
    }
  }
}

/// Frosted slate glassmorphic surface - 0.5px hairline border, 10px
/// rounded corners, solid surface (no BackdropFilter - keeps long live
/// lists at 60 FPS). Self-contained here
/// (rather than editing the shared glass_card.dart) so this restyle stays
/// scoped to just this file.
class _GlassmorphicSurface extends StatelessWidget {
  final Widget child;
  final Color? highlightBorder;
  final Color? stripColor;
  const _GlassmorphicSurface({required this.child, this.highlightBorder, this.stripColor});

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        // Flat: no coloured glow (near-SL / unprotected only recolours the border).
        boxShadow: [
          context.palette.brightness == Brightness.light
              ? BoxShadow(color: const Color(0xFF101828).withOpacity(0.05), blurRadius: 16, offset: const Offset(0, 4))
              : BoxShadow(color: Colors.black.withOpacity(0.30), blurRadius: 10, offset: const Offset(0, 3)),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        child: Builder(
          builder: (_) => Container(
            decoration: BoxDecoration(
              color: context.palette.surfaceElevated,
              borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
              border: Border.all(
                color: highlightBorder?.withOpacity(0.55) ?? context.palette.glassBorder,
                width: 1,
              ),
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [context.palette.glassHighlight, Colors.transparent],
                stops: const [0.0, 0.5],
              ),
            ),
            child: stripColor == null
                ? child
                : Stack(
                    children: [
                      child,
                      Positioned(
                        left: 0,
                        top: 0,
                        bottom: 0,
                        width: 3,
                        child: ColoredBox(color: stripColor!),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}

/// Profit block (top right of the card): only the USDT profit, big. Owner 31 Oct 2026: no percentage here.
class _ProfitBlock extends StatelessWidget {
  final double pnl;
  final bool isProfit;
  const _ProfitBlock({required this.pnl, required this.isProfit});

  @override
  Widget build(BuildContext context) {
    final color = isProfit ? _green : _red;
    final sign = isProfit ? '+' : '';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.end,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text.rich(
          TextSpan(children: [
            TextSpan(text: '$sign${pnl.toStringAsFixed(2)}', style: AppTypography.primaryData.copyWith(color: color, fontWeight: FontWeight.w800, fontSize: 20)),
            TextSpan(text: ' USDT', style: TextStyle(color: context.palette.textMuted, fontWeight: FontWeight.w600, fontSize: 10)),
          ]),
          maxLines: 1,
        ),
      ],
    );
  }
}

/// Small pill badge used for BE / UNPROTECTED / NO LIVE FEED tags in the
/// card header. `filled` gives it a solid background (used for the more
/// urgent UNPROTECTED alert); otherwise it's a soft outline tag.
class _BadgePill extends StatelessWidget {
  final String text;
  final Color color;
  final bool filled;
  const _BadgePill({required this.text, required this.color, this.filled = false});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: filled ? color.withOpacity(0.9) : color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(6),
        border: filled ? null : Border.all(color: color.withOpacity(0.5), width: 0.75),
      ),
      child: Text(
        text,
        style: TextStyle(
          color: filled ? Colors.black : color,
          fontSize: 9,
          fontWeight: FontWeight.bold,
          letterSpacing: 0.3,
          fontFamily: AppTypography.fontFamily, fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    );
  }
}

class _LadderRow extends StatelessWidget {
  final String label;
  final double? price;
  final double? pct;
  final double? profit; // USDT at this level (invest x price-move% x leverage)
  final bool isEntry;
  final bool isSl;
  final bool isTarget; // final/selected target: solid blue + small flag
  final bool isBreakeven;
  final double fill; // 0..1 - how much of the row is filled (price progress to this TP)
  final VoidCallback? onTap;

  const _LadderRow({
    required this.label,
    required this.price,
    this.pct,
    this.profit,
    this.isEntry = false,
    this.isSl = false,
    this.isTarget = false,
    this.isBreakeven = false,
    this.fill = 0.0,
    this.onTap,
  });

  String _signed(double v, int d) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

  @override
  Widget build(BuildContext context) {
    final isLight = context.palette.brightness == Brightness.light;
    final color = isSl
        ? _red
        : isEntry
            ? context.palette.textSecondary
            : (pct != null && pct! >= 0 ? _green : _red);
    final onColor = isTarget ? Colors.black : context.palette.textPrimary;
    final radius = BorderRadius.circular(AppSpacing.radiusSmall);
    final baseColor = isTarget
        ? context.palette.accent
        : (isLight ? Colors.black.withOpacity(0.03) : Colors.white.withOpacity(0.03));
    // Progress fill: green on normal rows, a darker shade of the blue on the
    // target row (so the fill is still visible on top of solid blue).
    final fillColor = isTarget ? Colors.black.withOpacity(0.28) : _green.withOpacity(0.32);

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: InkWell(
        onTap: onTap,
        borderRadius: radius,
        child: Container(
          decoration: BoxDecoration(
            color: baseColor,
            borderRadius: radius,
            border: isTarget ? null : Border.all(color: context.palette.glassBorder, width: 0.5),
          ),
          child: ClipRRect(
            borderRadius: radius,
            child: Stack(
              children: [
                if (fill > 0)
                  Positioned.fill(
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: FractionallySizedBox(
                        widthFactor: fill.clamp(0.0, 1.0),
                        heightFactor: 1.0,
                        child: ColoredBox(color: fillColor),
                      ),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: AppSpacing.s),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 46,
                        child: Row(
                          children: [
                            Text(label,
                                style: AppTypography.secondaryData.copyWith(
                                    color: isSl ? _red : onColor, fontWeight: FontWeight.w700)),
                            if (isTarget) ...[
                              const SizedBox(width: 3),
                              const Icon(Icons.flag, size: 12, color: Colors.black),
                            ],
                          ],
                        ),
                      ),
                      if (isSl && isBreakeven) ...[
                        const SizedBox(width: 4),
                        _BadgePill(text: 'BE', color: AppColors.textSecondary),
                      ],
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.only(left: 6),
                          child: Text(price == null ? '--' : price!.toStringAsFixed(6),
                              style: AppTypography.secondaryData.copyWith(color: onColor)),
                        ),
                      ),
                      if (pct != null)
                        Text(_signed(pct!, 2) + '%',
                            style: AppTypography.metadata
                                .copyWith(color: isTarget ? Colors.black : color, fontSize: 12)),
                      SizedBox(
                        width: 64,
                        child: Text(profit == null ? '--' : _signed(profit!, 2),
                            textAlign: TextAlign.right,
                            style: AppTypography.secondaryData.copyWith(
                                color: isTarget ? Colors.black : color, fontWeight: FontWeight.w700)),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Thin bar under the compact line: green = how far price went from entry toward the target, red = how far toward the stop.
/// Read-only, it has no tap of its own (the card header keeps its tap, the TP ladder keeps its tap to set a target).
class _ProgressToTarget extends StatelessWidget {
  final double livePct, targetPct;
  final double? slPct;
  final String targetLabel;
  const _ProgressToTarget({required this.livePct, required this.targetPct, required this.slPct, required this.targetLabel});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final up = livePct >= 0;
    final double f = up
        ? (livePct / targetPct).clamp(0.0, 1.0)
        : ((slPct != null && slPct! < 0) ? (livePct / slPct!).clamp(0.0, 1.0) : 0.0);
    final c = up ? _green : _red;
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Row(children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(3),
            child: Stack(children: [
              Container(height: 5, color: p.border.withOpacity(0.5)),
              FractionallySizedBox(widthFactor: f, child: Container(height: 5, color: c)),
            ]),
          ),
        ),
        const SizedBox(width: 8),
        Text(up ? '${(f * 100).round()}% to $targetLabel' : '${(f * 100).round()}% to stop',
            style: context.type.metadata.copyWith(fontSize: 10.5, color: c, fontWeight: FontWeight.w700)),
      ]),
    );
  }
}
