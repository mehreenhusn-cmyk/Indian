import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import '../widgets/owl_route.dart';
import 'strategy_doctor_screen.dart';

/// India "Stats" page: how the paper bot is doing, in a few big numbers.
/// Win rate, R:R, expectancy and drawdown are computed on the backend (india_stats.py) from closed trades,
/// with charges already taken off. Nothing here changes the bot.
class IndiaStatsTab extends StatefulWidget {
  final IndiaApi api;
  const IndiaStatsTab({super.key, required this.api});

  @override
  State<IndiaStatsTab> createState() => _IndiaStatsTabState();
}

class _IndiaStatsTabState extends State<IndiaStatsTab> {
  Map<String, dynamic>? _s;
  Map<String, dynamic>? _doc;
  String? _err;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final s = Map<String, dynamic>.from(await widget.api.get('/stats') as Map);
      Map<String, dynamic>? d;
      try {
        d = Map<String, dynamic>.from(await widget.api.get('/doctor') as Map);
      } catch (_) {}
      if (!mounted) return;
      setState(() {
        _s = s;
        _doc = d ?? _doc;
        _err = null;
      });
    } catch (e) {
      if (mounted) setState(() => _err = friendlyError(e));
    }
  }

  double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  Color _c(BuildContext c, double v) => v > 0 ? c.palette.profit : (v < 0 ? c.palette.loss : c.palette.textSecondary);
  String _rs(double v) => '${v < 0 ? '-' : (v > 0 ? '+' : '')}${inr(v.abs(), dp: 0)}';

  Widget _big(BuildContext context, String label, String value, {Color? color, String? sub}) {
    final p = context.palette;
    return Expanded(
      child: ICard(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: IT.small(context).copyWith(letterSpacing: 0.3)),
          const SizedBox(height: 4),
          FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, maxLines: 1, style: IT.big(context).copyWith(color: color ?? p.textPrimary))),
          if (sub != null) ...[const SizedBox(height: 2), Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: IT.small(context).copyWith(fontSize: 10))],
        ]),
      ),
    );
  }

  Widget _row2(Widget a, Widget b) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(children: [a, const SizedBox(width: 8), b]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = _s;
    if (s == null) {
      return Center(child: _err != null ? Text(_err!, style: IT.small(context).copyWith(color: p.loss)) : const CircularProgressIndicator());
    }
    final n = _i(s['trades']);
    final net = _d(s['net_pnl']);
    final rr = s['rr'];
    final pf = s['profit_factor'];
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, 4, AppSpacing.l, AppSpacing.huge),
        children: [
          if (n == 0)
            ICard(child: Text('No closed trades yet. Numbers appear after the first trade closes.', style: IT.body(context))),
          if (n > 0) ...[
            if (n < 30)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text('Only $n trades so far - these numbers can still swing a lot. Judge after 30+.', style: IT.small(context).copyWith(color: p.warning)),
              ),
            _row2(
              _big(context, 'NET P&L (after charges)', _rs(net), color: _c(context, net), sub: 'charges paid ${inr(_d(s['fees']), dp: 0)}'),
              _big(context, 'WIN RATE', '${_d(s['win_rate']).toStringAsFixed(0)}%', sub: '${_i(s['wins'])} won · ${_i(s['losses'])} lost'),
            ),
            _row2(
              _big(context, 'R : R', rr == null ? '—' : '1 : ${_d(rr).toStringAsFixed(2)}', sub: 'avg win ${inr(_d(s['avg_win']), dp: 0)} / avg loss ${inr(_d(s['avg_loss']).abs(), dp: 0)}'),
              _big(context, 'EXPECTANCY', _rs(_d(s['expectancy'])), color: _c(context, _d(s['expectancy'])), sub: 'per trade, on average'),
            ),
            _row2(
              _big(context, 'MAX DRAWDOWN', inr(_d(s['max_drawdown']), dp: 0), color: p.loss, sub: '${_d(s['max_drawdown_pct']).toStringAsFixed(1)}% from the peak'),
              _big(context, 'PROFIT FACTOR', pf == null ? '—' : _d(pf).toStringAsFixed(2), sub: 'wins ÷ losses, above 1 = profit'),
            ),
            const SizedBox(height: 4),
            const IHeading('Equity curve'),
            ICard(padding: const EdgeInsets.fromLTRB(8, 14, 12, 8), child: SizedBox(height: 170, child: _curve(context, s))),
            const SizedBox(height: 8),
            _row2(
              _big(context, 'BEST TRADE', _rs(_d(s['best_trade'])), color: p.profit, sub: 'win streak ${_i(s['max_win_streak'])}'),
              _big(context, 'WORST TRADE', _rs(_d(s['worst_trade'])), color: p.loss, sub: 'loss streak ${_i(s['max_loss_streak'])}'),
            ),
            const IHeading('Where it makes / loses money'),
            _groupCard(context, 'By index', s['by_index']),
            const SizedBox(height: 8),
            _groupCard(context, 'Call (CE) vs Put (PE)', s['by_side']),
            const SizedBox(height: 8),
            _exitCard(context, s['by_exit']),
          ],
          const SizedBox(height: 12),
          _doctorCard(context),
        ],
      ),
    );
  }

  Widget _curve(BuildContext context, Map<String, dynamic> s) {
    final p = context.palette;
    final pts = (s['curve'] as List?) ?? [];
    if (pts.length < 2) return Center(child: Text('Needs 2+ closed trades.', style: IT.small(context)));
    final ys = pts.map((e) => _d((e as Map)['v'])).toList();
    final base = _d(s['capital']);
    final lo = ys.reduce((a, b) => a < b ? a : b), hi = ys.reduce((a, b) => a > b ? a : b);
    final pad = (hi - lo).abs() * 0.1 + 1;
    final up = ys.last >= base;
    final col = up ? p.profit : p.loss;
    return LineChart(LineChartData(
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
            reservedSize: 52,
            getTitlesWidget: (v, meta) => (v == meta.min || v == meta.max)
                ? const SizedBox.shrink()
                : Text(inr(v, dp: 0).replaceFirst('₹', ''), style: IT.small(context).copyWith(fontSize: 9)),
          ),
        ),
      ),
      extraLinesData: ExtraLinesData(horizontalLines: [
        HorizontalLine(y: base, color: p.textSecondary.withOpacity(0.6), strokeWidth: 1, dashArray: [4, 4]),
      ]),
      lineTouchData: const LineTouchData(enabled: false),
      lineBarsData: [
        LineChartBarData(
          spots: [for (var i = 0; i < ys.length; i++) FlSpot(i.toDouble(), ys[i])],
          isCurved: false,
          color: col,
          barWidth: 2.2,
          dotData: const FlDotData(show: false),
          belowBarData: BarAreaData(show: true, color: col.withOpacity(0.10)),
        ),
      ],
    ));
  }

  Widget _groupCard(BuildContext context, String title, dynamic rows) {
    final list = (rows is List) ? rows.whereType<Map>().toList() : <Map>[];
    return ICard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: IT.h(context)),
        const SizedBox(height: 6),
        if (list.isEmpty) Text('—', style: IT.small(context)),
        for (final r in list)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Row(children: [
              Expanded(child: Text('${r['label']}', style: IT.body(context))),
              Text('${_i(r['n'])} trades · ${_d(r['win_rate']).toStringAsFixed(0)}% · ', style: IT.small(context)),
              Text(_rs(_d(r['net'])), style: IT.body(context).copyWith(fontWeight: FontWeight.w800, color: _c(context, _d(r['net'])))),
            ]),
          ),
      ]),
    );
  }

  Widget _exitCard(BuildContext context, dynamic rows) {
    final list = (rows is List) ? rows.whereType<Map>().toList() : <Map>[];
    final p = context.palette;
    return ICard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('How trades ended', style: IT.h(context)),
        const SizedBox(height: 8),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final r in list)
            IPill('${r['label']}  ${_i(r['n'])}', '${r['label']}'.startsWith('TP') ? p.profit : ('${r['label']}'.contains('SL') ? p.loss : p.textSecondary)),
        ]),
      ]),
    );
  }

  Widget _doctorCard(BuildContext context) {
    final p = context.palette;
    final d = _doc;
    final heads = (d != null && d['headline'] is List) ? (d['headline'] as List).map((e) => '$e').toList() : <String>[];
    final n = d == null ? 0 : _i(d['sample']);
    final enough = d != null && d['enough'] == true;
    final conf = d == null ? 0 : ((d['avoid'] as List?) ?? []).whereType<Map>().where((r) => r['status'] == 'confirmed').length;
    final badge = d == null ? 'Loading' : (n == 0 ? 'No trades yet' : (enough ? (conf > 0 ? '$conf leak${conf == 1 ? '' : 's'} confirmed' : 'No leak confirmed') : 'Learning $n/${_i(d['min_sample'])}'));
    final bc = d == null || n == 0 ? p.textMuted : (enough ? (conf > 0 ? p.warning : p.profit) : p.warning);
    return GestureDetector(
      onTap: () => Navigator.of(context).push(OwlRoute(builder: (_) => const StrategyDoctorScreen(india: true))),
      child: ICard(
        tint: bc.withOpacity(0.5),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.medical_services_outlined, size: 17, color: p.accent),
            const SizedBox(width: 8),
            Expanded(child: Text('Strategy Doctor', style: IT.h(context))),
            IPill(badge, bc),
            Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
          ]),
          const SizedBox(height: 6),
          Text(heads.length > 2 ? heads[2] : (heads.isNotEmpty ? heads.first : 'Tap to see which entries lose and which win.'),
              maxLines: 3, overflow: TextOverflow.ellipsis, style: IT.small(context).copyWith(height: 1.35)),
        ]),
      ),
    );
  }
}
