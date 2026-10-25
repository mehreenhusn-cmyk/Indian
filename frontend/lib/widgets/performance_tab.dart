import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Dual Bot "Performance" tab: equity curve, win-rate trend and daily results of the finished paper trades.
/// Numbers come from the Smart Brain reply ("perf"). Real USDT (each trade's own margin, fee inside). Report only.
class PerformanceTab extends StatelessWidget {
  final Map<String, dynamic> brain;
  const PerformanceTab({super.key, required this.brain});

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
  static String _sg(num v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  List<double> _list(dynamic v) => v is List ? v.whereType<num>().map((e) => e.toDouble()).toList() : <double>[];

  Widget _line(AppPalette p, List<double> ys, Color color, {double? flatY, double? minY, double? maxY}) {
    var lo = minY ?? ys.reduce((a, b) => a < b ? a : b);
    var hi = maxY ?? ys.reduce((a, b) => a > b ? a : b);
    if (flatY != null) {
      if (flatY < lo) lo = flatY;
      if (flatY > hi) hi = flatY;
    }
    final pad = (hi - lo).abs() < 0.0001 ? 1.0 : (hi - lo) * 0.1;
    return SizedBox(
      height: 150,
      child: LineChart(LineChartData(
        minY: lo - pad,
        maxY: hi + pad,
        gridData: FlGridData(show: true, drawVerticalLine: false, getDrawingHorizontalLine: (_) => FlLine(color: p.border.withOpacity(0.5), strokeWidth: 1)),
        borderData: FlBorderData(show: false),
        titlesData: FlTitlesData(
          topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          bottomTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
          leftTitles: AxisTitles(
            sideTitles: SideTitles(
              showTitles: true,
              reservedSize: 40,
              getTitlesWidget: (v, meta) => (v == meta.min || v == meta.max)
                  ? const SizedBox.shrink()
                  : Text(v.toStringAsFixed(0), style: TextStyle(fontSize: 9, color: p.textMuted)),
            ),
          ),
        ),
        extraLinesData: flatY == null
            ? null
            : ExtraLinesData(horizontalLines: [HorizontalLine(y: flatY, color: p.textMuted.withOpacity(0.6), strokeWidth: 1, dashArray: [4, 4])]),
        lineTouchData: const LineTouchData(enabled: false),
        lineBarsData: [
          LineChartBarData(
            spots: [for (var i = 0; i < ys.length; i++) FlSpot(i.toDouble(), ys[i])],
            isCurved: false,
            color: color,
            barWidth: 2,
            dotData: const FlDotData(show: false),
            belowBarData: BarAreaData(show: true, color: color.withOpacity(0.08)),
          ),
        ],
      )),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final f = _map(brain['perf']);
    if (f.isEmpty) {
      return OwlSectionCard(title: 'PERFORMANCE', children: [Text('Loading...', style: context.type.secondary)]);
    }
    if ('${f['status']}' != 'ready') {
      return OwlSectionCard(title: 'PERFORMANCE', edge: p.textMuted, children: [Text('${f['text'] ?? 'Collecting.'}', style: context.type.secondary)]);
    }
    final eq = _list(f['equity']);
    final wr = _list(f['winrate']);
    final days = _maps(f['days']);
    final total = _n(f['total']);
    final up = total >= 0;
    final wNow = f['win_now'], wBefore = f['win_before'];
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlSectionCard(title: 'EQUITY CURVE (ALL FINISHED TRADES)', edge: up ? p.profit : p.loss, children: [
        Text('${_sg(total)} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w900, fontSize: 24, color: up ? p.profit : p.loss)),
        Text('${f['text'] ?? ''}', style: context.type.metadata),
        const SizedBox(height: 8),
        if (eq.length >= 2) _line(p, eq, up ? p.profit : p.loss, flatY: 0),
        const SizedBox(height: 4),
        Text('Each point is the running total after a trade. The dotted line is zero.', style: context.type.metadata),
      ]),
      OwlSectionCard(title: 'WIN RATE TREND (LAST 20 TRADES AT A TIME)', children: [
        if (wr.length < 2) Text('Needs 20 finished trades first.', style: context.type.secondary),
        if (wr.length >= 2) ...[
          Text(
              wNow is num && wBefore is num
                  ? 'Now $wNow% won. It started at $wBefore%. ${wNow >= wBefore ? 'Holding up or improving.' : 'Getting weaker.'}'
                  : '',
              style: context.type.primary),
          const SizedBox(height: 8),
          _line(p, wr, p.accent, flatY: 50, minY: 0, maxY: 100),
          const SizedBox(height: 4),
          Text('The dotted line is 50%.', style: context.type.metadata),
        ],
      ]),
      OwlSectionCard(title: 'DAILY RESULTS (5:30 AM IST TO 5:30 AM IST)', children: [
        if (days.isEmpty) Text('No finished day yet.', style: context.type.secondary),
        for (final d in days)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${d['day']}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
                  Text('${_n(d['n']).toInt()} trades, ${_n(d['wins']).toInt()} won', style: context.type.metadata),
                ]),
              ),
              Text('${_sg(_n(d['pnl']))} USDT', style: context.type.secondary.copyWith(fontWeight: FontWeight.w800, color: _n(d['pnl']) >= 0 ? p.profit : p.loss)),
            ]),
          ),
        Text('Best day ${_sg(_n(f['best_day']))}, worst day ${_sg(_n(f['worst_day']))} USDT (days shown).', style: context.type.metadata),
      ]),
    ]);
  }
}
