import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../navigation/app_routes.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'owl_card.dart';
import 'owl_pressable.dart';

/// UI1 / SR1b: the Dashboard money card. ONE hero number (Today P&L, 36px), a thin bar toward the daily target,
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
      selector: (_, p) => '${(p.openPnl * 100).round()}|${(p.pnl7d * 100).round()}|${(p.pnl30d * 100).round()}|${(((p.splitGroup('main')['pnl'] as num?) ?? 0) * 100).round()}|${(((p.splitGroup('sniper')['pnl'] as num?) ?? 0) * 100).round()}|${p.splitBlock == null ? 0 : 1}',
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
              color: p.bg,
              borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4),
              border: Border.all(color: p.border),
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

        // Part 18: one small table, MAIN and SNIPER on their own rows. Never added together.
        double nv(Map<String, dynamic> m, String k) => (m[k] as num?)?.toDouble() ?? 0.0;
        Widget scell(String t, {Color? color, bool bold = false, int flex = 1}) => Expanded(
              flex: flex,
              child: Text(t, maxLines: 1, overflow: TextOverflow.ellipsis, textAlign: flex == 2 ? TextAlign.left : TextAlign.right, style: context.type.metadata.copyWith(color: color ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w500)),
            );
        Widget splitRow(String name, Map<String, dynamic> m) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(children: [
                scell(name, bold: true, flex: 2, color: p.textPrimary),
                scell('${(m['n'] as num?)?.toInt() ?? 0} · ${sg(nv(m, 'pnl'))}', color: pc(nv(m, 'pnl'))),
                scell(sg(nv(m, 'today_pnl')), color: pc(nv(m, 'today_pnl'))),
                scell(sg(nv(m, 'd7_pnl')), color: pc(nv(m, 'd7_pnl'))),
                scell(sg(nv(m, 'd30_pnl')), color: pc(nv(m, 'd30_pnl'))),
              ]),
            );
        final splitAll = isLive ? null : prov.splitBlock;

        // SR1b: the same calm card as the rest of the app (OWLCard); a thin green / red rim follows the sign of the hero number.
        return OWLCard(
          padding: EdgeInsets.zero,
          hasPositiveGlow: main > 0,
          hasNegativeGlow: main < 0,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.l),
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
                Divider(height: 24, thickness: 1, color: p.border),
                Row(children: [
                  if (isLive) tile('MARGIN USED', marginUsed.toStringAsFixed(2), p.accent) else tile('OPEN P&L', sg(openPnl), pc(openPnl)),
                  if (!isLive) tile('WIN RATE', '${winRate.toStringAsFixed(1)}%', p.accent),
                  tile('OPEN POSITIONS', '$openCount', p.textPrimary, onTap: () => goToTab(AppRoutes.screenIndex(AppRoute.positions))),
                ]),
                const SizedBox(height: AppSpacing.s),
                OWLPressable(
                  pressedScale: 0.99,
                  onTap: () => goToTab(AppRoutes.screenIndex(AppRoute.signals)),
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
                if (splitAll != null) ...[
                  Divider(height: 24, thickness: 1, color: p.border),
                  Text('MAIN BOT vs SNIPER (apart, never added)', style: AppTypography.eyebrow.copyWith(color: p.textMuted, fontSize: 9.5)),
                  const SizedBox(height: 6),
                  Row(children: [
                    scell('', flex: 2),
                    scell('OPEN', color: p.textMuted),
                    scell('TODAY', color: p.textMuted),
                    scell('7D', color: p.textMuted),
                    scell('30D', color: p.textMuted),
                  ]),
                  splitRow('MAIN', prov.splitGroup('main')),
                  splitRow('SNIPER', prov.splitGroup('sniper')),
                  if (splitAll['d7_partial'] == true || splitAll['d30_partial'] == true)
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text('7D / 30D are partial: the book keeps only the last 1500 trades.', style: context.type.metadata.copyWith(color: p.textMuted)),
                    ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}
