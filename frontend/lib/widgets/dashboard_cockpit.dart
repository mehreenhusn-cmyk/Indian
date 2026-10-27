import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'glass_card.dart';
import 'owl_card.dart';
import 'owl_pressable.dart';

/// UI1: the Dashboard money card. ONE hero number (Today P&L, 34px), a thin bar toward the daily target,
/// then three equal tiles (Open P&L / Win rate / Open positions) and the 7D / 30D row.
/// In LIVE mode the hero is the live open P&L and the first tile is margin used (same data rules as before).
/// Cheap: no painter, no controller. Only the Open P&L follows the live price tick, through its own Selector.
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
        // TODAY = closed trades only (same number as the top pill and the Daily target). Open P&L is a tile.
        final main = isLive ? openPnl : todayPnl;
        final mainColor = main == 0 ? p.textPrimary : (main > 0 ? p.profit : p.loss);
        final hasTarget = !isLive && dailyTarget > 0;
        final progress = hasTarget ? (todayPnl / dailyTarget).clamp(0.0, 1.0).toDouble() : 0.0;
        String sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';
        Color pc(double v) => v == 0 ? p.textPrimary : (v > 0 ? p.profit : p.loss);

        Widget tile(String label, String value, Color color, {VoidCallback? onTap}) {
          final box = Container(
            padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
            decoration: BoxDecoration(
              color: p.surfaceHigher.withOpacity(0.5),
              borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
              border: Border.all(color: p.border.withOpacity(0.7)),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: AppTypography.eyebrow.copyWith(color: p.textMuted, fontSize: 9.5)),
              const SizedBox(height: 4),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(value, maxLines: 1, style: AppTypography.numberLarge.copyWith(color: color)),
              ),
            ]),
          );
          return Expanded(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 3),
              child: onTap == null ? box : OWLPressable(pressedScale: 0.97, onTap: onTap, child: box),
            ),
          );
        }

        return GlassCard(
          hero: true,
          glowColor: main == 0 ? null : mainColor,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.cardPad),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                OwlHero(label: isLive ? 'LIVE OPEN P&L' : 'TODAY P&L (CLOSED TRADES)', value: main),
                if (hasTarget) ...[
                  const SizedBox(height: AppSpacing.s),
                  ClipRRect(
                    borderRadius: BorderRadius.circular(4),
                    child: Container(
                      height: 5,
                      color: p.border,
                      alignment: Alignment.centerLeft,
                      child: FractionallySizedBox(widthFactor: progress, child: Container(color: targetHit ? p.profit : p.accent)),
                    ),
                  ),
                  const SizedBox(height: 4),
                  Row(children: [
                    Text('Daily target', style: context.type.metadata),
                    const Spacer(),
                    Text('${todayPnl.toStringAsFixed(2)} / ${dailyTarget.toStringAsFixed(2)}  (${(progress * 100).toStringAsFixed(0)}%)',
                        style: context.type.metadata.copyWith(color: targetHit ? p.profit : p.textSecondary, fontWeight: FontWeight.w700)),
                  ]),
                ],
                const SizedBox(height: AppSpacing.m),
                Row(children: [
                  if (isLive) tile('MARGIN USED', marginUsed.toStringAsFixed(2), p.accent) else tile('OPEN P&L', sg(openPnl), pc(openPnl)),
                  if (!isLive) tile('WIN RATE', '${winRate.toStringAsFixed(1)}%', p.accent),
                  // Tabs: 0=Dash, 1=Market, 2=Positions, 3=Signals
                  tile('OPEN POSITIONS', '$openCount', p.textPrimary, onTap: () => goToTab(2)),
                ]),
                const SizedBox(height: AppSpacing.s),
                OWLPressable(
                  pressedScale: 0.99,
                  onTap: () => goToTab(3),
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 4),
                    child: Row(children: [
                      Text('$signalsToday signals today', style: context.type.secondary),
                      const Spacer(),
                      Icon(Icons.chevron_right_rounded, size: 16, color: p.textMuted),
                    ]),
                  ),
                ),
                if (!isLive) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Row(children: [
                    tile('7 DAYS · ${prov.trades7d} TRADES', sg(prov.pnl7d), pc(prov.pnl7d)),
                    tile('30 DAYS · ${prov.trades30d} TRADES', sg(prov.pnl30d), pc(prov.pnl30d)),
                  ]),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
