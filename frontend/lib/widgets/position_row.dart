import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'ai_advice_badge.dart';
import 'owl_pressable.dart';
import '../theme/owl_look_mode.dart';
import '../screens/position_detail_screen.dart';
import 'position_card.dart';

/// Part 4: the row now has 5 fixed lines (see the comment in build). R22b: price line fits (no '...'), % in one pill. Round 15: ONE compact row per open position (UI rules 1, 2, 7). Profit is the big number, the percent sits under it.
///   left   coin, LONG / SHORT chip, "NO STOP" warning when the exchange has no resting stop, then "open 12 min" and entry -> now
///   right  profit in USDT (big, green / red), ROI percent under it
/// Tap the row = it opens the FULL old PositionCard right under it (chart, entry / SL / TP ladder, move SL, set TP, close) plus the AI advice badge. E9: the row is now a 3-line card and the opened card has no second header.
/// So nothing was removed: every action is still one tap away, the list is just short enough to read all trades at once.
/// Like PositionCard, the row re-reads ITS OWN position from AppProvider.positions by id and rebuilds only when that position changes.
/// A missing number prints "--", never "None".
class PositionRow extends StatefulWidget {
  final Map<String, dynamic> pos;

  const PositionRow({super.key, required this.pos});

  @override
  State<PositionRow> createState() => _PositionRowState();
}

class _PositionRowState extends State<PositionRow> {
  bool _open = false;

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  @override
  Widget build(BuildContext context) {
    final prov = Provider.of<AppProvider>(context, listen: false);
    final id = widget.pos['id'];
    context.select<AppProvider, int>((p) {
      Object? mine;
      for (final x in p.positions) {
        if (x is Map && x['id'] == id) {
          mine = x;
          break;
        }
      }
      final sym = mine is Map ? mine['symbol'] : widget.pos['symbol'];
      return Object.hash('${mine ?? ''}', p.unprotectedPositions.any((u) => u['symbol'] == sym));
    });
    final pos = prov.positions.firstWhere((x) => x is Map && x['id'] == id, orElse: () => widget.pos) as Map<String, dynamic>;
    final p = context.palette;
    final symbol = (pos['symbol'] ?? '--').toString();
    final isLong = pos['action'] == 'BUY';
    final sideColor = isLong ? p.profit : p.loss;
    final pnl = _n(pos['pnl_usdt']);
    final roi = _n(pos['roi_pct']);
    final entry = _n(pos['entry_price']);
    final ltp = _n(pos['ltp']);
    final ts = _n(pos['opened_at_ts']);
    final age = ts == null ? '' : 'open ${fmtSpan(DateTime.now().millisecondsSinceEpoch / 1000 - ts)}';
    final unprotected = prov.unprotectedPositions.any((u) => u['symbol'] == pos['symbol']);
    final pnlColor = pnl == null || pnl == 0 ? p.textPrimary : (pnl > 0 ? p.profit : p.loss);

    // Part 4: strict hierarchy. 1 coin + side | profit USDT  2 age | ROI pill  3 thin bar SL -> TP1 (only when both are real)  4 Entry | Mark  5 Size | Margin | Liq.
    // Every missing number prints "--" (never 0, never a guess). Size = margin x leverage, the same rule as the full PositionCard.
    final invest = _n(pos['invest_usdt']);
    final levRaw = _n(pos['leverage']);
    final sizeText = (invest != null && levRaw != null && levRaw > 0) ? fmtMoney(invest * levRaw) : '--';
    final marginText = invest == null ? '--' : fmtMoney(invest);
    final liq = _n(pos['liq_price']); // only if the backend sends it
    final sl = _n(pos['effective_sl']);
    final tp1 = _n(pos['effective_tp1']);
    final canBar = sl != null && tp1 != null && ltp != null && tp1 != sl;
    double frac(double v) => ((v - sl!) / (tp1! - sl)).clamp(0.0, 1.0).toDouble();

    final src = (pos['source'] ?? '').toString();
    final srcText = src.isEmpty ? '' : (src == 'sniper_learn' ? 'SNIPER LEARN' : src.toUpperCase());

    // E9: ONE compact card of 3 lines + the thin bar (was 5 lines): coin / side / P&L, then age + source + ROI + Details, then entry -> now.
    // Size / margin / liq moved into the opened part. "Trade details" sits INSIDE the card. Tap = the whole trade opens (chart, ladder, close) in one go.
    final row = OWLPressable(
      pressedScale: 0.99,
      onTap: () => setState(() => _open = !_open),
      child: ValueListenableBuilder<int>(
        valueListenable: OwlLookMode.mode,
        builder: (context, lookMode, _) => Container(
        padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.cardPad, AppSpacing.s),
        decoration: OwlLookMode.decoration(p, lookMode, radius: AppSpacing.radiusMedium, edge: unprotected ? p.loss : null) ?? BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: unprotected ? p.loss : p.border),
        ),
        child: IntrinsicHeight(
          child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Container(width: 3, margin: const EdgeInsets.only(right: 10), decoration: BoxDecoration(color: pnlColor.withOpacity(0.9), borderRadius: BorderRadius.circular(2))),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Row(children: [
                  Flexible(child: Text(symbol, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w800))),
                  const SizedBox(width: 6),
                  _chip(context, isLong ? 'LONG' : 'SHORT', sideColor),
                  if (unprotected) ...[const SizedBox(width: 6), _chip(context, 'NO STOP', p.loss)],
                  const Spacer(),
                  Text(pnl == null ? '--' : fmtSigned(pnl), maxLines: 1, style: context.type.number.copyWith(fontSize: 19, fontWeight: FontWeight.w800, color: pnlColor)),
                  Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
                ]),
                const SizedBox(height: 3),
                Row(children: [
                  Expanded(child: Text(age.isEmpty ? srcText : (srcText.isEmpty ? age : '$age  |  $srcText'), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 1.5),
                    decoration: BoxDecoration(color: pnlColor.withOpacity(0.12), borderRadius: BorderRadius.circular(AppSpacing.radiusPill)),
                    child: Text(roi == null ? '--' : '${fmtSigned(roi, 1)}%', style: context.type.metadata.copyWith(fontSize: 12, fontWeight: FontWeight.w700, color: pnlColor)),
                  ),
                  const SizedBox(width: 6),
                  InkWell(
                    borderRadius: BorderRadius.circular(8),
                    onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PositionDetailScreen(pos: pos))),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                      child: Row(mainAxisSize: MainAxisSize.min, children: [
                        Icon(Icons.insights_rounded, size: 15, color: p.accent),
                        const SizedBox(width: 3),
                        Text('Details', style: context.type.metadata.copyWith(color: p.accent, fontWeight: FontWeight.w700)),
                      ]),
                    ),
                  ),
                ]),
                const SizedBox(height: 3),
                Text('Entry ${entry == null ? '--' : fmtPrice(entry)}  >  Now ${ltp == null ? '--' : fmtPrice(ltp)}', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata),
                if (canBar) ...[
                  const SizedBox(height: 6),
                  _bar(p, frac(ltp!), entry == null ? null : frac(entry), pnlColor),
                ],
              ]),
            ),
          ]),
        ),
      )),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.s),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        row,
        if (_open) ...[
          const SizedBox(height: AppSpacing.xs),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: Text('Size $sizeText  |  Margin $marginText  |  Liq ${liq == null ? '--' : fmtPrice(liq)}', style: context.type.metadata),
          ),
          AiAdviceBadge(tradeId: pos['id']),
          PositionCard(pos: pos, startOpen: true, embedded: true),
        ],
      ]),
    );
  }

  /// Part 4: thin bar from SL (left) to TP1 (right); the fill is where the price is now, the small tick is the entry. Drawn only when SL, TP1 and the price are real.
  Widget _bar(AppPalette p, double now, double? entryAt, Color fill) => SizedBox(
        height: 5,
        child: LayoutBuilder(builder: (context, c) {
          final w = c.maxWidth;
          return Stack(clipBehavior: Clip.none, children: [
            Container(width: w, height: 5, decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(3))),
            Container(width: w * now, height: 5, decoration: BoxDecoration(color: fill.withOpacity(0.85), borderRadius: BorderRadius.circular(3))),
            if (entryAt != null) Positioned(left: (w * entryAt - 1).clamp(0.0, w - 2).toDouble(), top: -2, child: Container(width: 2, height: 9, color: p.textMuted)),
          ]);
        }),
      );

  Widget _chip(BuildContext context, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2)),
        child: Text(text, style: context.type.label.copyWith(color: c, fontSize: 10.5, fontWeight: FontWeight.w700)),
      );
}
