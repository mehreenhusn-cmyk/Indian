import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import '../utils/signal_status.dart';
import 'mini_ladder.dart';
import 'owl_card.dart';

/// One card on the Signals screen. Layout follows Binance's Position
/// History: side box + symbol + tags on top, then a 3-column grid where
/// each cell is a small label over a value, then a one-line footer.
///
/// Backend shape (recovered_bot/signal_log.py `record()`): signal_no,
/// symbol, action, entry_price, stop_loss, tp1-tp4, ist_time_str, opened,
/// skip_reason. Prices use fmtPrice so a 0.08217 coin keeps its decimals.
class SignalTile extends StatelessWidget {
  final Map<String, dynamic> signal;

  /// What became of the signal (TP hit / SL / open ...). Null falls back to
  /// the plain OPENED / SKIPPED / NEW status from the signal record itself.
  final SignalOutcome? outcome;

  const SignalTile({super.key, required this.signal, this.outcome});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;

    final bool isLong = signal['action'] == 'BUY';
    final String? skipReason = signal['skip_reason'] as String?;
    final out = outcome ??
        (signal['opened'] == true
            ? const SignalOutcome('OPENED', SignalOutcomeKind.opened)
            : (skipReason != null
                ? const SignalOutcome('SKIPPED', SignalOutcomeKind.skipped)
                : const SignalOutcome('NEW', SignalOutcomeKind.fresh)));
    final Color statusColor = _kindColor(p, out.kind);
    final Color sideColor = isLong ? p.profit : p.loss;

    final entry = numOrNull(signal['entry_price']);
    final sl = numOrNull(signal['stop_loss']);
    final tp1 = numOrNull(signal['tp1']);
    // TP1..TP4 shown ONCE, under the ladder, as % from entry. Levels with the
    // same price (the SD ladder often repeats the last level: TP2 = TP3 = TP4)
    // collapse into one marker, e.g. "TP2-4", so no space is wasted.
    final tpGroups = _tpGroups(signal, entry);
    final tpLevels = <int>[for (var i = 0; i < tpGroups.length; i++) i + 1];
    final hitGroups = <int>{
      for (var i = 0; i < tpGroups.length; i++)
        if (tpGroups[i].levels.any(out.hitLevels.contains)) i + 1,
    };
    final risk = pctDist(entry, sl);
    final rr1 = rrTo(entry, sl, tp1);

    // Timeframe / leverage / mode are stored WITH the signal when it is
    // created (backend db.py), so an old card never changes when you later
    // change settings. Old signals from before that change simply show no
    // label instead of a wrong one.
    final lev = (signal['leverage'] as num?)?.toInt();
    final tf = (signal['timeframe'] as String?) ?? '';
    final mode = (signal['mode'] as String?) ?? '';
    final tag = lev != null ? 'Perp · ${lev}x' : 'Perp';
    final marginRisk = (risk != null && lev != null) ? risk * lev : null;
    // Reward:risk rating in plain words.
    String? rrWord;
    Color rrColor = p.textSecondary;
    if (rr1 != null) {
      if (rr1 < 1) {
        rrWord = 'Weak';
        rrColor = p.loss;
      } else if (rr1 < 2) {
        rrWord = 'OK';
        rrColor = p.owlEye;
      } else {
        rrWord = 'Good';
        rrColor = p.profit;
      }
    }

    return OWLCard(
      hasPositiveGlow: out.kind == SignalOutcomeKind.win,
      hasNegativeGlow: out.kind == SignalOutcomeKind.loss,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.m),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header: [S] SYMBOL #n  Perp · 10x            STATUS
          Row(
            children: [
              _sidePill(isLong ? 'LONG' : 'SHORT', sideColor),
              const SizedBox(width: AppSpacing.s),
              Flexible(
                child: Text(
                  '${signal['symbol'] ?? 'UNKNOWN'}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: t.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 15),
                ),
              ),
              if (signal['signal_no'] != null) ...[
                const SizedBox(width: 6),
                Text('#${signal['signal_no']}', style: t.metadata),
              ],
              const SizedBox(width: 6),
              _tag(p, tag),
              const Spacer(),
              if (out.kind == SignalOutcomeKind.fresh) ...[
                Container(
                  width: 6,
                  height: 6,
                  margin: const EdgeInsets.only(right: 5),
                  decoration: BoxDecoration(
                    color: statusColor,
                    shape: BoxShape.circle,
                    boxShadow: [BoxShadow(color: statusColor.withOpacity(0.5), blurRadius: 6)],
                  ),
                ),
              ],
              Text(
                out.label,
                style: t.metadata.copyWith(color: statusColor, fontWeight: FontWeight.w800, fontSize: 10, letterSpacing: 0.4),
              ),
              if (out.pnl != null) ...[
                const SizedBox(width: 6),
                Text(
                  fmtSigned(out.pnl!),
                  style: t.metadata.copyWith(color: out.pnl! >= 0 ? p.profit : p.loss, fontWeight: FontWeight.w800, fontSize: 11),
                ),
              ],
            ],
          ),
          const SizedBox(height: AppSpacing.m),
          // Row 1: Entry | Stop Loss (%, price underneath) | R:R (TP1)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _cell(t, p, 'Entry', fmtPrice(entry)),
              _cell(t, p, 'Stop Loss', risk != null ? '-${risk.toStringAsFixed(2)}%' : '--',
                  color: p.loss,
                  sub: fmtPrice(sl) + (marginRisk != null ? ' · ${marginRisk.toStringAsFixed(0)}% margin' : ''),
                  subColor: p.textMuted),
              _cell(t, p, 'R:R (TP1)', fmtRR(rr1), color: rrColor, sub: rrWord, subColor: rrColor),
            ],
          ),
          const SizedBox(height: AppSpacing.s + 4),
          MiniLadder(
            hasSl: sl != null,
            tpLevels: tpLevels,
            tpLabels: [for (final g in tpGroups) g.label],
            tpSubs: [for (final g in tpGroups) g.pct],
            hit: hitGroups,
            slColor: p.loss,
            entryColor: p.textSecondary,
            tpColor: p.profit,
            trackColor: p.border,
            labelColor: p.textMuted,
          ),
          const SizedBox(height: AppSpacing.s + 2),
          // Footer: when it fired, on which timeframe, paper or live
          Text(
            [
              '${signal['ist_time_str'] ?? '--'}',
              if (tf.isNotEmpty) tf,
              if (mode.isNotEmpty) mode,
            ].join(' · '),
            style: t.metadata,
          ),
          // Why it was skipped - full sentence, never cut off.
          if (skipReason != null) ...[
            const SizedBox(height: 6),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline_rounded, size: 13, color: p.owlEye),
                const SizedBox(width: 5),
                Expanded(
                  child: Text(
                    'Skipped: $skipReason',
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: t.metadata.copyWith(color: p.textSecondary),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  /// Distinct TP levels, in order. Consecutive levels with the same price are
  /// merged into one entry (label "TP2-4", pct text "+4.42%").
  static List<_TpGroup> _tpGroups(Map<String, dynamic> signal, double? entry) {
    final out = <_TpGroup>[];
    double? lastPrice;
    for (final k in [1, 2, 3, 4]) {
      final price = numOrNull(signal['tp$k']);
      if (price == null) continue;
      if (lastPrice != null && out.isNotEmpty && (price - lastPrice).abs() <= lastPrice.abs() * 1e-9) {
        out.last.levels.add(k);
      } else {
        final pct = pctDist(entry, price);
        out.add(_TpGroup([k], pct != null ? '+${pct.toStringAsFixed(2)}%' : '--'));
      }
      lastPrice = price;
    }
    return out;
  }

  Widget _sidePill(String word, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(5),
      ),
      child: Text(
        word,
        style: const TextStyle(color: Colors.white, fontSize: 10.5, fontWeight: FontWeight.w800, height: 1.1, letterSpacing: 0.4),
      ),
    );
  }

  Widget _tag(AppPalette p, String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(
        color: p.surfaceHigher,
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 10, fontWeight: FontWeight.w600),
      ),
    );
  }

  Widget _cell(AppText t, AppPalette p, String label, String value,
      {Color? color, String? sub, Color? subColor}) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: t.label),
          const SizedBox(height: 2),
          Text(
            value,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: t.primary.copyWith(
              color: color ?? p.textPrimary,
              fontWeight: FontWeight.w700,
              fontSize: 13.5,
            ),
          ),
          if (sub != null)
            Text(
              sub,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: t.metadata.copyWith(color: subColor ?? p.textMuted, fontSize: 10.5, fontWeight: FontWeight.w600),
            ),
        ],
      ),
    );
  }

  Color _kindColor(AppPalette p, SignalOutcomeKind k) {
    switch (k) {
      case SignalOutcomeKind.fresh:
        return p.owlEye;
      case SignalOutcomeKind.opened:
      case SignalOutcomeKind.open:
        return p.accent;
      case SignalOutcomeKind.win:
        return p.profit;
      case SignalOutcomeKind.loss:
        return p.loss;
      case SignalOutcomeKind.neutral:
        return p.textSecondary;
      case SignalOutcomeKind.skipped:
        return p.textMuted;
    }
  }
}

class _TpGroup {
  final List<int> levels;
  final String pct;
  _TpGroup(this.levels, this.pct);

  String get label => levels.length == 1 ? 'TP${levels.first}' : 'TP${levels.first}-${levels.last}';
}
