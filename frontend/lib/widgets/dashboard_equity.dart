import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../theme/app_theme.dart';
import 'glass_card.dart';

/// Round 13: the Dashboard equity curve (cumulative closed-trade P&L with a timeframe row), moved word for word
/// out of dashboard_screen.dart. Only the name changed (DashboardEquityChart). No behaviour changed.

const _equityTfOptions = ['15m', '1h', '2h', '1d', '3d', '7d'];

class DashboardEquityChart extends StatelessWidget {
  final List<Map<String, dynamic>> data;
  final String selectedTf;
  final ValueChanged<String> onTfChanged;

  const DashboardEquityChart(this.data, this.selectedTf, this.onTfChanged);

  double _num(dynamic v) => (v is num) ? v.toDouble() : 0.0;

  String _label(dynamic v) {
    final d = (v ?? '').toString();
    if (d == 'start') return 'start';
    // "2026-09-24" -> "09-24"; "14:30" stays as is.
    return (d.length == 10 && d[4] == '-') ? d.substring(5) : d;
  }

  @override
  Widget build(BuildContext context) {
    final tfRow = SizedBox(
      height: 36,
      child: ListView(
        scrollDirection: Axis.horizontal,
        children: _equityTfOptions.map((tf) {
          final isSelected = tf == selectedTf;
          return Padding(
            padding: const EdgeInsets.only(right: 8), // Part 6: more room between the time buttons
            child: ChoiceChip(
              label: Text(tf),
              selected: isSelected,
              // No check-mark: it made the selected chip wider and pushed
              // the last chip ("7d") half off-screen.
              showCheckmark: false,
              onSelected: (_) => onTfChanged(tf),
              backgroundColor: context.palette.glassFill,
              selectedColor: context.palette.accent.withOpacity(0.25),
              labelStyle: AppTypography.secondaryData.copyWith(color: isSelected ? context.palette.accent : context.palette.textSecondary, fontSize: 12, fontWeight: isSelected ? FontWeight.w700 : FontWeight.normal),
              side: BorderSide(
                color: isSelected ? context.palette.accent : Colors.transparent,
              ),
              padding: const EdgeInsets.symmetric(horizontal: 10), // Part 6: was 4, the buttons looked cramped
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
              visualDensity: VisualDensity.compact,
            ),
          );
        }).toList(),
      ),
    );

    Widget shell(List<Widget> children) => GlassCard(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.l),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
          ),
        );

    if (data.isEmpty) {
      return shell([
        Text('Equity Curve',
            style: AppTypography.primaryData.copyWith(color: context.palette.textPrimary, fontSize: 16, fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        tfRow,
        Padding(
          padding: const EdgeInsets.all(AppSpacing.section),
          child: Center(
            child: Text('No trades yet - baseline will fill in once trading starts',
                textAlign: TextAlign.center,
                style: context.type.secondary.copyWith(color: context.palette.textMuted)),
          ),
        ),
      ]);
    }

    // Values can arrive as int (e.g. 0) - always go through _num, a raw
    // `?? 0.0` handed an int to FlSpot and silently broke the whole chart.
    final ys = data.map((e) => _num(e['cumulative'])).toList();
    // A single point draws nothing; duplicate it so a flat line still shows.
    final plotYs = ys.length == 1 ? [ys.first, ys.first] : ys;
    final spots = <FlSpot>[
      for (int i = 0; i < plotYs.length; i++) FlSpot(i.toDouble(), plotYs[i]),
    ];

    final maxY = plotYs.fold<double>(0, (a, b) => a > b ? a : b);
    final minY = plotYs.fold<double>(0, (a, b) => a < b ? a : b);
    final range = (maxY - minY).abs() < 0.01 ? 1.0 : (maxY - minY).abs();
    final total = ys.last;
    final totalColor = total >= 0 ? context.palette.profit : context.palette.loss;
    final lineColor = total >= 0 ? context.palette.accent : context.palette.loss;
    final lastIdx = spots.length - 1;
    final hasTrades = data.any((e) => _num(e['pnl']) != 0);

    return shell([
      Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Equity Curve',
              style: AppTypography.primaryData.copyWith(color: context.palette.textPrimary, fontSize: 16, fontWeight: FontWeight.w700)),
          Text(
            '${total >= 0 ? '+' : ''}${total.toStringAsFixed(2)} USDT',
            style: AppTypography.primaryData.copyWith(color: totalColor, fontSize: 14, fontWeight: FontWeight.w700),
          ),
        ],
      ),
      const SizedBox(height: 8),
      tfRow,
      const SizedBox(height: 12),
      SizedBox(
        height: 160,
        child: LineChart(
          LineChartData(
            gridData: FlGridData(
              show: true,
              drawVerticalLine: false,
              horizontalInterval: range / 3,
              getDrawingHorizontalLine: (_) => FlLine(color: context.palette.textMuted.withOpacity(0.10), strokeWidth: 1),
            ),
            borderData: FlBorderData(show: false),
            titlesData: FlTitlesData(
              show: true,
              leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              rightTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              topTitles: AxisTitles(sideTitles: SideTitles(showTitles: false)),
              bottomTitles: AxisTitles(
                sideTitles: SideTitles(
                  showTitles: true,
                  reservedSize: 20,
                  interval: 1,
                  getTitlesWidget: (value, meta) {
                    final i = value.toInt();
                    if (value != i.toDouble() || i < 0 || i >= data.length) {
                      return const SizedBox.shrink();
                    }
                    // Only first / middle / last label so they never overlap.
                    if (i != 0 && i != data.length - 1 && i != data.length ~/ 2) {
                      return const SizedBox.shrink();
                    }
                    return Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(_label(data[i]['date']),
                          style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 9)),
                    );
                  },
                ),
              ),
            ),
            extraLinesData: ExtraLinesData(horizontalLines: [
              HorizontalLine(
                y: 0,
                color: context.palette.textMuted.withOpacity(0.35),
                strokeWidth: 1,
                dashArray: [4, 4],
              ),
            ]),
            lineTouchData: LineTouchData(
              touchTooltipData: LineTouchTooltipData(
                tooltipBgColor: context.palette.surface,
                getTooltipItems: (touched) => touched.map((t) {
                  final i = t.x.toInt().clamp(0, data.length - 1).toInt();
                  final pnl = _num(data[i]['pnl']);
                  return LineTooltipItem(
                    '${_label(data[i]['date'])}\n'
                    'total ${t.y >= 0 ? '+' : ''}${t.y.toStringAsFixed(2)}\n'
                    'this bucket ${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)}',
                    AppTypography.metadata.copyWith(color: Colors.white, fontSize: 11),
                  );
                }).toList(),
              ),
            ),
            lineBarsData: [
              LineChartBarData(
                spots: spots,
                isCurved: spots.length > 3,
                curveSmoothness: 0.2,
                preventCurveOverShooting: true,
                color: lineColor,
                barWidth: 2.5,
                dotData: FlDotData(
                  show: true,
                  checkToShowDot: (spot, barData) =>
                      spots.length <= 12 || spot.x.toInt() == lastIdx,
                ),
                belowBarData: BarAreaData(
                  show: true,
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [lineColor.withOpacity(0.28), lineColor.withOpacity(0.0)],
                  ),
                ),
              ),
            ],
            minY: minY - range * 0.15,
            maxY: maxY + range * 0.15,
          ),
        ),
      ),
      if (hasTrades)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('Peak ${ys.reduce((x, y) => x > y ? x : y).toStringAsFixed(2)}  |  Low ${ys.reduce((x, y) => x < y ? x : y).toStringAsFixed(2)}  |  ${data.length} points',
              style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 11)),
        ),
      if (!hasTrades)
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('No closed trades in this window yet - flat baseline shown',
              style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 11)),
        ),
    ]);
  }
}
