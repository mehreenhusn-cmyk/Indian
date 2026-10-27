import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'candle_chart.dart';

/// Chart of ONE Dual Bot trade (open or finished). It opens the SAME full chart as the positions and the Free AI
/// trades (candles, EMA30/50, SD bands, TSI and Z panes, timeframes, zoom) and adds:
///   triangle        - where the Dual Bot got IN
///   orange steps    - every place the stop moved (the "SL" tag is where the stop is NOW, or was at the exit)
///   green TP lines  - the 4 SD take-profit levels
///   dot + line      - where it got OUT (finished trades), or the latest price (open trades)
/// Everything comes from the trade row of GET /api/dual_lab, so the chart opens at once. Read-only.
const Color _dualColor = Color(0xFF0EA5E9); // blue = Dual Bot
const Color _stopColor = Color(0xFFF59E0B); // orange = the stop and where it moved
const Map<String, int> _tfMs = {'5m': 300000, '15m': 900000};

double? _n(dynamic v) => v is num ? v.toDouble() : (v is String ? double.tryParse(v) : null);

/// [row] = one entry of "recent" from /api/dual_lab. [margin] = USDT per trade, [lev] = leverage.
void showDualTradeChart(BuildContext context, {required Map<String, dynamic> row, double? margin, double? lev}) {
  final sym = '${row['s'] ?? ''}';
  final tf = '${row['f'] ?? '5m'}';
  final step = _tfMs[tf] ?? 300000;
  final long = (_n(row['d']) ?? 1) > 0;
  final status = '${row['status'] ?? ''}';
  final closed = status == 'closed' || status == 'skipped_done';

  final entry = _n(row['entry']);
  final sl0 = _n(row['sl']);
  final ct = _n(row['ct']);
  final int? entryMs = ct == null ? null : ct.round() + step; // the entry is the close of the signal candle
  final xt = _n(row['xt']);
  final int? lastMs = xt == null ? null : xt.round() + step ~/ 2; // middle of the candle where it ended / the latest candle
  final exitPx = closed ? _n(row['xpx']) : null;
  final livePx = closed ? null : _n(row['lpx']);

  final path = <List<double>>[];
  if (row['path'] is List) {
    for (final e in row['path'] as List) {
      if (e is List && e.length >= 2 && e[0] is num && e[1] is num) path.add([(e[0] as num).toDouble(), (e[1] as num).toDouble()]);
    }
  }
  final slNow = path.isNotEmpty ? path.last[1] : sl0;

  final tps = <int, double?>{};
  if (row['tps'] is List) {
    final l = row['tps'] as List;
    for (var k = 0; k < l.length; k++) {
      tps[k + 1] = _n(l[k]);
    }
  }

  final roi = closed ? _n(row['net']) : _n(row['live']);
  final usdt = (roi != null && margin != null) ? roi / 100.0 * margin : null;
  final skipped = status == 'skipped' || status == 'skipped_done';
  final src = '${row['src'] ?? ''}';
  final srcName = src == 'MAIN' ? 'Main' : (src == 'BOTH' ? 'Main + Z' : (src == 'Z' ? 'Z' : ''));
  final srcLetter = src == 'MAIN' ? 'M' : (src == 'BOTH' ? 'B' : (src == 'Z' ? 'Z' : 'D'));

  final entries = <ChartEntryMark>[];
  final exits = <ChartExitMark>[];
  final links = <ChartTradeLink>[];
  if (entryMs != null && entry != null) {
    entries.add(ChartEntryMark(
        tsMs: entryMs, price: entry, label: srcLetter, color: _dualColor, isLong: long, note: '${skipped ? 'SKIPPED' : 'IN'}${srcName.isEmpty ? '' : ' ($srcName)'} ${fmtPrice(entry)}'));
  }
  if (closed && lastMs != null && exitPx != null) {
    exits.add(ChartExitMark(
      tsMs: lastMs,
      price: exitPx,
      label: 'D',
      color: _dualColor,
      note: 'OUT ${usdt != null ? '${fmtSigned(usdt)} USDT' : (roi != null ? '${fmtSigned(roi)}%' : '')}',
    ));
  }
  // the path of the trade: entry to exit (finished) or entry to the latest price (open)
  final endPx = exitPx ?? livePx;
  if (entryMs != null && entry != null && lastMs != null && endPx != null) {
    links.add(ChartTradeLink(fromTsMs: entryMs, fromPrice: entry, toTsMs: lastMs, toPrice: endPx, color: _dualColor));
  }
  // the stop as it moved: flat piece, then a step up or down, again and again
  if (entryMs != null && sl0 != null) {
    var t0 = entryMs;
    var p0 = sl0;
    for (final s in path) {
      final t1 = math.max(t0, s[0].round());
      links.add(ChartTradeLink(fromTsMs: t0, fromPrice: p0, toTsMs: t1, toPrice: p0, color: _stopColor));
      links.add(ChartTradeLink(fromTsMs: t1, fromPrice: p0, toTsMs: t1, toPrice: s[1], color: _stopColor));
      t0 = t1;
      p0 = s[1];
    }
    final endMs = math.max(t0, closed ? (lastMs ?? t0) : DateTime.now().millisecondsSinceEpoch);
    links.add(ChartTradeLink(fromTsMs: t0, fromPrice: p0, toTsMs: endMs, toPrice: p0, color: _stopColor));
  }

  showCandleChartSheet(
    context,
    sym,
    entry: entry,
    sl: slNow,
    tpLevels: tps.isEmpty ? null : tps,
    isLong: long,
    entryTsMs: entryMs,
    focusTsMs: entryMs == null ? null : entryMs - 20 * step,
    entries: entries.isEmpty ? null : entries,
    exits: exits.isEmpty ? null : exits,
    links: links.isEmpty ? null : links,
    initialTf: _tfMs.containsKey(tf) ? tf : null,
    dualStyle: true, // both panes: main chart on top, Z candles + Z-EMA 30/50 + cloud + BUY/SELL below
    title: '$sym  ${long ? 'LONG' : 'SHORT'}  ·  Dual Bot ($tf)',
    summary: _DualSummaryLine(
      status: status,
      roi: roi,
      usdt: usdt,
      entry: entry,
      slNow: slNow,
      srcName: srcName,
      details: _DualSummary(
      status: status,
      roi: roi,
      usdt: usdt,
      margin: margin,
      lev: lev,
      entry: entry,
      sl0: sl0,
      slNow: slNow,
      moves: path.length,
      scenario: '${row['scn'] ?? ''}',
      what1: '${row['what1'] ?? ''}',
      what2: '${row['what2'] ?? ''}',
      why: '${row['why'] ?? ''}',
      label: '${row['label'] ?? ''}',
      reason: '${row['reason'] ?? ''}',
      mem: row['mem'] is Map ? '${(row['mem'] as Map)['text'] ?? ''}${(row['mem'] as Map)['worst'] != null ? ' Worst sign: ${(row['mem'] as Map)['worst']}.' : ''}' : '',
      setup: row['stp'] is Map ? _setupText(row['stp'] as Map) : '',
      side: row['side'] is List && (row['side'] as List).length == 2 && (row['side'] as List)[0] is num
          ? 'Sideways now: main chart ${(row['side'] as List)[0]}%, Z pane ${(row['side'] as List)[1]}%.'
          : '',
      ),
    ),
  );
}

String _setupText(Map stp) {
  final n = (stp['n'] is num) ? (stp['n'] as num).toInt() : 0;
  if (n == 0) return 'New setup: the bot never saw this picture of both indicators before.';
  final avg = _n(stp['avg']) ?? 0.0;
  final v = '${stp['verdict'] ?? ''}';
  final word = v == 'USE' ? 'a good setup' : (v == 'SKIP' ? 'a bad setup' : (v == 'FEW' ? 'too few trades to judge' : 'not clear yet'));
  return 'Same picture of both indicators happened $n times before: ${stp['win']}% won, average ${avg >= 0 ? '+' : ''}${avg.toStringAsFixed(1)}% of margin. That is $word.';
}

/// ONE short line above the chart, so the chart stays big. The long story is behind the Details button.
class _DualSummaryLine extends StatelessWidget {
  final String status, srcName;
  final double? roi, usdt, entry, slNow;
  final Widget details;
  const _DualSummaryLine({
    required this.status,
    required this.roi,
    required this.usdt,
    required this.entry,
    required this.slNow,
    required this.srcName,
    required this.details,
  });

  String _head() {
    switch (status) {
      case 'closed':
        return 'Finished';
      case 'open':
        return 'Open';
      case 'skipped_done':
        return 'Skipped (would be)';
      case 'skipped':
        return 'Skipped';
      default:
        return status;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final res = usdt ?? roi;
    final color = res == null ? p.textPrimary : (res >= 0 ? p.profit : p.loss);
    final pnl = usdt != null ? '${fmtSigned(usdt!)} USDT' : (roi != null ? '${fmtSigned(roi!)}%' : '');
    final line2 = 'Entry ${entry == null ? '-' : fmtPrice(entry!)}  ·  Stop ${slNow == null ? '-' : fmtPrice(slNow!)}'
        '${srcName.isEmpty ? '' : '  ·  Entry from $srcName'}';
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('${_head()}${pnl.isEmpty ? '' : '   $pnl'}', style: t.primary.copyWith(fontWeight: FontWeight.w800, fontSize: 14, color: color)),
              Text(line2, style: t.metadata, maxLines: 1, overflow: TextOverflow.ellipsis),
            ],
          ),
        ),
        TextButton(
          onPressed: () => showModalBottomSheet(
            context: context,
            isScrollControlled: true,
            backgroundColor: p.surfaceElevated,
            shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
            builder: (_) => SafeArea(
              child: ConstrainedBox(
                constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.8),
                child: SingleChildScrollView(padding: const EdgeInsets.all(12), child: details),
              ),
            ),
          ),
          child: const Text('Details'),
        ),
      ],
    );
  }
}

class _DualSummary extends StatelessWidget {
  final String status, scenario, what1, what2, why, label, reason, mem, side, setup;
  final double? roi, usdt, margin, lev, entry, sl0, slNow;
  final int moves;
  const _DualSummary({
    required this.status,
    required this.roi,
    required this.usdt,
    required this.margin,
    required this.lev,
    required this.entry,
    required this.sl0,
    required this.slNow,
    required this.moves,
    required this.scenario,
    required this.what1,
    required this.what2,
    required this.why,
    this.label = '',
    this.reason = '',
    this.mem = '',
    this.side = '',
    this.setup = '',
  });

  String _head() {
    switch (status) {
      case 'closed':
        return 'Finished';
      case 'open':
        return 'Open now';
      case 'skipped_done':
        return 'Skipped (what it would have made)';
      case 'skipped':
        return 'Skipped (still followed)';
      default:
        return status;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final res = roi;
    final head = _head() + (res != null ? '   ${fmtSigned(res)}% of margin' : '') + (usdt != null ? '   (${fmtSigned(usdt!)} USDT)' : '');
    final color = res == null ? p.textPrimary : (res >= 0 ? p.profit : p.loss);
    final done = status == 'closed' || status == 'skipped_done';
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
              child: Text('Paper: ${margin!.toStringAsFixed(0)} USDT${lev != null ? ' at ${lev!.toStringAsFixed(0)}x' : ''}', style: t.metadata),
            ),
          const SizedBox(height: 6),
          Text(
            'Entry ${entry == null ? '-' : fmtPrice(entry!)}   ·   First stop ${sl0 == null ? '-' : fmtPrice(sl0!)}   ·   '
            'Stop ${done ? 'at exit' : 'now'} ${slNow == null ? '-' : fmtPrice(slNow!)}',
            style: t.metadata.copyWith(height: 1.4),
          ),
          Text(
            moves == 0
                ? 'The stop did not move.'
                : 'The stop moved $moves time${moves == 1 ? '' : 's'} (orange steps). Blue line = entry to ${done ? 'exit' : 'latest price'}. Green lines = take-profit levels.',
            style: t.metadata.copyWith(height: 1.4),
          ),
          if (scenario.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('The situation', style: t.section.copyWith(fontSize: 11.5)),
            Text(scenario, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (what1.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('What happened', style: t.section.copyWith(fontSize: 11.5)),
            Text(what1, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
            if (what2.isNotEmpty) Text(what2, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (side.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Reading line', style: t.section.copyWith(fontSize: 11.5)),
            Text(side, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (label == 'real' || label == 'fake') ...[
            const SizedBox(height: 8),
            Text(label == 'fake' ? 'FAKE signal' : 'REAL move', style: t.section.copyWith(fontSize: 11.5, color: label == 'fake' ? p.loss : p.profit)),
            Text(reason, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (setup.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Setup record', style: t.section.copyWith(fontSize: 11.5)),
            Text(setup, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (mem.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Old mistakes vs this trade', style: t.section.copyWith(fontSize: 11.5)),
            Text(mem, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
          if (why.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Why the bot took it', style: t.section.copyWith(fontSize: 11.5)),
            Text(why, style: t.secondary.copyWith(fontSize: 12, height: 1.35)),
          ],
        ],
      ),
    );
  }
}
