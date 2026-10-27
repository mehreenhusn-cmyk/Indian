import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'flash_value.dart';
import 'owl_card.dart';
import 'owl_pressable.dart';
import 'owl_status_pill.dart';

/// HH:mm in IST (the app's trading clock) from epoch seconds.
String istHm(double? sec) {
  if (sec == null) return '--';
  final d = DateTime.fromMillisecondsSinceEpoch((sec * 1000).round(), isUtc: true)
      .add(const Duration(hours: 5, minutes: 30));
  return '${d.hour.toString().padLeft(2, '0')}:${d.minute.toString().padLeft(2, '0')}';
}

String _shortDur(double secs) {
  final s = secs < 0 ? 0 : secs.round();
  return fmtSpan(s);
}

/// Everything one row needs. The screen builds it from its own data, so the
/// same row works for Signals, Alerts and the coin history sheet.
class TradeRowData {
  final String symbol;
  final bool isLong;

  /// open | won | lost | skipped | closed | new (see OWLStatusPill.trade)
  final String status;
  final double? entry;

  /// Exit price when closed, live price when open.
  final double? last;
  final bool lastIsLive;

  /// Overrides the "Now" / "Exit" caption (e.g. "Stop" for an open alert).
  final String? lastLabel;
  final double? pnl;
  final double? openedSec;
  final double? closedSec;

  /// Used when there is no open/close time (old signals): e.g. "09:28".
  final String? fallbackTime;

  /// One plain line: "Stopped out", "Why skipped: ...".
  final String? extra;
  final VoidCallback? onTap;

  const TradeRowData({
    required this.symbol,
    required this.isLong,
    required this.status,
    this.entry,
    this.last,
    this.lastIsLive = false,
    this.lastLabel,
    this.pnl,
    this.openedSec,
    this.closedSec,
    this.fallbackTime,
    this.extra,
    this.onTap,
  });
}

/// One clean row for every trade or signal:
///   coin  LONG/SHORT  [STATUS]                       +12.40
///   Entry 67,250 -> Exit 68,100
///   Opened 09:28  Closed 10:05  37m       Details  History
/// Tap = opens the chart (the screen passes [TradeRowData.onTap]).
class TradeRow extends StatelessWidget {
  final TradeRowData data;
  final VoidCallback? onHistory;
  final VoidCallback? onDetails;
  final bool detailsOpen;

  const TradeRow({
    super.key,
    required this.data,
    this.onHistory,
    this.onDetails,
    this.detailsOpen = false,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final d = data;
    final sideColor = d.isLong ? p.profit : p.loss;
    final pnl = d.pnl;
    final pnlColor = pnl == null
        ? p.textMuted
        : (pnl > 0 ? p.profit : (pnl < 0 ? p.loss : p.textSecondary));

    // Time line: Opened 09:28  Closed 10:05  37m   (or "running 12m" while open).
    final nowSec = DateTime.now().millisecondsSinceEpoch / 1000.0;
    final times = <String>[];
    if (d.openedSec != null) times.add('Opened ${istHm(d.openedSec)}');
    if (d.closedSec != null) times.add('Closed ${istHm(d.closedSec)}');
    if (d.openedSec != null && d.closedSec != null) {
      times.add(_shortDur(d.closedSec! - d.openedSec!));
    } else if (d.openedSec != null && d.status == 'open') {
      times.add('running ${_shortDur(nowSec - d.openedSec!)}');
    }
    if (times.isEmpty && d.fallbackTime != null) times.add('Signal ${d.fallbackTime}');

    Widget priceCell(String label, Widget value) => Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: t.label),
            const SizedBox(height: 2),
            value,
          ],
        );

    final priceStyle = t.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 14);
    final lastLabel = d.lastLabel ?? (d.lastIsLive ? 'Now' : 'Exit');
    final Widget lastValue = d.last == null
        ? Text('--', style: priceStyle.copyWith(color: p.textMuted))
        : (d.lastIsLive
            ? FlashValue(value: d.last!, text: fmtPrice(d.last), style: priceStyle)
            : Text(fmtPrice(d.last), style: priceStyle.copyWith(color: pnl == null ? p.textPrimary : pnlColor)));

    Widget action(String label, VoidCallback? cb, {bool on = false}) {
      if (cb == null) return const SizedBox.shrink();
      return OWLPressable(
        onTap: cb,
        pressedScale: 0.94,
        child: Container(
          margin: const EdgeInsets.only(left: 6),
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            color: on ? p.accent.withOpacity(0.14) : Colors.transparent,
            borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
            border: Border.all(color: on ? p.accent.withOpacity(0.5) : p.border),
          ),
          child: Text(
            label,
            style: t.metadata.copyWith(color: on ? p.accent : p.textSecondary, fontWeight: FontWeight.w700),
          ),
        ),
      );
    }

    return OWLPressable(
      onTap: d.onTap,
      pressedScale: 0.985,
      child: OWLCard(
        hasPositiveGlow: d.status == 'won',
        hasNegativeGlow: d.status == 'lost',
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Flexible(
                  child: Text(
                    d.symbol,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: t.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 15),
                  ),
                ),
                const SizedBox(width: 8),
                OwlSideBadge(d.isLong ? 'LONG' : 'SHORT', sideColor),
                const SizedBox(width: 6),
                OWLStatusPill.trade(context, d.status),
                const Spacer(),
                Text(
                  pnl == null ? '--' : fmtSigned(pnl),
                  style: t.primary.copyWith(color: pnlColor, fontWeight: FontWeight.w800, fontSize: 18),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Row(
              children: [
                priceCell('Entry', Text(fmtPrice(d.entry), style: priceStyle)),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  child: Icon(Icons.arrow_forward_rounded, size: 16, color: p.textMuted),
                ),
                priceCell(lastLabel, lastValue),
              ],
            ),
            if (d.extra != null && d.extra!.isNotEmpty) ...[
              const SizedBox(height: 6),
              Text(d.extra!, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.metadata.copyWith(color: p.textSecondary)),
            ],
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Text(
                    times.join('  ·  '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: t.metadata,
                  ),
                ),
                action('Details', onDetails, on: detailsOpen),
                action('History', onHistory),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
