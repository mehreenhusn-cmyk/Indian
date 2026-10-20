import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'candle_chart.dart';

/// Chart of ONE Free AI trade. It opens the SAME full chart as the positions and the Bot vs AI trades
/// (candles, EMA30/50, SD bands, TSI and Z-score panes, timeframes, pinch zoom, crosshair) and adds:
///   purple triangle  - where the Free AI got IN
///   orange stepped line - every place the AI moved its stop (the "SL" tag is where the stop is NOW)
///   purple flag      - where it got OUT (price and result in USDT)
/// The Free AI has no fixed take-profit, so there is no TP line. Everything comes from the list row,
/// so the chart opens at once (no extra request for the trade). Read-only.
const Color _aiColor = Color(0xFF7C3AED); // purple = AI (same colour as the Bot vs AI chart)
const Color _stopColor = Color(0xFFF59E0B); // orange = the stop and where it moved

double? _n(dynamic v) => v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);
const Map<String, int> _tfMs = {'1m': 60000, '3m': 180000, '5m': 300000, '15m': 900000, '1h': 3600000};

/// [row] = one entry of the Free AI list (live or finished). [money] = the "money" block of the same answer.
void showFreeTradeChart(BuildContext context, {required Map<String, dynamic> row, Map<String, dynamic>? money}) {
  final key = '${row['k'] ?? ''}';
  final parts = key.split('|'); // SYMBOL|tf|candle-close-ms|B or S
  final cd = row['cd'] is Map ? Map<String, dynamic>.from(row['cd'] as Map) : <String, dynamic>{};
  final sym = '${row['sym'] ?? (parts.isNotEmpty ? parts[0] : '')}';
  final tf = '${row['tf'] ?? (parts.length > 1 ? parts[1] : '3m')}';
  final step = _tfMs[tf] ?? 180000;
  final long = row['side'] == 'BUY';
  final closed = cd['state'] == 'closed' || (cd.isEmpty && row['exit'] != null);

  final entry = _n(cd['entry']) ?? _n(row['entry']);
  final barT = _n(cd['bar_t']);
  final int? entryMs = barT != null ? barT.round() + step : (parts.length > 2 ? int.tryParse(parts[2]) : null);
  final sl0 = _n(cd['sl0']) ?? _n(row['sl0']);
  final slNow = _n(cd['sl_now']) ?? _n(row['sl']) ?? sl0;
  final exitPx = closed ? (_n(cd['exit_px']) ?? _n(row['exit'])) : null;
  final exitT = _n(cd['exit_t']);
  final closedSec = _n(row['t']);
  final int? exitMs = closed ? (exitT != null ? exitT.round() + step : (closedSec != null ? (closedSec * 1000).round() : null)) : null;
  final path = <List<double>>[];
  if (cd['sl_path'] is List) {
    for (final e in cd['sl_path'] as List) {
      if (e is List && e.length >= 2 && e[0] is num && e[1] is num) path.add([(e[0] as num).toDouble(), (e[1] as num).toDouble()]);
    }
  }
  final roi = closed ? _n(row['roi']) : _n(row['pnl']);
  final margin = _n(money?['margin']);
  final lev = _n(money?['lev']);
  final usdt = (roi != null && margin != null) ? roi / 100.0 * margin : null;

  // ---- marks and lines on the chart ----
  final entries = <ChartEntryMark>[];
  final exits = <ChartExitMark>[];
  final links = <ChartTradeLink>[];
  if (entryMs != null && entry != null) {
    entries.add(ChartEntryMark(tsMs: entryMs, price: entry, label: 'A', color: _aiColor, isLong: long, note: 'AI IN ${fmtPrice(entry)}'));
  }
  if (closed && exitMs != null && exitPx != null) {
    exits.add(ChartExitMark(
      tsMs: exitMs,
      price: exitPx,
      label: 'A',
      color: _aiColor,
      note: 'AI OUT ${usdt != null ? '${fmtSigned(usdt)} USDT' : (roi != null ? '${fmtSigned(roi)}%' : '')}',
    ));
    if (entryMs != null && entry != null) {
      links.add(ChartTradeLink(fromTsMs: entryMs, fromPrice: entry, toTsMs: exitMs, toPrice: exitPx, color: _aiColor));
    }
  }
  // the stop as it moved: flat piece, then a step up or down, again and again
  if (entryMs != null && sl0 != null && path.isNotEmpty) {
    var t0 = entryMs;
    var p0 = sl0;
    for (final s in path) {
      final t1 = math.max(t0, s[0].round());
      links.add(ChartTradeLink(fromTsMs: t0, fromPrice: p0, toTsMs: t1, toPrice: p0, color: _stopColor));
      links.add(ChartTradeLink(fromTsMs: t1, fromPrice: p0, toTsMs: t1, toPrice: s[1], color: _stopColor));
      t0 = t1;
      p0 = s[1];
    }
    final endMs = math.max(t0, exitMs ?? DateTime.now().millisecondsSinceEpoch);
    links.add(ChartTradeLink(fromTsMs: t0, fromPrice: p0, toTsMs: endMs, toPrice: p0, color: _stopColor));
  }

  showCandleChartSheet(
    context,
    sym,
    entry: entry,
    sl: slNow,
    isLong: long,
    entryTsMs: entryMs,
    focusTsMs: entryMs == null ? null : entryMs - 20 * step,
    entries: entries.isEmpty ? null : entries,
    exits: exits.isEmpty ? null : exits,
    links: links.isEmpty ? null : links,
    initialTf: _tfMs.containsKey(tf) ? tf : null,
    title: '$sym  ${long ? 'LONG' : 'SHORT'}  ·  Free AI',
    summary: _FreeSummary(
      closed: closed,
      how: '${row['how'] ?? cd['how'] ?? ''}',
      roi: roi,
      usdt: usdt,
      margin: margin,
      lev: lev,
      entry: entry,
      sl0: sl0,
      slNow: slNow,
      moves: path.length,
      why: '${cd['why'] ?? ''}',
      exitWhy: closed ? '${cd['exit_why'] ?? row['why'] ?? ''}' : '',
    ),
  );
}

class _FreeSummary extends StatelessWidget {
  final bool closed;
  final String how;
  final double? roi, usdt, margin, lev, entry, sl0, slNow;
  final int moves;
  final String why, exitWhy;
  const _FreeSummary({
    required this.closed,
    required this.how,
    required this.roi,
    required this.usdt,
    required this.margin,
    required this.lev,
    required this.entry,
    required this.sl0,
    required this.slNow,
    required this.moves,
    required this.why,
    required this.exitWhy,
  });

  String _m(double v) => v.toStringAsFixed(v == v.roundToDouble() ? 0 : 2);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final res = roi;
    final head = (closed ? 'Closed${how.isEmpty ? '' : ': $how'}' : 'Open now') +
        (res != null ? '   ${fmtSigned(res)}% of margin' : '') +
        (usdt != null ? '   (${fmtSigned(usdt!)} USDT)' : '');
    final color = res == null ? p.textPrimary : (res >= 0 ? p.profit : p.loss);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border, width: 0.6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(head, style: t.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 14, color: color)),
          if (margin != null)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text('Margin ${_m(margin!)} USDT${lev != null ? ' at ${lev!.toStringAsFixed(0)}x' : ''}  (Settings > Invest Amount)', style: t.metadata),
            ),
          const SizedBox(height: 6),
          Text(
            'Entry ${entry == null ? '-' : fmtPrice(entry!)}   ·   First stop ${sl0 == null ? '-' : fmtPrice(sl0!)}   ·   '
            'Stop ${closed ? 'at exit' : 'now'} ${slNow == null ? '-' : fmtPrice(slNow!)}',
            style: t.metadata.copyWith(height: 1.4),
          ),
          Text(
            moves == 0
                ? 'The AI did not move its stop.'
                : 'The AI moved its stop $moves time${moves == 1 ? '' : 's'} (orange steps). Purple = the AI in and out. No fixed target: it leaves by its own reading.',
            style: t.metadata.copyWith(height: 1.4),
          ),
          if (why.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Why it entered', style: t.section.copyWith(fontSize: 11.5)),
            Text(why, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (exitWhy.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Why it left', style: t.section.copyWith(fontSize: 11.5)),
            Text(exitWhy, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
        ],
      ),
    );
  }
}
