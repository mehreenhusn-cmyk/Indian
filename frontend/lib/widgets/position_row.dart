import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'ai_advice_badge.dart';
import 'owl_pressable.dart';
import '../screens/position_detail_screen.dart';
import 'position_card.dart';

/// Round 15: ONE compact row per open position (UI rules 1, 2, 7). Profit is the big number, the percent sits under it.
///   left   coin, LONG / SHORT chip, "NO STOP" warning when the exchange has no resting stop, then "open 12 min" and entry -> now
///   right  profit in USDT (big, green / red), ROI percent under it
/// Tap the row = it opens the FULL old PositionCard right under it (chart, entry / SL / TP ladder, move SL, set TP, close) plus the AI advice badge.
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
    final prices = (entry != null && ltp != null) ? '${fmtPrice(entry)} -> ${fmtPrice(ltp)}' : '';
    final meta = [if (age.isNotEmpty) age, if (prices.isNotEmpty) prices].join('  ·  ');

    final row = OWLPressable(
      pressedScale: 0.99,
      onTap: () => setState(() => _open = !_open),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.m),
        decoration: BoxDecoration(
          color: p.surface,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: unprotected ? p.loss : p.border),
        ),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(symbol, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w800))),
                const SizedBox(width: 6),
                _chip(context, isLong ? 'LONG' : 'SHORT', sideColor),
                if (unprotected) ...[const SizedBox(width: 6), _chip(context, 'NO STOP', p.loss)],
              ]),
              if (meta.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 3), child: Text(meta, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
            ]),
          ),
          const SizedBox(width: 8),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(pnl == null ? '--' : fmtSigned(pnl), style: context.type.number.copyWith(fontSize: 20, fontWeight: FontWeight.w800, color: pnlColor)),
            Text(roi == null ? '--' : '${fmtSigned(roi, 1)}%', style: context.type.metadata.copyWith(color: pnlColor)),
          ]),
          Icon(_open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
        ]),
      ),
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        row,
        if (_open) ...[
          const SizedBox(height: AppSpacing.s),
          AiAdviceBadge(tradeId: pos['id']),
          // Round 16: the detail page (best point, worst dip, give-back, indicator health)
          Align(
            alignment: Alignment.centerRight,
            child: TextButton.icon(
              onPressed: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => PositionDetailScreen(pos: pos))),
              icon: const Icon(Icons.insights_rounded, size: 18),
              label: const Text('Trade details'),
            ),
          ),
          PositionCard(pos: pos),
        ],
      ]),
    );
  }

  Widget _chip(BuildContext context, String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall - 2)),
        child: Text(text, style: context.type.label.copyWith(color: c, fontSize: 10.5, fontWeight: FontWeight.w700)),
      );
}
