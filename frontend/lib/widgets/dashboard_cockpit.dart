import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'glass_card.dart';
import 'owl_pressable.dart';

/// One compact "cockpit" card that replaces the big P&L hero + the four bento
/// tiles: a ring gauge on the left (the P&L number sits inside it, the arc
/// fills as you approach the daily target) and four live stats stacked on the
/// right. The equity chart below it is the only chart - no duplicate sparkline.
///
/// Cheap to paint: one CustomPaint (arc + track), no blur, no controllers.
/// Only the Open P&L reading follows the live price tick, via its own small
/// Selector; everything else comes in as plain values from the dashboard body.
class DashboardCockpit extends StatelessWidget {
  final bool isLive;
  final double todayPnl;
  final double dailyTarget;
  final bool targetHit;
  final int openCount;
  final double winRate;
  final int signalsToday;
  final double marginUsed;
  final void Function(int tab) goToTab;

  const DashboardCockpit({
    super.key,
    required this.isLive,
    required this.todayPnl,
    required this.dailyTarget,
    required this.targetHit,
    required this.openCount,
    required this.winRate,
    required this.signalsToday,
    required this.marginUsed,
    required this.goToTab,
  });

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, String>(
      selector: (_, p) => '${(p.openPnl * 100).round()}|${(p.pnl7d * 100).round()}|${(p.pnl30d * 100).round()}',
      builder: (context, _, __) {
        final prov = context.read<AppProvider>();
        final openPnl = prov.openPnl;
        final p = context.palette;
        // TODAY = closed trades only (same number as the top pill and the Daily target). Open P&L is a small live row.
        final main = isLive ? openPnl : todayPnl;
        final mainColor = main == 0 ? p.textPrimary : (main > 0 ? p.profit : p.loss);
        final hasTarget = !isLive && dailyTarget > 0;
        final progress = hasTarget ? (todayPnl / dailyTarget).clamp(0.0, 1.0).toDouble() : null;

        Widget statRow(String label, String value, {Color? color, VoidCallback? onTap}) {
          final row = Padding(
            padding: const EdgeInsets.symmetric(vertical: 5),
            child: Row(
              children: [
                Expanded(
                  child: Text(label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: context.type.label.copyWith(fontSize: 10.5, letterSpacing: 0.5, color: p.textMuted)),
                ),
                Text(value,
                    maxLines: 1,
                    style: context.type.secondary.copyWith(
                        fontSize: 13.5, fontWeight: FontWeight.w700, color: color ?? p.textPrimary)),
                SizedBox(
                  width: 14,
                  child: onTap == null
                      ? null
                      : Icon(Icons.chevron_right_rounded, size: 14, color: p.textMuted),
                ),
              ],
            ),
          );
          if (onTap == null) return row;
          return OWLPressable(pressedScale: 0.98, onTap: onTap, child: row);
        }

        Widget hairline() => Container(height: 0.5, color: p.border);

        return GlassCard(
          hero: true,
          glowColor: main == 0 ? null : mainColor,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.cardPad),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    SizedBox(
                      width: 116,
                      height: 116,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          Positioned.fill(
                            child: CustomPaint(
                              painter: _RingPainter(
                                progress: progress,
                                color: mainColor == p.textPrimary ? p.accent : mainColor,
                                track: p.border,
                              ),
                            ),
                          ),
                          Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 16),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Text(isLive ? 'Live open' : 'Today',
                                    style: context.type.label.copyWith(fontSize: 9.5, letterSpacing: 0.8, color: p.textMuted)),
                                const SizedBox(height: 2),
                                FittedBox(
                                  fit: BoxFit.scaleDown,
                                  child: TweenAnimationBuilder<double>(
                                    tween: Tween<double>(end: main),
                                    duration: const Duration(milliseconds: 450),
                                    curve: Curves.easeOutCubic,
                                    builder: (context, v, _) => Text(
                                      '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}',
                                      maxLines: 1,
                                      style: AppTypography.numberLarge.copyWith(fontSize: 20, color: mainColor),
                                    ),
                                  ),
                                ),
                                Text('USDT', style: context.type.label.copyWith(fontSize: 9.5, color: p.textMuted)),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: AppSpacing.m),
                    Expanded(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          if (isLive)
                            statRow('Margin used', '${marginUsed.toStringAsFixed(2)} USDT', color: p.accent)
                          else ...[
                            statRow('Open P&L', '${openPnl >= 0 ? '+' : ''}${openPnl.toStringAsFixed(2)}',
                                color: openPnl == 0 ? null : (openPnl > 0 ? p.profit : p.loss)),
                          ],
                          hairline(),
                          if (!isLive) ...[
                            statRow('Win rate today', '${winRate.toStringAsFixed(1)}%', color: p.accent),
                            hairline(),
                          ],
                          // Tabs: 0=Dash, 1=Market, 2=Positions, 3=Signals
                          statRow('Open positions', '$openCount', onTap: () => goToTab(2)),
                          hairline(),
                          statRow('Signals today', '$signalsToday', onTap: () => goToTab(3)),
                        ],
                      ),
                    ),
                  ],
                ),
                if (!isLive) ...[
                  const SizedBox(height: AppSpacing.s),
                  Container(height: 0.5, color: p.border),
                  const SizedBox(height: AppSpacing.s),
                  Row(
                    children: [
                      _periodCell(context, '7D', prov.pnl7d, prov.trades7d),
                      _periodCell(context, '30D', prov.pnl30d, prov.trades30d),
                    ],
                  ),
                ],
                if (hasTarget) ...[
                  const SizedBox(height: AppSpacing.s),
                  Row(
                    children: [
                      Icon(Icons.flag_outlined, size: 13, color: p.textMuted),
                      const SizedBox(width: 6),
                      Text('Daily target (closed trades)', style: context.type.metadata.copyWith(color: p.textMuted)),
                      const Spacer(),
                      Text(
                        '${todayPnl.toStringAsFixed(2)} / ${dailyTarget.toStringAsFixed(2)}  (${((progress ?? 0) * 100).toStringAsFixed(0)}%)',
                        style: context.type.metadata.copyWith(
                            color: targetHit ? p.profit : p.textSecondary, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  /// One cell of the 7D / 30D row: closed-trade P&L (after fee) over the last N trading days + trade count.
  Widget _periodCell(BuildContext context, String label, double pnl, int? trades) {
    final p = context.palette;
    final c = pnl == 0 ? p.textPrimary : (pnl > 0 ? p.profit : p.loss);
    return Expanded(
      child: Container(
      margin: const EdgeInsets.symmetric(horizontal: 4),
      padding: const EdgeInsets.symmetric(vertical: 8),
      decoration: BoxDecoration(
        color: p.surfaceHigher.withOpacity(0.5),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border.withOpacity(0.7), width: 1),
      ),
      child: Column(
        children: [
          Text(label, style: context.type.label.copyWith(fontSize: 10, letterSpacing: 0.6, color: p.textMuted)),
          const SizedBox(height: 2),
          Text('${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)}',
              style: context.type.secondary.copyWith(fontSize: 14, fontWeight: FontWeight.w800, color: c)),
          if (trades != null)
            Text('$trades trades', style: context.type.metadata.copyWith(fontSize: 9.5, color: p.textMuted)),
        ],
      ),
    ));
  }
}

/// Ring gauge: grey track + rounded arc starting at 12 o'clock.
/// [progress] null = no target set -> a faint full ring in the P&L colour.
class _RingPainter extends CustomPainter {
  final double? progress;
  final Color color;
  final Color track;
  const _RingPainter({required this.progress, required this.color, required this.track});

  @override
  void paint(Canvas canvas, Size size) {
    const stroke = 9.0;
    final rect = Offset.zero & size;
    final arcRect = rect.deflate(stroke / 2);
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = progress == null ? color.withOpacity(0.25) : track;
    canvas.drawArc(arcRect, 0, math.pi * 2, false, trackPaint);
    final pr = progress;
    if (pr != null && pr > 0) {
      final arcPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = stroke
        ..strokeCap = StrokeCap.round
        ..color = color;
      canvas.drawArc(arcRect, -math.pi / 2, math.pi * 2 * pr, false, arcPaint);
    }
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) =>
      old.progress != progress || old.color != color || old.track != track;
}
