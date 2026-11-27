import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_active.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'candle_chart.dart';
import 'owl_kit_extras.dart'; // Part 15: shared UI kit (Parts 8 + 9)
import 'owl_kit_parts.dart';

/// Round H (26 Nov 2026): the "7 Days" tab of the Market screen. Every coin that was in Binance's TOP 10 GAINERS or TOP 10 LOSERS on any of the last
/// 7 completed days (day = 5:30 AM IST to 5:30 AM IST), ONE list, no section split. One row per coin = its newest day in a top-10 list.
/// Row: coin, G / L tag, that day, how many days it came back, that day's % move, and how it is doing NOW (since that day's close, over the 7 days, 24h).
/// Data: GET /api/top10_7d (the backend builds it from Binance daily candles, so all 7 days are there at once). Refreshes every 45 s while open;
/// while the backend is still building (about 1 minute, once a day) it asks again every 5 s. Dart NOT compiled in the sandbox.
class Top10WeekList extends StatefulWidget {
  final String query;
  const Top10WeekList({super.key, this.query = ''});

  @override
  State<Top10WeekList> createState() => _Top10WeekListState();
}

class _Top10WeekListState extends State<Top10WeekList> {
  static Map<String, dynamic>? _last; // kept while the app runs: coming back shows the old list at once
  Map<String, dynamic>? _r = _last;
  bool _busy = false;
  bool _failed = false;
  Timer? _timer;
  int _tick = 0;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = AppActive.every(const Duration(seconds: 5), () {
      _tick++;
      final building = _r?['building'] == true;
      if (building || _tick % 9 == 0) _load(); // every 5 s while building, else about every 45 s
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy || !mounted) return;
    _busy = true;
    final d = await context.read<AppProvider>().getBtcJson('/api/top10_7d'); // generic GET helper
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (d != null && d['state'] != 'error') {
        _r = d;
        _last = d;
        _failed = false;
      } else if (_r == null) {
        _failed = true;
      }
    });
  }

  static double _n(Object? v) => v is num ? v.toDouble() : 0.0;
  static String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';
  static String _dayLabel(String ymd) {
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    final p = ymd.split('-');
    if (p.length != 3) return ymd;
    final mi = (int.tryParse(p[1]) ?? 1).clamp(1, 12);
    return '${int.tryParse(p[2]) ?? p[2]} ${m[mi - 1]}';
  }

  String _coin(String s) => s.endsWith('USDT') ? s.substring(0, s.length - 4) : s;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    if (r == null) {
      if (!_failed) return const OwlShimmerList(count: 4); // Part 15: kit shimmer instead of the word "Loading..."
      return Center(child: Text('Cannot reach the backend. Start it with owlon, then pull down.', style: TextStyle(color: p.textMuted)));
    }
    final building = r['building'] == true;
    final prog = r['progress'] is List ? (r['progress'] as List) : const [0, 0];
    final rows = (r['rows'] is List ? r['rows'] as List : const []).whereType<Map>().map((e) => e.cast<String, dynamic>()).where((e) => widget.query.isEmpty || '${e['symbol']}'.toUpperCase().contains(widget.query)).toList();
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(physics: const AlwaysScrollableScrollPhysics(), padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, AppSpacing.xl), children: [
        // Part 15: kit heading; the rule text is shortened (a day = 5:30 AM IST to 5:30 AM IST, one row per coin = its newest day, right side = how it is doing now).
        const OwlSectionHeader(title: '7-day movers', sub: 'top 10 gainers + losers per day, right side = now'),
        if (building) ...[
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(color: p.warning.withOpacity(0.12), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall)),
            child: Text('Building today\'s 7-day list from Binance: ${prog.isNotEmpty ? prog[0] : 0} of ${prog.length > 1 ? prog[1] : 0} coins. It takes about a minute, once a day.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
          ),
        ],
        if ('${r['error'] ?? ''}'.isNotEmpty && rows.isEmpty) ...[
          const SizedBox(height: 8),
          Text('Problem: ${r['error']}', style: TextStyle(fontSize: 12, color: p.loss)),
        ],
        const SizedBox(height: 10),
        if (rows.isEmpty && !building) const OwlEmptyState(icon: Icons.show_chart_rounded, title: 'No coin to show', sub: 'A coin appears here when it was in a daily top 10 in the last 7 days.'),
        for (final e in rows) _row(p, e),
      ]),
    );
  }

  Widget _row(AppPalette p, Map<String, dynamic> e) {
    final g = '${e['side']}' == 'G';
    final dayPct = _n(e['day_pct']);
    final hasNow = e['since_pct'] is num;
    final since = _n(e['since_pct']);
    final week = e['week_pct'] is num ? _n(e['week_pct']) : null;
    final times = (e['times'] is num) ? (e['times'] as num).toInt() : 1;
    final c = g ? p.profit : p.loss;
    return GestureDetector(
      onTap: () => showCandleChartSheet(context, '${e['symbol']}'),
      child: Container(
        margin: const EdgeInsets.only(bottom: 6),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
        child: Row(children: [
          Expanded(
            flex: 5,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Flexible(child: Text(_coin('${e['symbol']}'), maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
                  decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(4)),
                  child: Text(g ? 'GAINER' : 'LOSER', style: TextStyle(fontSize: 9, fontWeight: FontWeight.w800, color: c)),
                ),
              ]),
              const SizedBox(height: 3),
              Text('${_dayLabel('${e['day']}')}${times > 1 ? '  ·  came $times times' : ''}', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
            ]),
          ),
          Expanded(
            flex: 3,
            child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(_sg(dayPct), style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: c)),
              Text('that day', style: TextStyle(fontSize: 10, color: p.textMuted)),
            ]),
          ),
          Expanded(
            flex: 4,
            child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text(hasNow ? _sg(since) : '--', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: !hasNow ? p.textMuted : (since >= 0 ? p.profit : p.loss))),
              Text(hasNow ? 'since${week != null ? '  ·  7d ${_sg(week)}' : ''}' : 'no live price', style: TextStyle(fontSize: 10, color: p.textMuted)),
            ]),
          ),
        ]),
      ),
    );
  }
}
