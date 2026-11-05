import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_active.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';
import 'owl_pressable.dart';
import 'stat_tile.dart';

/// R28b (Part 9): SNIPER TODAY and SNIPER 7 DAYS on the Dashboard, two plain text tabs (owner rule 31).
/// Data: GET /api/v2/sniper_days (closed Sniper PAPER trades; a day starts 5:30 AM IST = 00:00 UTC; BTC never counted; read every 30 s).
/// Shown: one big net number, 4 tiles (trades, win rate, profit, loss), best / worst trade, lanes, best + worst coins, most frequent exit reasons and mistake tags.
/// The 7 Days tab adds seven day bars. Never added to the Current Bot, Dual or Brain numbers. n = 0 shows a plain line, no made-up number. Read only. Dart NOT compiled.
double _n(Object? v) => v is num ? v.toDouble() : 0.0;
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];

class SniperDaysCard extends StatefulWidget {
  const SniperDaysCard({super.key});

  @override
  State<SniperDaysCard> createState() => _SniperDaysCardState();
}

class _SniperDaysCardState extends State<SniperDaysCard> {
  Map<String, dynamic>? _data;
  Timer? _timer;
  int _tab = 0; // 0 = Today, 1 = 7 Days

  @override
  void initState() {
    super.initState();
    _data = ScreenCache.get('sniper_days'); // Part 14: last good block at once, refresh quietly
    _load();
    _timer = AppActive.every(const Duration(seconds: 30), _load);
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchSniperDays();
    if (mounted) setState(() => _data = ScreenCache.put('sniper_days', r) ? r : (_data ?? r));
  }

  String _tone(double v) => v > 0 ? 'good' : (v < 0 ? 'bad' : '');

  Widget _tab_(BuildContext context, int i, String name) {
    final p = context.palette;
    final on = i == _tab;
    return Padding(
      padding: const EdgeInsets.only(right: AppSpacing.xl),
      child: OWLPressable(
        pressedScale: 0.97,
        onTap: () => setState(() => _tab = i),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text(name, style: context.type.primary.copyWith(fontSize: 15, fontWeight: on ? FontWeight.w700 : FontWeight.w500, color: on ? p.textPrimary : p.textMuted)),
          const SizedBox(height: 4),
          Container(height: 2.5, width: 22, decoration: BoxDecoration(color: on ? p.textPrimary : Colors.transparent, borderRadius: BorderRadius.circular(2))),
        ]),
      ),
    );
  }

  Widget _bars(BuildContext context, List<dynamic> days) {
    final p = context.palette;
    var mx = 0.0;
    for (final d in days) {
      final v = _n(_m(d)['net']).abs();
      if (v > mx) mx = v;
    }
    return Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
      for (final d in days)
        Expanded(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            SizedBox(
              height: 44,
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Container(
                  width: 14,
                  height: _m(d)['n'] == 0 || mx == 0 ? 2 : (4 + 40 * _n(_m(d)['net']).abs() / mx),
                  decoration: BoxDecoration(color: _n(_m(d)['net']) >= 0 ? p.profit : p.loss, borderRadius: BorderRadius.circular(3)),
                ),
              ),
            ),
            const SizedBox(height: 3),
            Text(fmtSigned(_n(_m(d)['net']), 1), maxLines: 1, style: context.type.metadata.copyWith(fontSize: 11)),
            Text('${_m(d)['label'] ?? ''}'.split(' ').first, maxLines: 1, style: context.type.metadata.copyWith(fontSize: 11)),
          ]),
        ),
    ]);
  }

  String _coins(List<dynamic> l) => l.map((c) => '${_m(c)['symbol']} ${fmtSigned(_n(_m(c)['net']), 1)}').join('  ');

  Widget _line(BuildContext context, String k, String v) {
    if (v.trim().isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 92, child: Text(k, style: context.type.label)),
        Expanded(child: Text(v, style: context.type.metadata)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final b = _m(d == null ? null : d[_tab == 0 ? 'today' : 'week']);
    final n = _n(b['n']).round();
    final net = _n(b['net']);
    final state = d == null ? '' : '${d['state'] ?? ''}';
    final lanes = _m(b['lanes']);
    final laneTxt = lanes.entries.map((e) => '${e.key} ${_m(e.value)['n']} trades, ${fmtSigned(_n(_m(e.value)['net']))}').join('   ');
    final exits = _l(b['exits']).map((e) => '${_m(e)['reason']} x${_m(e)['n']}').join(', ');
    final tags = _l(b['tags']).map((e) => '${_m(e)['tag']} x${_m(e)['n']}').join(', ');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.l),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [_tab_(context, 0, 'Sniper Today'), _tab_(context, 1, 'Sniper 7 Days')]),
        const SizedBox(height: AppSpacing.s),
        if (d == null)
          Text('Loading...', style: context.type.metadata)
        else if (state == 'off' || state == 'old' || state == 'error')
          Text(state == 'off' ? 'The Sniper is switched off.' : 'Sniper results are not available from this backend yet (update the backend).', style: context.type.metadata)
        else ...[
          Text(_tab == 0 ? 'Paper trades closed today (day starts 5:30 AM IST)' : 'Paper trades closed in the last 7 days', style: context.type.label),
          const SizedBox(height: 4),
          if (n == 0)
            Text('${b['text'] ?? 'No closed Sniper trade in this window yet.'}', style: context.type.metadata)
          else ...[
            FittedBox(
              fit: BoxFit.scaleDown,
              alignment: Alignment.centerLeft,
              child: Text('${fmtSigned(net)} USDT', maxLines: 1, style: context.type.number.copyWith(fontSize: 32, fontWeight: FontWeight.w800, color: net > 0 ? p.profit : (net < 0 ? p.loss : p.textPrimary))),
            ),
            const SizedBox(height: AppSpacing.m),
            Row(children: [
              Expanded(child: StatTile(label: 'Trades', value: '$n', sub: '${_n(b['wins']).round()} win, ${_n(b['losses']).round()} loss')),
              const SizedBox(width: AppSpacing.s),
              Expanded(child: StatTile(label: 'Win rate', value: '${_n(b['win_pct']).toStringAsFixed(1)}%')),
            ]),
            const SizedBox(height: AppSpacing.s),
            Row(children: [
              Expanded(child: StatTile(label: 'Profit', value: fmtSigned(_n(b['profit'])), tone: _tone(_n(b['profit'])))),
              const SizedBox(width: AppSpacing.s),
              Expanded(child: StatTile(label: 'Loss', value: fmtSigned(_n(b['loss'])), tone: _tone(_n(b['loss'])))),
            ]),
            if (_tab == 1 && _l(d['days']).isNotEmpty) ...[const SizedBox(height: AppSpacing.m), _bars(context, _l(d['days']))],
            const SizedBox(height: AppSpacing.s),
            _line(context, 'Best / worst', '${fmtSigned(_n(b['best']))} / ${fmtSigned(_n(b['worst']))}   avg ${fmtSigned(_n(b['avg']))}'),
            _line(context, 'Lanes', laneTxt),
            _line(context, 'Best coins', _coins(_l(b['coins_top']))),
            _line(context, 'Worst coins', _coins(_l(b['coins_worst']))),
            _line(context, 'Exits', exits),
            _line(context, 'Mistakes', tags),
          ],
          const SizedBox(height: AppSpacing.s),
          Text('Paper money only. BTC is not counted. Not added to Current Bot, Dual or Brain.', style: context.type.metadata.copyWith(fontSize: 11)),
        ],
      ]),
    );
  }
}
