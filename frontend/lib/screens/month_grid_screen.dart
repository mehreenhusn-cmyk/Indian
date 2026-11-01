import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/equity_line.dart';
import '../widgets/owl_card.dart';
import 'learning_progress_cards.dart';

/// Part M2: Month calendar (idea of mock picture 16), read-only, on the Part M2 route /api/v2/brain_month.
/// A month grid (Monday first, UTC days = the app's day): each day shows the Brain's net in USDT, green for profit, red for loss, grey for no trade. Tap a day: the Brain and the Current Bot numbers of that day (never added).
/// Above the grid: month net of the Brain and of the Current Bot (apart), best day, worst day, trades, profit days / loss days (counts, no win-rate headline), worst dip. Below: the running-net line of the month.
/// Arrows go to the previous / next month. PAPER, SHADOW and REPLAY are separate tabs. LIVE is locked. Dart NOT compiled (the APK build is the proof).
class MonthGridScreen extends StatefulWidget {
  const MonthGridScreen({super.key});

  @override
  State<MonthGridScreen> createState() => _MonthGridScreenState();
}

class _MonthGridScreenState extends State<MonthGridScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'PAPER';
  String? _month;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainMonth(_src, _month);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  String _problem(Map<String, dynamic>? r) {
    if (r != null && r['error'] != null) return '${r['error']}';
    switch (r == null ? 'error' : r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the month calendar route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _sources() => Wrap(spacing: 8, children: [
        for (final s in const ['PAPER', 'SHADOW', 'REPLAY'])
          ChoiceChip(
            label: Text(s),
            selected: _src == s,
            onSelected: (_) {
              if (_src == s) return;
              _src = s;
              _load();
            },
          ),
      ]);

  Widget _header(AppPalette p, Map<String, dynamic> r) => Row(children: [
        IconButton(
          icon: const Icon(Icons.chevron_left),
          onPressed: () {
            _month = '${r['prev']}';
            _load();
          },
        ),
        Expanded(child: Text('${r['month']}', textAlign: TextAlign.center, style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: p.textPrimary))),
        IconButton(
          icon: const Icon(Icons.chevron_right),
          onPressed: r['next'] == null
              ? null
              : () {
                  _month = '${r['next']}';
                  _load();
                },
        ),
      ]);

  Widget _kv(AppPalette p, String big, String label, [Color? c]) => Expanded(
        child: Column(children: [
          Text(big, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
          const SizedBox(height: 2),
          Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      );

  String _dayText(Map<String, dynamic>? d) => d == null ? '-' : 'day ${d['day']}';

  Widget _summary(AppPalette p, Map<String, dynamic> r) {
    final best = lpMap(r['best_day']);
    final worst = lpMap(r['worst_day']);
    final dd = lpMap(r['drawdown']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _kv(p, lpSg(r['brain_usdt']), 'Brain net USDT', lpNet(p, r['brain_usdt'])),
          _kv(p, lpSg(r['bot_usdt']), 'Current Bot net USDT', lpNet(p, r['bot_usdt'])),
          _kv(p, '${r['brain_trades'] ?? 0}', 'Brain trades'),
        ]),
        const SizedBox(height: 12),
        Row(children: [
          _kv(p, best.isEmpty ? '-' : lpSg(best['brain_usdt']), 'Best day (${_dayText(best.isEmpty ? null : best)})', best.isEmpty ? null : p.profit),
          _kv(p, worst.isEmpty ? '-' : lpSg(worst['brain_usdt']), 'Worst day (${_dayText(worst.isEmpty ? null : worst)})', worst.isEmpty ? null : p.loss),
          _kv(p, lpNum(dd['max'] ?? dd['max_usdt']).toStringAsFixed(2), 'Worst dip USDT', p.loss),
        ]),
        const SizedBox(height: 12),
        Text('${r['profit_days'] ?? 0} profit days, ${r['loss_days'] ?? 0} loss days, out of ${r['days_with_trades'] ?? 0} days with a Brain trade.', style: TextStyle(fontSize: 12, color: p.textSecondary)),
      ]),
    );
  }

  void _open(AppPalette p, Map<String, dynamic> r, Map<String, dynamic> d) {
    showModalBottomSheet<void>(
      context: context,
      builder: (_) => Padding(
        padding: const EdgeInsets.all(AppSpacing.l),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${r['month']}-${'${d['day']}'.padLeft(2, '0')} (UTC)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 10),
          Text('Owl Brain: ${lpSg(d['brain_usdt'])} USDT in ${d['brain_trades']} closed trades', style: TextStyle(fontSize: 13, color: lpNet(p, d['brain_usdt']))),
          const SizedBox(height: 4),
          Text('Current Bot: ${lpSg(d['bot_usdt'])} USDT in ${d['bot_trades']} closed trades', style: TextStyle(fontSize: 13, color: lpNet(p, d['bot_usdt']))),
          const SizedBox(height: 8),
          Text('Different trades, never added. Net of fee.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      ),
    );
  }

  Widget _tile(AppPalette p, Map<String, dynamic> r, int day, Map<String, dynamic>? d) {
    final m = d ?? <String, dynamic>{};
    final has = lpNum(m['brain_trades']) > 0 || lpNum(m['bot_trades']) > 0;
    final brain = lpNum(m['brain_trades']) > 0;
    final v = lpNum(m['brain_usdt']);
    final c = !brain ? p.textMuted : v > 0 ? p.profit : v < 0 ? p.loss : p.textMuted;
    return Expanded(
      child: GestureDetector(
        onTap: has ? () => _open(p, r, m) : null,
        child: Container(
          height: 54,
          margin: const EdgeInsets.all(2),
          decoration: BoxDecoration(color: c.withOpacity(brain ? 0.14 : 0.05), borderRadius: BorderRadius.circular(8)),
          child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
            Text('$day', style: TextStyle(fontSize: 11, color: p.textSecondary)),
            if (brain) Text(lpSg(v), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: c)),
          ]),
        ),
      ),
    );
  }

  Widget _grid(AppPalette p, Map<String, dynamic> r) {
    final byDay = {for (final d in lpList(r['days'])) (d['day'] as num).toInt(): d};
    final n = (r['days_in_month'] as num).toInt();
    final lead = (r['first_weekday'] as num).toInt();
    final cells = <Widget>[for (var i = 0; i < lead; i++) Expanded(child: Container(height: 54, margin: const EdgeInsets.all(2))), for (var d = 1; d <= n; d++) _tile(p, r, d, byDay[d])];
    while (cells.length % 7 != 0) {
      cells.add(Expanded(child: Container(height: 54, margin: const EdgeInsets.all(2))));
    }
    return OWLCard(
      child: Column(children: [
        Row(children: [
          for (final w in const ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']) Expanded(child: Text(w, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted))),
        ]),
        const SizedBox(height: 4),
        for (var i = 0; i < cells.length; i += 7) Row(children: cells.sublist(i, i + 7)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [_sources(), OWLCard(edge: p.warning, child: Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      final ok = r!;
      final pts = [for (final e in (ok['equity'] is List ? ok['equity'] as List : const [])) lpNum(e)];
      kids = [
        _sources(),
        _header(p, ok),
        _summary(p, ok),
        _grid(p, ok),
        OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Brain running net of the month', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 10),
            if (pts.length < 2) Text('Not enough days with a Brain trade for a line.', style: TextStyle(fontSize: 12.5, color: p.textMuted)) else EquityLine(values: pts, line: p.accent, grid: p.border),
          ]),
        ),
        Text('${ok['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ];
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
      ),
    );
  }
}
