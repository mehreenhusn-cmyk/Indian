import '../widgets/live_status_chip.dart';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../widgets/position_card.dart';
import '../widgets/position_row.dart';
import '../widgets/ai_advice_badge.dart';
import '../widgets/position_glance.dart';
import '../widgets/owl_empty_state.dart';
import '../models/view_state.dart';
import '../widgets/owl_state_gate.dart';
import '../widgets/owl_skeleton.dart';
import '../widgets/owl_status_pill.dart';
import '../widgets/owl_refresh.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

const _green = AppColors.profit;
const _red = AppColors.loss;

/// Part 17 (FILE 35): tap "N UP" / "N DOWN" in the top line to show only the winning / only the losing trades (tap again = all). 0 = all, 1 = UP, 2 = DOWN.
final ValueNotifier<int> positionsSide = ValueNotifier<int>(0);

List<dynamic> _bySide(List<dynamic> list, int side) {
  if (side == 0) return list;
  return list.where((x) {
    if (x is! Map) return false;
    final v = (x['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
    return side == 1 ? v >= 0 : v < 0;
  }).toList();
}

/// LIVE / PAPER badge for the close dialogs (Part 20). Shows what the backend preview says (`mode`); if there is no answer yet it
/// falls back to the Live Trading switch in Settings. Display only - it changes nothing.
Widget _modeBadge(String? mode, bool liveFallback) {
  final live = mode != null ? mode == 'live' : liveFallback;
  final color = live ? _red : _green;
  return Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    decoration: BoxDecoration(
      border: Border.all(color: color),
      borderRadius: BorderRadius.circular(6),
    ),
    child: Text(live ? 'LIVE' : 'PAPER',
        style: TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.w800)),
  );
}

/// The "what will close right now" line inside the PANIC dialog (Part 20). The dialog and its buttons show at once - the line fills
/// in when the backend answers and the panic close NEVER waits for it.
class _PanicPreviewLine extends StatelessWidget {
  const _PanicPreviewLine({required this.future, required this.liveFallback});
  final Future<Map<String, dynamic>?> future;
  final bool liveFallback;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<Map<String, dynamic>?>(
      future: future,
      builder: (ctx, snap) {
        final safe = snap.data;
        final String line;
        if (snap.connectionState != ConnectionState.done) {
          line = 'Checking what will close...';
        } else if (safe == null || safe['unreachable'] == true) {
          line = 'Preview not available - the panic close does not need it.';
        } else if (safe['ok'] != true) {
          line = 'Preview not available (${safe['error']}).';
        } else {
          final total = (safe['count'] as num?)?.toInt() ?? 0;
          final pnl = (safe['total_pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          final parts = safe['parts'];
          int n(String k) => (parts is Map && parts[k] is Map) ? ((parts[k]['count'] as num?)?.toInt() ?? 0) : 0;
          line = 'Right now: ${n('live')} live + ${n('paper')} paper = $total position${total == 1 ? '' : 's'}, '
              '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT.';
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            const SizedBox(height: 10),
            _modeBadge(safe == null ? null : safe['mode']?.toString(), liveFallback),
            const SizedBox(height: 6),
            Text(line, style: ctx.type.primary.copyWith(fontWeight: FontWeight.w700)),
          ],
        );
      },
    );
  }
}

/// Awaits a closeAllProfit()/closeAllLoss() call and always shows a
/// SnackBar - "N positions closed", "No positions in <profit/loss> to
/// close" (count 0 - not a bug, just nothing matched), or an error if the
/// request itself failed. Without this the buttons looked broken any
/// time there was nothing to close or the backend was unreachable.
Future<void> _closeAllAndNotify(
    BuildContext context, Future<int?> future, String label) async {
  final closed = await future;
  if (!context.mounted) return;
  final String msg;
  if (closed == null) {
    msg = 'Could not reach backend - nothing closed';
  } else if (closed == 0) {
    msg = 'No positions in $label to close';
  } else {
    AppHaptics.medium();
    msg = '$closed position${closed == 1 ? '' : 's'} closed';
  }
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(msg), duration: const Duration(seconds: 2)),
  );
}

/// Fetches a fresh preview (re-priced at live price, not the possibly-
/// stale numbers on screen) of what Close All Profit/Loss would actually
/// close, shows it in a confirm dialog, and only then fires the real
/// close call. Returns without closing anything if the user cancels, the
/// preview comes back empty, or the backend is unreachable.
///
/// CLOSE ALL EXECUTION FIX: `setBusy` is toggled ON for both network legs
/// (the preview fetch AND the actual close) and OFF the instant each leg
/// finishes - including every early-return path (empty preview, backend
/// unreachable, user cancels) - so the button's spinner can never get
/// stuck showing "in progress" after the request has actually settled,
/// and a double-tap while a request is in flight is simply ignored by the
/// caller (see _FloatingSummaryBar/_PanicButton below, which check busy
/// state before ever calling this).
Future<void> _confirmAndCloseAll(
  BuildContext context,
  AppProvider provider,
  String mode,
  Future<int?> Function() doClose, {
  required ValueChanged<bool> setBusy,
}) async {
  final label = mode == 'profit' ? 'profit' : 'loss';
  setBusy(true);
  final Map<String, dynamic>? preview;
  String? previewError;
  try {
    // Part 20: the SAFE preview first - same selection and same mode (LIVE / PAPER) as the real close. If the backend does not
    // have it (older backend / not mounted) null comes back and the old preview is used exactly as before.
    final safe = await provider.previewClose(mode);
    if (safe == null) {
      preview = await provider.previewCloseAll(mode);
    } else if (safe['ok'] == true) {
      preview = safe;
    } else {
      preview = null;
      previewError = safe['unreachable'] == true ? null : safe['error']?.toString();
    }
  } finally {
    setBusy(false);
  }
  if (!context.mounted) return;
  if (preview == null) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text(previewError != null
              ? 'Preview not available ($previewError) - nothing closed'
              : 'Could not reach backend - nothing closed'),
          duration: const Duration(seconds: 2)),
    );
    return;
  }
  final String? previewMode = preview['mode']?.toString();
  final count = preview['count'] as int? ?? 0;
  final totalPnl = (preview['total_pnl_usdt'] as num?)?.toDouble() ?? 0.0;
  if (count == 0) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
          content: Text('No positions in $label to close'),
          duration: const Duration(seconds: 2)),
    );
    return;
  }
  final positions = (preview['positions'] as List<dynamic>? ?? [])
      .cast<Map<String, dynamic>>();
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: ctx.palette.surfaceElevated,
      title: Row(
        children: [
          Expanded(child: Text('Close $count position${count == 1 ? '' : 's'}?')),
          _modeBadge(previewMode, provider.settings['live_trading_enabled'] == true),
        ],
      ),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ...positions.map((p) {
            final pnl = (p['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('${p['symbol']}', style: ctx.type.secondary),
                  Text('${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT',
                      style: TextStyle(color: pnl >= 0 ? _green : _red)),
                ],
              ),
            );
          }),
          Divider(color: ctx.palette.border, height: 20),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Total', style: ctx.type.primary.copyWith(fontWeight: FontWeight.w700)),
              Text('${totalPnl >= 0 ? '+' : ''}${totalPnl.toStringAsFixed(2)} USDT',
                  style: AppTypography.primaryData.copyWith(
                      color: totalPnl >= 0 ? _green : _red, fontWeight: FontWeight.bold)),
            ],
          ),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Close All')),
      ],
    ),
  );
  if (confirmed != true) return;
  if (!context.mounted) return;
  setBusy(true);
  try {
    // Re-verified again inside doClose() at the actual moment of closing
    // (fresh price, not the preview snapshot above) - see paper_trader.py.
    // On the LIVE/Binance side, doClose() ultimately routes through
    // ExecutionRouter -> binance_trader.close_position_market(), which now
    // treats a -2022 "ReduceOnly Order is rejected" (position already
    // closed - guard loop / native SL-TP / a race with another client got
    // there first) as a graceful, already-closed skip rather than a
    // reported failure or an unhandled exception - see that function's
    // CRASH-GUARD docstring. Any other backend error still surfaces
    // normally via _closeAllAndNotify below, it just can never hang this
    // spinner or crash the screen.
    await _closeAllAndNotify(context, doClose(), label);
  } finally {
    setBusy(false);
  }
}

/// PHASE 4 - EMERGENCY PANIC KILL SWITCH. Unlike the old "Flatten All"
/// (which called closeAll() -> /api/close_all, a PAPER-ONLY close that
/// silently left every real exchange position untouched whenever live
/// trading was on), this calls provider.panicFlatten() -> /api/flatten,
/// which closes REAL exchange positions too and then force-disables
/// live_trading_enabled so no further auto-entries can open on either
/// engine - see api_server.py's /api/flatten docstring for the exact
/// ordering/safety reasoning. Double-confirmed (dialog here, backend
/// re-checks live price on every close too) so a stray tap can't
/// flatten the whole book and kill live trading by accident. `setBusy`
/// covers only the actual flatten call, same "spinner reflects real
/// network state, never gets stuck" rule as _confirmAndCloseAll above.
Future<void> _confirmPanicClose(
  BuildContext context,
  AppProvider provider, {
  required ValueChanged<bool> setBusy,
}) async {
  final count = provider.positions.length;
  final isLive = provider.settings['live_trading_enabled'] == true;
  // Part 20: asked while the dialog is already on screen - NO await here, the panic close never waits for the preview.
  final Future<Map<String, dynamic>?> previewFuture = provider.previewClose('flatten');
  final confirmed = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: ctx.palette.surfaceElevated,
      title: Text('PANIC - Flatten everything?', style: ctx.type.section),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            (isLive
                    ? 'This market-closes every open position - LIVE and paper - right now, '
                        'regardless of profit or loss, '
                    : 'This closes all $count open position${count == 1 ? '' : 's'} at market price right now, '
                        'regardless of profit or loss, ') +
                'and turns Live Trading OFF so no new trades can open until you switch it back on.',
            style: ctx.type.secondary,
          ),
          _PanicPreviewLine(future: previewFuture, liveFallback: isLive),
        ],
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        TextButton(
          onPressed: () => Navigator.pop(ctx, true),
          child: const Text('PANIC - FLATTEN ALL', style: TextStyle(color: _red, fontWeight: FontWeight.bold)),
        ),
      ],
    ),
  );
  if (confirmed != true) return;
  if (!context.mounted) return;
  AppHaptics.heavy();
  setBusy(true);
  final Map<String, dynamic>? result;
  try {
    result = await provider.panicFlatten();
  } finally {
    setBusy(false);
  }
  if (!context.mounted) return;
  final String msg;
  Color? bg;
  if (result == null) {
    msg = 'Could not reach backend - nothing flattened';
    bg = _red;
  } else {
    final liveClosed = (result['live_closed_count'] as num?)?.toInt() ?? 0;
    final liveFailed = (result['live_failed_count'] as num?)?.toInt() ?? 0;
    final paperClosed = (result['paper_closed_count'] as num?)?.toInt() ?? 0;
    final paperFailed = (result['paper_failed_count'] as num?)?.toInt() ?? 0;
    final totalClosed = liveClosed + paperClosed;
    final totalFailed = liveFailed + paperFailed;
    if (totalFailed > 0) {
      msg = 'Flattened $totalClosed, $totalFailed could not be closed. Live trading is now OFF.';
      bg = _red;
    } else if (totalClosed == 0) {
      msg = 'No open positions to flatten. Live trading is now OFF.';
    } else {
      msg = 'Flattened $totalClosed position${totalClosed == 1 ? '' : 's'}. Live trading is now OFF.';
    }
  }
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(msg), duration: const Duration(seconds: 3), backgroundColor: bg),
  );
}

/// Round 14: this is the OLD Positions screen, moved here word for word. Only two things changed: the class is now PositionsLiveView (the "Live" part of the
/// Positions tab, see positions_screen.dart) and its SafeArea no longer pads the top. Close, close-all, panic, swipe-to-close and the cards are untouched.
class PositionsLiveView extends StatelessWidget {
  const PositionsLiveView({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        top: false, // Round 14: the Positions tab above (positions_screen.dart) already clears the top bar
        child: Padding(
          // Compact: less top padding + smaller header gap so more
          // position cards fit on screen (was all(l) + gap l).
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.xs, AppSpacing.l, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '💼 Positions',
                    style: context.type.hero.copyWith(fontSize: 18),
                  ),
                  // PHASE 4: always visible, even with zero positions - the
                  // panic switch's "turn live_trading off right now" half is
                  // useful on its own, independent of whether anything is
                  // currently open.
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const LiveStatusChip(),
                      const SizedBox(width: 10),
                      const _PanicButton(),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              const _TopSummary(),
              const PositionsTopBar(),
              const PositionsSearchBar(),
              // Part 17: ONE place for Close All Profit / Close All Loss, in the layout right above the list (it used to float over the list and hide cards).
              const _FloatingSummaryBar(),
              Expanded(
                child: OWLRefresh(
                      onRefresh: () => context.read<AppProvider>().fetchStatus(),
                      // The LIST only rebuilds when the set/order of positions
                      // changes (open/close). Price/P&L changes are handled by
                      // each PositionCard itself, so a tick no longer rebuilds
                      // the whole list.
                      child: ValueListenableBuilder<String>(
                      valueListenable: positionsSearch,
                      builder: (context, query, _) => ValueListenableBuilder<int>(
                      valueListenable: positionsSortMode,
                      builder: (context, sortMode, _) => ValueListenableBuilder<int>(
                      valueListenable: positionsSide,
                      builder: (context, side, _) => Selector<AppProvider, int>(
                      selector: (_, p) => Object.hash(
                        p.positions.isEmpty,
                        p.status.isEmpty,
                        p.error == null,
                        p.liveState == 'offline',
                        sortMode,
                        side,
                        query,
                        Object.hashAll(_bySide(filterPositions(sortedPositions(p.positions, sortMode), query), side).map((x) => x is Map ? x['id'] : null)),
                      ),
                      builder: (context, _, child) {
                        final provider = context.read<AppProvider>();
                        final positions = _bySide(filterPositions(sortedPositions(provider.positions, sortMode), query), side);
                        if (positions.isEmpty &&
                            provider.status.isEmpty &&
                            provider.error == null) {
                          // First load only - shimmer cards instead of a
                          // misleading "No open positions" flash.
                          return ListView(
                            physics: const NeverScrollableScrollPhysics(),
                            padding: const EdgeInsets.all(AppSpacing.l),
                            children: List.generate(
                              3,
                              (_) => const Padding(
                                padding: EdgeInsets.only(bottom: AppSpacing.m),
                                child: OWLSkeleton.card(height: 200),
                              ),
                            ),
                          );
                        }
                        if (positions.isEmpty && query.trim().isNotEmpty && provider.positions.isNotEmpty) {
                          return OWLPullEmpty(
                            child: OWLEmptyState(
                              icon: Icons.search_off_rounded,
                              title: 'No position matches "${query.trim()}"',
                              subtitle: 'Search by coin, trade no (#id) or signal no.',
                            ),
                          );
                        }
                        if (positions.isEmpty && side != 0 && provider.positions.isNotEmpty) {
                          return OWLPullEmpty(
                            child: OWLEmptyState(
                              icon: Icons.filter_alt_off_outlined,
                              title: side == 1 ? 'No trade is UP right now' : 'No trade is DOWN right now',
                              subtitle: 'Tap the UP / DOWN pill at the top again to see all trades.',
                            ),
                          );
                        }
                        if (positions.isEmpty) {
                          // Part 28: dead backend = "Backend offline", never a fake empty list.
                          return OwlStateGate(
                            state: decideViewState(hasData: false, offline: provider.liveState == 'offline'),
                            what: 'open positions',
                            onRetry: () => provider.fetchStatus(),
                            empty: const OWLEmptyState(
                              icon: Icons.account_balance_wallet_outlined,
                              title: 'No open positions',
                              subtitle: 'New trades appear here the moment they open.',
                            ),
                          );
                        }
                        return ListView.builder(
                          physics: owlPullPhysics,
                          // Part 17: the Close All bar is no longer an overlay (it sits above the list), so no big empty space is reserved here.
                          padding: const EdgeInsets.only(bottom: 8),
                          itemCount: positions.length,
                          itemBuilder: (context, index) {
                            final pos = positions[index] as Map<String, dynamic>;
                            // PART 1 HARDENING FIX: id is an int trade_id in
                            // PAPER mode, or the exchange symbol (String) in
                            // LIVE mode - see position_card.dart's tradeId
                            // comment. No cast here, just check for null.
                            final tradeId = pos['id'];
                            final symbol = pos['symbol'] as String? ?? '--';
                            // Round 15: one compact row per trade; tap opens the full PositionCard (+ AI badge) right under it.
                            final card = PositionRow(pos: pos);
                            if (tradeId == null) return card;
                            // Swipe-left-to-close - high-frequency trader
                            // shortcut so closing doesn't require expanding
                            // the card first. Reuses the same confirm dialog
                            // style as the Close button so a swipe never
                            // closes anything silently.
                            return Dismissible(
                              key: ValueKey(tradeId),
                              direction: DismissDirection.endToStart,
                              background: Container(
                                alignment: Alignment.centerRight,
                                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xl),
                                margin: const EdgeInsets.only(bottom: AppSpacing.m),
                                decoration: BoxDecoration(
                                  color: _red.withOpacity(0.25),
                                  borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                                ),
                                child: const Icon(Icons.close, color: _red),
                              ),
                              confirmDismiss: (_) async {
                                final confirm = await showDialog<bool>(
                                  context: context,
                                  builder: (ctx) => AlertDialog(
                                    backgroundColor: ctx.palette.surfaceElevated,
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
                                if (confirm == true) {
                                  // CRASH-GUARD: if this position already
                                  // closed out from under the swipe (guard
                                  // loop, native SL/TP, a race with another
                                  // client), the backend's -2022 handling /
                                  // _find_live_position None-check both
                                  // resolve to a clean {"ok": false/true, ...}
                                  // dict here - never an unhandled exception -
                                  // so this always has a real result map to
                                  // read below.
                                  final result = await provider.closePosition(tradeId);
                                  if (!context.mounted) return false;
                                  if (result['ok'] != true) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('Could not close $symbol: ${result['error'] ?? 'unknown error'}'),
                                        duration: const Duration(seconds: 3),
                                        backgroundColor: _red,
                                      ),
                                    );
                                  } else if (result['forced'] == true) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('$symbol closed (dead price feed - used last-known price)'),
                                        duration: const Duration(seconds: 3),
                                      ),
                                    );
                                  } else if (result['already_closed'] == true) {
                                    ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(
                                        content: Text('$symbol was already closed on the exchange'),
                                        duration: const Duration(seconds: 2),
                                      ),
                                    );
                                  }
                                }
                                // Always false - the position's own removal
                                // from provider.positions (optimistic in
                                // closePosition) is what actually rebuilds
                                // this list; letting Dismissible also remove
                                // itself on a false/cancelled dismiss would
                                // leave a phantom gap.
                                return false;
                              },
                              child: card,
                            );
                          },
                        );
                      },
                    ),
                    ),
                    ),
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

/// UI3a: one slim line at the very top = the answer in 2 seconds. Big open P&L (green / red), then how many
/// trades are up and how many are down. Same numbers as the floating bar below, just first. Shows nothing
/// when no position is open, and only rebuilds when the shown numbers change.
class _TopSummary extends StatelessWidget {
  const _TopSummary();

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, int>(
      selector: (_, p) {
        double pnl = 0.0;
        int up = 0;
        for (final x in p.positions) {
          if (x is! Map) continue;
          final v = (x['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          pnl += v;
          if (v >= 0) up++;
        }
        return Object.hash(p.positions.length, (pnl * 100).round(), up);
      },
      builder: (context, _, child) {
        final positions = context.read<AppProvider>().positions;
        if (positions.isEmpty) {
          // nothing open: forget the UP / DOWN choice, so the next trades are not hidden by an old filter
          if (positionsSide.value != 0) WidgetsBinding.instance.addPostFrameCallback((_) => positionsSide.value = 0);
          return const SizedBox.shrink();
        }
        double pnl = 0.0;
        int up = 0, down = 0;
        for (final x in positions) {
          if (x is! Map) continue;
          final v = (x['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          pnl += v;
          if (v >= 0) {
            up++;
          } else {
            down++;
          }
        }
        final c = pnl >= 0 ? _green : _red;
        // Part 17: the two pills are buttons: tap = only UP (or only DOWN) trades, tap again = all.
        Widget side(String text, Color col, int me) => ValueListenableBuilder<int>(
              valueListenable: positionsSide,
              builder: (context, cur, _) => GestureDetector(
                behavior: HitTestBehavior.opaque,
                onTap: () => positionsSide.value = cur == me ? 0 : me,
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                    border: Border.all(color: cur == me ? col : Colors.transparent, width: 1.4),
                  ),
                  child: OWLStatusPill(text: text, color: col, showDot: false),
                ),
              ),
            );
        return Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.xs),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Text('${fmtSigned(pnl)} USDT',
                  style: context.type.hero.copyWith(fontSize: 28, fontWeight: FontWeight.w800, color: c)),
              const SizedBox(width: 10),
              side('$up UP', _green, 1),
              const SizedBox(width: 6),
              side('$down DOWN', _red, 2),
            ],
          ),
        );
      },
    );
  }
}

/// v0 "summary-bar" component, converted natively: a single floating
/// glassmorphic pill-card - frosted slate #0D121D, 0.5px translucent
/// border, 12px corners - showing the LIVE aggregated Unrealized P&L
/// ($ and %) and Total Margin Used across every currently open position,
/// with a dynamic green/crimson glow that flips with the book's sign, plus
/// the two bulk-action pill buttons underneath. Recomputed on every
/// provider rebuild (i.e. every WS/status tick) so it can never visibly lag
/// behind the cards scrolling beneath it.
class _FloatingSummaryBar extends StatefulWidget {
  const _FloatingSummaryBar();

  @override
  State<_FloatingSummaryBar> createState() => _FloatingSummaryBarState();
}

class _FloatingSummaryBarState extends State<_FloatingSummaryBar> {
  // Which bulk action is currently in flight - null when idle. Only ever
  // one at a time; the previous _BottomActionBar shared a single busy bool
  // across both buttons, this tracks it per-button instead so only the
  // tapped pill cross-fades into its spinner while the other just dims.
  String? _busyMode; // 'profit' | 'loss' | null

  void _setBusy(String? mode) {
    if (mounted) setState(() => _busyMode = mode);
  }

  @override
  Widget build(BuildContext context) {
    // Rebuilds only when the book's total P&L / margin / count actually
    // moved (rounded to the 0.01 shown on screen), not on every tick.
    return Selector<AppProvider, int>(
      selector: (_, p) {
        double pnl = 0.0, margin = 0.0;
        for (final x in p.positions) {
          if (x is! Map) continue;
          pnl += (x['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          margin += (x['invest_usdt'] as num?)?.toDouble() ?? 0.0;
        }
        return Object.hash(p.positions.length, (pnl * 100).round(), (margin * 100).round(), (p.closedPnl * 100).round());
      },
      builder: (context, _, child) {
        final provider = context.read<AppProvider>();
        final positions = provider.positions;
        if (positions.isEmpty) return const SizedBox.shrink();

        // Owner 31 Oct 2026: the profit goes INSIDE "Close All Profit" and the loss INSIDE "Close All Loss"; no percent, no repeated count.
        double profitSum = 0.0, lossSum = 0.0;
        for (final p in positions) {
          if (p is! Map) continue;
          final v = (p['pnl_usdt'] as num?)?.toDouble() ?? 0.0;
          if (v >= 0) {
            profitSum += v;
          } else {
            lossSum += v;
          }
        }
        String amt(double v) => v == 0 ? '0.00 USDT' : '${fmtSigned(v)} USDT';

        return Padding(
          padding: const EdgeInsets.only(bottom: 4),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
            child: Builder(
              builder: (_) => AnimatedContainer(
                duration: AppMotion.slow,
                curve: AppMotion.standard,
                // Trimmed from (16,14,16,14) - user feedback: this floating
                // bar + the two buttons below it were eating too much
                // vertical space over the position list.
                padding: const EdgeInsets.fromLTRB(12, 6, 12, 6),
                decoration: BoxDecoration(
                  color: context.palette.surfaceElevated,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                  border: Border.all(color: context.palette.border, width: 1),
                  boxShadow: context.palette.brightness == Brightness.light
                      ? [BoxShadow(color: const Color(0xFF101828).withOpacity(0.05), blurRadius: 16, offset: const Offset(0, 4))]
                      : null,
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: _NeonPillButton(
                            label: 'Close All Profit',
                            amount: amt(profitSum),
                            color: _green,
                            busy: _busyMode == 'profit',
                            disabled: _busyMode != null && _busyMode != 'profit',
                            onTap: () => _confirmAndCloseAll(
                              context,
                              provider,
                              'profit',
                              provider.closeAllProfit,
                              setBusy: (v) => _setBusy(v ? 'profit' : null),
                            ),
                          ),
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: _NeonPillButton(
                            label: 'Close All Loss',
                            amount: amt(lossSum),
                            color: _red,
                            busy: _busyMode == 'loss',
                            disabled: _busyMode != null && _busyMode != 'loss',
                            onTap: () => _confirmAndCloseAll(
                              context,
                              provider,
                              'loss',
                              provider.closeAllLoss,
                              setBusy: (v) => _setBusy(v ? 'loss' : null),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Neon outline pill button with native micro-animations:
/// - AnimatedScale: 0.96x tactile shrink on tap-down, snaps back on
///   release/cancel (110ms, easeOut - fast enough to read as instant
///   tactile feedback, not a lag).
/// - AnimatedCrossFade: label text cross-fades into a small neon
///   CircularProgressIndicator while `busy` is true, instead of an
///   abrupt widget swap - both children are laid out via sizeCurve so the
///   pill never jumps size mid-transition.
/// - AnimatedOpacity: dims to 35% (and stops accepting taps) while the
///   OTHER pill in the row is mid-execution, so a double bulk-action can
///   never fire concurrently.
class _NeonPillButton extends StatefulWidget {
  final String label;
  final String? amount;
  final Color color;
  final bool busy;
  final bool disabled;
  final VoidCallback onTap;

  const _NeonPillButton({
    required this.label,
    this.amount,
    required this.color,
    required this.busy,
    required this.disabled,
    required this.onTap,
  });

  @override
  State<_NeonPillButton> createState() => _NeonPillButtonState();
}

class _NeonPillButtonState extends State<_NeonPillButton> {
  bool _pressed = false;

  void _setPressed(bool value) {
    if (mounted) setState(() => _pressed = value);
  }

  @override
  Widget build(BuildContext context) {
    final isActive = !widget.disabled && !widget.busy;

    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTapDown: isActive ? (_) => _setPressed(true) : null,
      onTapUp: isActive ? (_) => _setPressed(false) : null,
      onTapCancel: isActive ? () => _setPressed(false) : null,
      onTap: isActive
          ? () {
              AppHaptics.light();
              widget.onTap();
            }
          : null,
      child: AnimatedScale(
        scale: _pressed ? 0.96 : 1.0,
        duration: AppMotion.fast,
        curve: AppMotion.standard,
        child: AnimatedOpacity(
          opacity: widget.disabled ? 0.35 : 1.0,
          duration: AppMotion.base,
          child: Container(
            // Shrunk from 44 - Close All Profit/Loss pair was taking up
            // too much vertical space above the position list.
            height: widget.amount == null ? 34 : 50,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: widget.color.withOpacity(widget.busy ? 0.14 : 0.08),
              borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
              border: Border.all(
                color: widget.color.withOpacity(0.35),
                width: 1,
              ),
            ),
            child: AnimatedCrossFade(
              duration: AppMotion.base,
              firstCurve: AppMotion.standard,
              secondCurve: AppMotion.standard,
              sizeCurve: AppMotion.standard,
              crossFadeState: widget.busy ? CrossFadeState.showSecond : CrossFadeState.showFirst,
              firstChild: widget.amount == null
                  ? Text(
                      widget.label,
                      style: AppTypography.primaryData.copyWith(
                        color: widget.color,
                        fontWeight: FontWeight.w700,
                        fontSize: 12,
                        letterSpacing: 0.2,
                      ),
                    )
                  : Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(widget.label, style: AppTypography.primaryData.copyWith(color: widget.color, fontWeight: FontWeight.w600, fontSize: 11)),
                        const SizedBox(height: 1),
                        Text(widget.amount!, style: AppTypography.primaryData.copyWith(color: widget.color, fontWeight: FontWeight.w800, fontSize: 16)),
                      ],
                    ),
              secondChild: SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2, color: widget.color),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// PANIC button with its own busy flag - separate from _FloatingSummaryBar's
/// because it's always visible (even with zero positions) up in the header
/// row, not part of the floating bottom overlay.
class _PanicButton extends StatefulWidget {
  const _PanicButton();

  @override
  State<_PanicButton> createState() => _PanicButtonState();
}

class _PanicButtonState extends State<_PanicButton> {
  bool _busy = false;

  void _setBusy(bool value) {
    if (mounted) setState(() => _busy = value);
  }

  @override
  Widget build(BuildContext context) {
    // PANIC only needs the provider for its tap callback - nothing it shows
    // depends on price ticks, so it must NOT rebuild on them.
    return Selector<AppProvider, int>(
      selector: (_, __) => 0,
      builder: (context, _, child) {
        final provider = context.read<AppProvider>();
        return TextButton.icon(
          style: TextButton.styleFrom(
            foregroundColor: _red,
            // Compact: drop the 48dp min tap height that made the header row tall.
            minimumSize: const Size(0, 30),
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 0),
            tapTargetSize: MaterialTapTargetSize.shrinkWrap,
            visualDensity: VisualDensity.compact,
          ),
          onPressed: _busy ? null : () => _confirmPanicClose(context, provider, setBusy: _setBusy),
          icon: _busy
              ? const SizedBox(
                  width: 14,
                  height: 14,
                  child: CircularProgressIndicator(strokeWidth: 2, color: _red),
                )
              : const Icon(Icons.warning_amber_rounded, size: 18),
          label: const Text('PANIC'),
        );
      },
    );
  }
}
