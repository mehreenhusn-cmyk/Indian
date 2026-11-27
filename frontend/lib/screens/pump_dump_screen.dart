import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_active.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/pd_cool_widgets.dart';
import '../widgets/pd_learning_card.dart';
import '../widgets/pd_movers_widgets.dart';
import '../widgets/pd_pre_widgets.dart';
import '../widgets/pd_widgets.dart';

/// PUMP / DUMP tab (26 Nov 2026). Coins that start to pump (left, green) or dump (right, red), found by the scanner on this phone
/// (backend/pd_*.py). Signals show ONLY here: no Telegram. Top = coins in play right now; below = day by day (IST), newest first,
/// each START with its checked result (REAL / FAKE after 15 / 30 / 60 min); at the bottom what the scanner learned.
/// The screen asks the phone every 5 s only while it is open and the app is in front; leaving the tab stops it. Dart NOT compiled in the sandbox.
class PumpDumpScreen extends StatefulWidget {
  const PumpDumpScreen({super.key});

  @override
  State<PumpDumpScreen> createState() => _PumpDumpScreenState();
}

class _PumpDumpScreenState extends State<PumpDumpScreen> {
  static Map<String, dynamic>? _lastLive; // kept for the whole run: coming back to the tab shows the old numbers at once
  static Map<String, dynamic>? _lastMovers; // Round 1
  static Map<String, dynamic>? _lastPre; // Round 2
  static Map<String, dynamic>? _lastCool; // Part 4
  static Map<String, dynamic>? _lastDay;
  static String _lastDayKey = '';

  Map<String, dynamic>? _live = _lastLive;
  Map<String, dynamic>? _movers = _lastMovers;
  Map<String, dynamic>? _pre = _lastPre;
  Map<String, dynamic>? _cool = _lastCool;
  Map<String, dynamic>? _day = _lastDay;
  String _dayKey = _lastDayKey; // '' = today
  bool _onlyStart = true; // Round C: by default only the moves that reached START (hints that faded are one tap away)
  bool _busy = false;
  int _tick = 0;
  Timer? _timer;
  AppProvider? _prov;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _prov = context.read<AppProvider>();
      _prov!.pdSetOnTab(true);
      _refresh(true);
    });
    _timer = AppActive.every(const Duration(seconds: 5), () => _refresh(false));
  }

  @override
  void dispose() {
    _timer?.cancel();
    _prov?.pdSetOnTab(false);
    super.dispose();
  }

  bool _bad(Map<String, dynamic>? m) => m == null || m['state'] != null;

  Future<void> _refresh(bool withDay) async {
    if (_busy || !mounted) return;
    _busy = true;
    try {
      final prov = context.read<AppProvider>();
      final live = await prov.fetchPdLive();
      final movers = await prov.fetchPdMovers();
      final pre = await prov.fetchPdPre();
      final cool = await prov.fetchPdCool();
      Map<String, dynamic>? day;
      _tick++;
      if (withDay || _day == null || _tick % 4 == 0) day = await prov.fetchPdDay(_dayKey);
      if (!mounted) return;
      setState(() {
        _live = live;
        _lastLive = live;
        _movers = movers;
        _lastMovers = movers;
        _pre = pre;
        _lastPre = pre;
        _cool = cool;
        _lastCool = cool;
        if (day != null && !_bad(day)) {
          _day = day;
          _lastDay = day;
          _lastDayKey = _dayKey;
        }
      });
    } finally {
      _busy = false;
    }
  }

  Future<void> _pickDay(String d, String today) async {
    setState(() {
      _dayKey = d == today ? '' : d;
      _lastDayKey = _dayKey;
    });
    final day = await context.read<AppProvider>().fetchPdDay(_dayKey);
    if (!mounted) return;
    setState(() {
      if (!_bad(day)) {
        _day = day;
        _lastDay = day;
      }
    });
  }

  Future<void> _switch(bool on) async {
    final ok = await context.read<AppProvider>().setPdSwitch(enabled: on);
    if (!mounted) return;
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not change the switch (is the backend running?)')));
      return;
    }
    _refresh(false);
  }

  // ------------------------------------------------------------------ pieces
  Widget _card(AppPalette p, Widget child) => Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
        child: child,
      );

  Widget _heading(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(top: 4, bottom: 8),
        child: Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
          Text(t, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) ...[
            const SizedBox(width: 8),
            Expanded(child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
          ],
        ]),
      );

  Widget _status(AppPalette p, Map<String, dynamic> l) {
    final enabled = l['enabled'] != false;
    final warm = pdNum(l['warm_left_min']);
    final age = l['last_poll_age'];
    final err = '${l['last_error'] ?? ''}';
    String line;
    Color dot;
    if (!enabled) {
      line = 'Switched off: no data is used';
      dot = p.textMuted;
    } else if (err.isNotEmpty) {
      line = 'No connection to Binance: $err';
      dot = p.warning;
    } else if (age == null) {
      line = 'Starting... first check in a few seconds';
      dot = p.warning;
    } else if (warm > 0) {
      line = 'Warming up: ${warm.toStringAsFixed(0)} min left, it needs a little history before it can judge volume';
      dot = p.warning;
    } else {
      line = 'Live  ·  checked ${pdNum(age).toStringAsFixed(0)}s ago  ·  ${l['tracked']} coins watched';
      dot = p.profit;
    }
    final np = l['pump'] is List ? (l['pump'] as List).length : 0;
    final nd = l['dump'] is List ? (l['dump'] as List).length : 0;
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration( // Round F2: status header with a soft tint of the scanner state
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [dot.withOpacity(0.16), p.surface]),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: dot.withOpacity(0.4)),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.14), blurRadius: 8, offset: const Offset(0, 3))],
      ),
      child: Column(children: [
      Row(children: [
        Container(width: 9, height: 9, decoration: BoxDecoration(color: dot, shape: BoxShape.circle, boxShadow: [BoxShadow(color: dot.withOpacity(0.7), blurRadius: 6)])),
        const SizedBox(width: 10),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Pump / Dump scanner', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 2),
            Text(line, style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          ]),
        ),
        Switch(value: enabled, onChanged: _switch),
      ]),
      if (enabled) ...[
        const SizedBox(height: 8),
        Row(children: [
          _countChip(p, 'Pump', np, p.profit, Icons.trending_up_rounded),
          const SizedBox(width: 8),
          _countChip(p, 'Dump', nd, p.loss, Icons.trending_down_rounded),
        ]),
      ],
      ]),
    );
  }

  /// Round F2: a small pill with the number of coins in play on one side.
  Widget _countChip(AppPalette p, String label, int n, Color c, IconData icon) => Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
          decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall)),
          child: Row(children: [
            Icon(icon, size: 16, color: c),
            const SizedBox(width: 6),
            Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: c)),
            const Spacer(),
            Text('$n', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          ]),
        ),
      );

  List<Widget> _liveTiles(List<dynamic> rows, bool pump) => [
        for (final r in rows) if (r is Map<String, dynamic>) PdLiveTile(row: r, pump: pump),
      ];

  Widget _dayChips(AppPalette p, Map<String, dynamic> d) {
    final days = d['days'] is List ? d['days'] as List : <dynamic>[];
    final today = '${d['today']}';
    final sel = '${d['day']}';
    if (days.isEmpty) return const SizedBox.shrink();
    return SizedBox(
      height: 54,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: days.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (_, i) {
          final m = days[i] as Map;
          final key = '${m['day']}';
          final on = key == sel;
          final pump = m['pump'] is Map ? m['pump'] as Map : <dynamic, dynamic>{};
          final dump = m['dump'] is Map ? m['dump'] as Map : <dynamic, dynamic>{};
          final label = key == today ? 'Today' : key.substring(5).replaceAll('-', '/');
          return GestureDetector(
            onTap: () => _pickDay(key, today),
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: on ? p.accent.withOpacity(0.16) : p.surface,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: on ? p.accent : p.border),
              ),
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(label, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: on ? p.accent : p.textPrimary)),
                const SizedBox(height: 2),
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Text('▲${pump['starts'] ?? 0}', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: p.profit)),
                  const SizedBox(width: 6),
                  Text('▼${dump['starts'] ?? 0}', style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: p.loss)),
                ]),
              ]),
            ),
          );
        },
      ),
    );
  }

  String _sideLine(Map<String, dynamic> d, String side) {
    final days = d['days'] is List ? d['days'] as List : <dynamic>[];
    for (final e in days) {
      if (e is Map && '${e['day']}' == '${d['day']}') {
        final s = e[side] is Map ? e[side] as Map : <dynamic, dynamic>{};
        final chk = pdNum(s['checked']);
        final real = pdNum(s['real']);
        final rate = chk > 0 ? ' · ${(real / chk * 100).toStringAsFixed(0)}% real' : '';
        return '${s['starts'] ?? 0} starts$rate';
      }
    }
    return '';
  }

  List<Widget> _eventTiles(List<dynamic> rows, bool pump) {
    final out = <Widget>[];
    for (final r in rows) {
      if (r is! Map<String, dynamic>) continue;
      if (_onlyStart && r['started'] != true) continue;   // Round C: a card is one coin move; 'main alerts' = the moves that reached START
      out.add(PdEpisodeTile(e: r, pump: pump));
      if (out.length >= 80) break;
    }
    return out;
  }

  Widget _message(AppPalette p, String title, String body) => _card(
        p,
        Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 6),
          Text(body, style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final live = _live;
    final pad = const EdgeInsets.fromLTRB(AppSpacing.screenPad, 8, AppSpacing.screenPad, 24);
    if (live == null) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_bad(live)) {
      final old = live['state'] == 'old';
      return ListView(padding: pad, children: [
        _message(
          p,
          old ? 'The scanner is not on this backend yet' : 'Cannot reach the backend',
          old ? 'The backend on this phone has no Pump/Dump scanner. Update the repo, then restart it (owloff, then owlon).' : 'Start it with owlon in Termux, then pull down to retry.',
        ),
      ]);
    }
    final pumpRows = live['pump'] is List ? live['pump'] as List : <dynamic>[];
    final dumpRows = live['dump'] is List ? live['dump'] as List : <dynamic>[];
    final d = _day;
    return RefreshIndicator(
      onRefresh: () => _refresh(true),
      child: ListView(padding: pad, physics: const AlwaysScrollableScrollPhysics(), children: [
        _status(p, live),
        const SizedBox(height: 14),
        PdMoversSection(data: _movers), // Round 1: Naye movers + Pehle se chal rahe hain, above "Right now"
        const SizedBox(height: 18),
        PdPreSection(data: _pre), // Round 2: Taiyari me (pre-pump / pre-dump)
        const SizedBox(height: 18),
        PdCoolSection(data: _cool), // Part 4: Cooling watch (pump, sideways, dump)
        const SizedBox(height: 18),
        _heading(p, 'Right now', 'coins in play, max 5 per side'),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: PdSideColumn(pump: true, count: pumpRows.length, children: _liveTiles(pumpRows, true))),
          const SizedBox(width: 8),
          Expanded(child: PdSideColumn(pump: false, count: dumpRows.length, children: _liveTiles(dumpRows, false))),
        ]),
        const SizedBox(height: 18),
        _heading(p, 'Day by day', 'IST, one card per coin move'),
        if (d == null)
          const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator()))
        else ...[
          _dayChips(p, d),
          const SizedBox(height: 10),
          Row(children: [
            Expanded(child: Text(_sideLine(d, 'pump'), style: TextStyle(fontSize: 11.5, color: p.profit))),
            Expanded(child: Text(_sideLine(d, 'dump'), textAlign: TextAlign.right, style: TextStyle(fontSize: 11.5, color: p.loss))),
          ]),
          const SizedBox(height: 6),
          Row(children: [
            GestureDetector(
              onTap: () => setState(() => _onlyStart = !_onlyStart),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: _onlyStart ? p.accent.withOpacity(0.16) : Colors.transparent,
                  borderRadius: BorderRadius.circular(16),
                  border: Border.all(color: _onlyStart ? p.accent : p.border),
                ),
                child: Text(_onlyStart ? 'Main alerts only' : 'All incl. hints', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: _onlyStart ? p.accent : p.textSecondary)),
              ),
            ),
            const Spacer(),
            if ((d['missed'] ?? 0) != 0) Text('${d['missed']} missed moves', style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
          const SizedBox(height: 10),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Builder(builder: (_) {
              final t = _eventTiles(d['pump'] is List ? d['pump'] as List : <dynamic>[], true);
              return PdSideColumn(pump: true, count: t.length, children: t, emptyText: 'No pump alerts');
            })),
            const SizedBox(width: 8),
            Expanded(child: Builder(builder: (_) {
              final t = _eventTiles(d['dump'] is List ? d['dump'] as List : <dynamic>[], false);
              return PdSideColumn(pump: false, count: t.length, children: t, emptyText: 'No dump alerts');
            })),
          ]),
        ],
        const SizedBox(height: 18),
        const PdLearningCard(),
        const SizedBox(height: 10),
        Text('An alert is a heads-up to open the chart, not a buy or sell order. Some alerts will be fake. Alerts show only here, never on Telegram.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}
