import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_motion.dart';
import '../services/market_mode.dart';

/// OBSIDIAN TERMINAL TOP BAR (formerly "LIVE TICKER BAR").
///
/// A thin, persistent glass strip shown on every screen (wired once in
/// main.dart, directly under the top connection banner - see that file's
/// comment for why "below the AppBar" collapses to that spot: none of the
/// six screens actually use a Flutter `AppBar` widget, they each just draw
/// their own header Text inside the body).
///
/// Shows, left to right:
///   - Ticker/mode pill: exchange + rotating universe + leverage + margin
///     mode. This bot trades a rotating Top-10 gainers/losers universe
///     (scanner bot), not one fixed pair, so this pill reads e.g.
///     "BINANCE · TOP10 · 3x CROSS" instead of a literal "BTC/USDT" -
///     same spot/role as a single-pair terminal's "BTC/USDT Perp 20x
///     Cross" pill, adapted to this app's actual multi-symbol engine so
///     it never shows a pair that isn't what's really being traded.
///   - Net vs Engine latency split micro-badge, reading the existing
///     status['feed_latency_net_ms'] / status['feed_latency_engine_ms']
///     fields (AppProvider.feedLatencyNetMs / feedLatencyEngineMs) - falls
///     back to the WS round-trip ping (wsLatencyMs) as "Net" if the feed
///     split isn't available yet, so the badge is never blank.
///   - a LIVE / PAPER mode badge (settings['live_trading_enabled'])
///   - the active Strategy Timeframe pill (settings['timeframe'])
///   - a P&L chip = TODAY closed P&L (same number as the Dashboard ring), green/red by sign
///   - a Hold-to-Confirm PANIC button - 1.5s circular progress fill,
///     calls the existing AppProvider.panicFlatten() (POST /api/flatten)
///     only once the ring completes, so an accidental tap/slip never
///     fires it.
///
/// Purely a read of AppProvider's existing polled state plus one write
/// action (panicFlatten) - this widget triggers no network calls of its
/// own beyond that single explicit, user-confirmed action.
class LiveTickerBar extends StatefulWidget {
  const LiveTickerBar({super.key});

  @override
  State<LiveTickerBar> createState() => _LiveTickerBarState();
}

class _LiveTickerBarState extends State<LiveTickerBar> with TickerProviderStateMixin {
  late final AnimationController _pulseController;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1100),
    )..repeat(reverse: true);
  }

  @override
  void dispose() {
    _pulseController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<AppProvider>(
      builder: (context, provider, _) {
        final connected = provider.wsConnected;
        final wsLatency = provider.wsLatencyMs;
        final netMs = provider.feedLatencyNetMs?.round() ?? wsLatency;
        final engineMs = provider.feedLatencyEngineMs?.round();

        final isLive = provider.settings['live_trading_enabled'] == true;
        final timeframe = (provider.settings['timeframe'] as String?) ?? '5m';
        final exchange = ((provider.settings['active_exchange'] as String?) ?? 'binance').toUpperCase();
        final leverage = isLive
            ? (provider.settings['live_leverage'] as num?)?.toInt() ?? 3
            : (provider.settings['leverage'] as num?)?.toInt() ?? 1;

        // Same number as the Dashboard ring: TODAY = closed trades only (stable). LIVE mode: open exchange P&L.
        final pnl = provider.statsMode == 'live' ? provider.openPnl : provider.closedPnl;
        final pnlColor = pnl > 0 ? context.palette.profit : (pnl < 0 ? context.palette.loss : context.palette.textMuted);
        final statusColor = connected ? context.palette.profit : context.palette.loss;

        return LayoutBuilder(builder: (context, box) {
        // Phones are ~360-412dp wide: the full "BINANCE · TOP10 · 10x CROSS"
        // pill + "Net | Engine" badge + PAPER + timeframe + P&L + PANIC
        // cannot all fit, so on narrow screens the LEFT side shortens and
        // shrinks; the right side (mode, timeframe, P&L, PANIC) never moves.
        final compact = box.maxWidth < 560;
        return Container(
          height: 36,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          decoration: BoxDecoration(
            color: context.palette.surface.withOpacity(0.92),
            border: Border(bottom: BorderSide(color: context.palette.glassBorder, width: 0.5)),
          ),
          child: Row(
            children: [
              // ---- Market switch: one tap, same spot in both markets (no swipe needed) ----
              const MarketModeSwitch(),
              const SizedBox(width: 6),
              // ---- Left group: shrinks first when space runs out ----
              Expanded(
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: FittedBox(
                    fit: BoxFit.scaleDown,
                    alignment: Alignment.centerLeft,
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        // The market switch needs room on a phone: below ~420dp the exchange pill is
                        // dropped (it is still shown in Settings); the latency badge stays.
                        if (box.maxWidth >= 420) ...[
                          _tickerPill(exchange: exchange, leverage: leverage, compact: compact),
                          const SizedBox(width: 8),
                        ],
                        _latencyBadge(
                          connected: connected,
                          netMs: netMs,
                          engineMs: compact ? null : engineMs,
                          statusColor: statusColor,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 6),

              // ---- LIVE/PAPER + timeframe pills ----
              // Issue #5: tap-to-toggle - opens a confirm dialog rather than
              // flipping live_trading_enabled on a single accidental tap,
              // since going PAPER->LIVE has real money consequences.
              GestureDetector(
                onTap: () => _confirmToggleLiveMode(context, provider, isLive),
                child: _pill(
                  text: isLive ? 'LIVE' : 'PAPER',
                  color: isLive ? context.palette.loss : context.palette.accent,
                  filled: true,
                ),
              ),
              const SizedBox(width: 4),
              _pill(text: timeframe, color: context.palette.textMuted, filled: false),
              const SizedBox(width: 6),

              // ---- 24h P&L ----
              Column(
                mainAxisSize: MainAxisSize.min,
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(
                    provider.statsMode == 'live' ? 'MAIN OPEN P&L' : 'MAIN TODAY P&L',
                    style: TextStyle(fontSize: 8, height: 1.1, letterSpacing: 0.4, color: context.palette.textMuted),
                  ),
                  Text(
                    '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)}',
                    style: AppTypography.secondaryData.copyWith(color: pnlColor, fontSize: 12.5, height: 1.15, fontWeight: FontWeight.w800),
                  ),
                ],
              ),
              const SizedBox(width: 8),

              // ---- Hold-to-confirm PANIC button ----
              _PanicButton(onConfirmed: () => provider.panicFlatten()),
            ],
          ),
        );
        });
      },
    );
  }

  Widget _tickerPill({required String exchange, required int leverage, bool compact = false}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: context.palette.glassFill,
        borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 1),
        border: Border.all(color: context.palette.glassBorder, width: 0.5),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          AnimatedBuilder(
            animation: _pulseController,
            builder: (context, child) {
              final t = _pulseController.value;
              return Container(
                width: 5,
                height: 5,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: context.palette.accent,
                  boxShadow: [
                    BoxShadow(
                      color: context.palette.accent.withOpacity(0.3 + t * 0.4),
                      blurRadius: 3 + t * 4,
                      spreadRadius: 0.5,
                    ),
                  ],
                ),
              );
            },
          ),
          const SizedBox(width: 6),
          Text(
            compact ? '$exchange · ${leverage}x' : '$exchange · TOP10 · ${leverage}x CROSS',
            style: AppTypography.metadata.copyWith(color: context.palette.textPrimary, fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.3),
          ),
        ],
      ),
    );
  }

  Widget _latencyBadge({
    required bool connected,
    required int? netMs,
    required int? engineMs,
    required Color statusColor,
  }) {
    if (!connected) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 6,
            height: 6,
            decoration: BoxDecoration(shape: BoxShape.circle, color: context.palette.loss),
          ),
          const SizedBox(width: 5),
          Text(
            'OFFLINE',
            style: AppTypography.metadata.copyWith(color: context.palette.loss, fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.3),
          ),
        ],
      );
    }

    final netText = netMs != null ? '${netMs}ms' : '--';

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(shape: BoxShape.circle, color: statusColor),
        ),
        const SizedBox(width: 5),
        // Only the ms value, large and bold, so it reads at a glance on a phone.
        Text(
          netText,
          style: AppTypography.metadata.copyWith(
            color: context.palette.textPrimary,
            fontSize: 13,
            fontWeight: FontWeight.w800,
          ),
        ),
      ],
    );
  }

  Widget _pill({required String text, required Color color, required bool filled}) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: filled ? color.withOpacity(0.9) : color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(5),
        border: filled ? null : Border.all(color: color.withOpacity(0.5)),
        boxShadow: filled
            ? [BoxShadow(color: color.withOpacity(0.18), blurRadius: 4)]
            : null,
      ),
      child: Text(
        text,
        style: TextStyle(
          color: filled ? Colors.black : color,
          fontSize: 10,
          fontWeight: FontWeight.bold,
          letterSpacing: 0.3,
          fontFamily: AppTypography.fontFamily, fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    );
  }

  // Issue #5: PAPER/LIVE badge tap-to-toggle. Going PAPER -> LIVE risks real
  // money the moment it's confirmed, so this always confirms first via a
  // dialog rather than flipping the switch on a single tap - same
  // seriousness as the PANIC button next to it, just for entering live
  // mode instead of flattening it.
  Future<void> _confirmToggleLiveMode(BuildContext context, AppProvider provider, bool currentlyLive) async {
    final goingLive = !currentlyLive;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(goingLive ? 'Switch to LIVE trading?' : 'Switch to PAPER trading?'),
        content: Text(goingLive
            ? 'The bot will start placing REAL orders on Binance with real funds. '
                'Make sure your API keys and risk settings are correct before continuing.'
            : 'The bot will stop placing real orders and go back to simulated (PAPER) trades only.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text(
              goingLive ? 'Go LIVE' : 'Switch to PAPER',
              style: AppTypography.primaryData.copyWith(color: goingLive ? context.palette.loss : context.palette.accent, fontWeight: FontWeight.w700),
            ),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final ok = await provider.setLiveTradingEnabledImmediate(goingLive);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not switch to ${goingLive ? 'LIVE' : 'PAPER'} - check your connection and try again')),
      );
    }
  }
}

/// Hold-to-Confirm PANIC button - 1.5s circular progress ring fills as the
/// user holds their thumb down; releasing early cancels and the ring
/// snaps back to empty. Only firing [onConfirmed] once the ring completes
/// prevents an accidental tap from flattening every live position.
class _PanicButton extends StatefulWidget {
  final Future<void> Function() onConfirmed;
  const _PanicButton({required this.onConfirmed});

  @override
  State<_PanicButton> createState() => _PanicButtonState();
}

class _PanicButtonState extends State<_PanicButton> with SingleTickerProviderStateMixin {
  late final AnimationController _holdController;
  bool _armed = false; // true briefly while showing the "confirmed" flash
  bool _busy = false;

  static const _holdDuration = Duration(milliseconds: 1500);

  @override
  void initState() {
    super.initState();
    _holdController = AnimationController(vsync: this, duration: _holdDuration);
    _holdController.addStatusListener(_onStatus);
  }

  void _onStatus(AnimationStatus status) {
    if (status == AnimationStatus.completed && !_busy) {
      _fire();
    }
  }

  Future<void> _fire() async {
    // Part 14: the hold alone is not enough. After the 1.5 s hold the power button asks ONE more time in plain words.
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Close ALL positions?'),
        content: const Text('The power button closes every open position now. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text('Close all', style: TextStyle(color: context.palette.loss, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
    );
    if (!mounted) return;
    if (ok != true) {
      _holdController.reset();
      return;
    }
    setState(() {
      _busy = true;
      _armed = true;
    });
    HapticFeedback.heavyImpact();
    await widget.onConfirmed();
    if (!mounted) return;
    setState(() {
      _busy = false;
      _armed = false;
    });
    _holdController.reset();
  }

  @override
  void dispose() {
    _holdController.removeStatusListener(_onStatus);
    _holdController.dispose();
    super.dispose();
  }

  void _startHold() {
    if (_busy) return;
    HapticFeedback.mediumImpact();
    _holdController.forward();
  }

  void _cancelHold() {
    if (_busy) return;
    if (_holdController.status != AnimationStatus.completed) {
      _holdController.reverse();
    }
  }

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: (_) => _startHold(),
      onTapUp: (_) => _cancelHold(),
      onTapCancel: _cancelHold,
      child: AnimatedBuilder(
        animation: _holdController,
        builder: (context, child) {
          final progress = _holdController.value;
          final glowT = _armed ? 1.0 : progress;
          return Container(
            width: 30,
            height: 30,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: AppColors.loss.withOpacity(0.10 + glowT * 0.20),
              boxShadow: progress > 0
                  ? [
                      BoxShadow(
                        color: AppColors.loss.withOpacity(0.25 + glowT * 0.35),
                        blurRadius: 4 + glowT * 8,
                        spreadRadius: 0.5,
                      ),
                    ]
                  : null,
            ),
            child: CustomPaint(
              painter: _PanicRingPainter(progress: progress, color: AppColors.loss),
              child: Center(
                child: _busy
                    ? const SizedBox(
                        width: 12,
                        height: 12,
                        child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.loss),
                      )
                    : const Icon(Icons.power_settings_new_rounded, size: 15, color: AppColors.loss),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _PanicRingPainter extends CustomPainter {
  final double progress;
  final Color color;
  _PanicRingPainter({required this.progress, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = (size.shortestSide - 3) / 2;

    final track = Paint()
      ..color = color.withOpacity(0.18)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round;
    canvas.drawCircle(center, radius, track);

    if (progress <= 0) return;
    final fill = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.2
      ..strokeCap = StrokeCap.round;
    const start = -math.pi / 2;
    final sweep = 2 * math.pi * progress;
    canvas.drawArc(Rect.fromCircle(center: center, radius: radius), start, sweep, false, fill);
  }

  @override
  bool shouldRepaint(covariant _PanicRingPainter oldDelegate) =>
      oldDelegate.progress != progress || oldDelegate.color != color;
}


/// CRYPTO | INDIA switch. One tap changes the market; it sits in the same place in both terminals.
/// Each market has its own colour so one glance tells which one is on screen:
/// Crypto = the app's blue accent, India = saffron.
class MarketModeSwitch extends StatelessWidget {
  const MarketModeSwitch({super.key});

  static const Color indiaColor = Color(0xFFFF9933);

  Widget _seg(BuildContext context, String label, bool on, Color color, VoidCallback onTap) {
    final p = context.palette;
    return Expanded(
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: on ? color : Colors.transparent,
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            label,
            maxLines: 1,
            style: TextStyle(
              color: on ? Colors.black : p.textSecondary,
              fontSize: 10.5,
              fontWeight: FontWeight.w800,
              letterSpacing: 0.2,
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ValueListenableBuilder<String>(
      valueListenable: MarketMode.mode,
      builder: (context, m, _) {
        final india = m == 'india';
        return Container(
          width: 106,
          height: 30,
          padding: const EdgeInsets.all(2),
          decoration: BoxDecoration(
            color: p.surfaceHigher,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: (india ? indiaColor : p.accent).withOpacity(0.6)),
          ),
          child: Row(children: [
            _seg(context, 'CRYPTO', !india, p.accent, () {
              if (india) {
                AppHaptics.light();
                MarketMode.set('crypto');
              }
            }),
            _seg(context, 'INDIA', india, indiaColor, () {
              if (!india) {
                AppHaptics.light();
                MarketMode.set('india');
              }
            }),
          ]),
        );
      },
    );
  }
}
