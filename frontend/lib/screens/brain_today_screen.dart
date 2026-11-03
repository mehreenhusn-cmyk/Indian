import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import 'bt_signal_screen.dart';
import 'bt_trade_screen.dart';

/// Part 86b (Brain Trader Today page): read-only. It shows the answer of /api/v2/brain_today (Part 86a) and, when a coin is tapped (or typed), the CURRENT chart of that coin in plain
/// sentences from /api/v2/brain_chart: price vs EMA50, TSI vs its zero line and signal line, the histogram (red storm = RED and growing), Z vs zero and Z-SMA, and where they clash.
/// Top: net result of today's PAPER trades. Then the plain report lines, the newest answer of the Brain per coin, and why some coins have no data. No setting, no order, LIVE is locked.
/// Words only, never advice. Dart NOT compiled (the owner's APK build is the proof).
class BrainTodayScreen extends StatefulWidget {
  const BrainTodayScreen({super.key});

  @override
  State<BrainTodayScreen> createState() => _BrainTodayScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
List<String> _s(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
double _d(Object? v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);
String _usdt(Object? v) {
  final x = _d(v);
  return '${x >= 0 ? '+' : ''}${x.toStringAsFixed(2)}';
}

class _BrainTodayScreenState extends State<BrainTodayScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  final _coin = TextEditingController();

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _coin.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainToday();
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Brain Today route yet. Install the newest zip, restart the backend, then pull down to refresh.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Color _decColor(AppPalette p, String d) => d.startsWith('OPEN') ? p.profit : (d == 'WAIT' ? p.warning : p.textMuted);

  Color _stormColor(AppPalette p, String s) => s.startsWith('RED') ? p.loss : (s.startsWith('GREEN') ? p.profit : p.textMuted);

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(right: 6, top: 4),
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
        child: Text(t, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Future<void> _openChart(String symbol, [String interval = '5m']) async {
    final sym = symbol.trim().toUpperCase();
    if (sym.isEmpty) return;
    final f = context.read<AppProvider>().fetchBrainChart(sym, interval);
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (ctx) => FutureBuilder<Map<String, dynamic>>(
        future: f,
        builder: (c, snap) {
          final p = c.palette;
          final r = snap.data;
          Widget body;
          if (r == null) {
            body = const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()));
          } else if (r['state'] != null) {
            body = Text(_problem(r), style: TextStyle(fontSize: 13, color: p.textPrimary));
          } else if (r['error'] != null) {
            body = Text('${r['error']}', style: TextStyle(fontSize: 13, color: p.textPrimary));
          } else {
            final x = _m(r['chart']);
            final b = _m(r['brain']);
            body = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('$sym  $interval', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: p.textPrimary)),
              if (r['ready'] == true) Text('Newest closed candle ends ${r['candle_time']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
              const SizedBox(height: 6),
              if (r['ready'] == true)
                Wrap(children: [
                  _chip('${_m(r['tags'])['market_state']}', p.accent),
                  _chip('${b['decision']}', _decColor(p, '${b['decision']}')),
                  if (x['storm'] != null) _chip('${x['storm']}'.replaceAll('_', ' '), _stormColor(p, '${x['storm']}')),
                ])
              else
                _chip('NO DATA', p.warning),
              const SizedBox(height: 8),
              for (final line in _s(r['lines'])) Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(line, style: TextStyle(fontSize: 13, color: line.startsWith('Note:') ? p.warning : p.textPrimary))),
              Text('Words only, nothing is saved and no order is sent.', style: TextStyle(fontSize: 11, color: p.textMuted)),
            ]);
          }
          return SafeArea(child: Padding(padding: const EdgeInsets.fromLTRB(20, 0, 20, 20), child: SingleChildScrollView(child: body)));
        },
      ),
    );
  }

  Widget _coinRow(AppPalette p, Map<String, dynamic> c) {
    final clash = _s(c['clash']);
    return InkWell(
      onTap: () => BtSignalScreen.open(context, '${c['symbol']}', '${c['interval'] ?? '5m'}'),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('${c['symbol']}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
              Text('${c['state']} - ${c['time']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
              Wrap(children: [
                if (c['storm'] != null) _chip('${c['storm']}'.replaceAll('_', ' '), _stormColor(p, '${c['storm']}')),
                if (c['tsi_vs_zero'] != null) _chip('TSI ${'${c['tsi_vs_zero']}'.replaceAll('_', ' ').toLowerCase()}', p.textSecondary),
                if (clash.isNotEmpty) _chip('${clash.length} clash', p.warning),
              ]),
            ]),
          ),
          Text('${c['decision']}'.replaceAll('_', ' '), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: _decColor(p, '${c['decision']}'))),
          Icon(Icons.chevron_right, size: 18, color: p.textMuted),
        ]),
      ),
    );
  }

  List<Widget> _body(AppPalette p, Map<String, dynamic> r) {
    final t = _m(r['trades']);
    final net = _d(t['net_usdt']);
    final coins = _l(r['coins']);
    final noData = _l(r['no_data']);
    final waits = _m(r['waits']);
    final openPos = _l(r['open_positions']);
    final lines = _s(r['lines']);
    return [
      OWLCard(
        hasPositiveGlow: net > 0,
        hasNegativeGlow: net < 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('TODAY - PAPER (PRETEND MONEY)', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.textMuted)),
          const SizedBox(height: 4),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(_usdt(net), style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss)),
            const SizedBox(width: 6),
            Padding(padding: const EdgeInsets.only(bottom: 5), child: Text('USDT net after fee', style: TextStyle(fontSize: 12, color: p.textSecondary))),
          ]),
          Text('${t['opened'] ?? 0} opened - ${t['closed'] ?? 0} closed - ${openPos.length} open now', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
          Text('WAIT answers: ${waits['CAME'] ?? 0} came, ${waits['DROPPED'] ?? 0} dropped, ${waits['PENDING'] ?? 0} pending', style: TextStyle(fontSize: 12, color: p.textSecondary)),
          const SizedBox(height: 4),
          Text('LIVE is locked. Too few trades = no USE / AVOID verdict yet (see Results).', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Read a coin chart now', 'Type a coin, e.g. BTCUSDT: the Brain reads the chart in plain words'),
          Row(children: [
            Expanded(child: TextField(controller: _coin, textCapitalization: TextCapitalization.characters, decoration: const InputDecoration(hintText: 'BTCUSDT', isDense: true), onSubmitted: _openChart)),
            const SizedBox(width: 8),
            FilledButton(onPressed: () => _openChart(_coin.text), child: const Text('Read')),
          ]),
        ]),
      ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'What the Brain did today'),
          if (lines.isEmpty) Text('Nothing yet.', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
          for (final s in lines) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(s, style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
        ]),
      ),
      if (openPos.isNotEmpty)
        OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'Open paper trades', 'Tap one: chart, profit now, why still in'),
            for (final o in openPos)
              InkWell(
                onTap: () => BtTradeScreen.open(context, '${o['symbol']}', '${o['interval'] ?? '5m'}'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 6),
                  child: Row(children: [
                    Expanded(child: Text('${o['symbol']}  ${o['side']}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
                    Text('open ${o['age']}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                    Icon(Icons.chevron_right, size: 18, color: p.textMuted),
                  ]),
                ),
              ),
          ]),
        ),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Coins - newest answer', 'Tap a coin: Signal Detail with chart, reason and evidence'),
          if (coins.isEmpty) Text('No coin answered yet. The Brain needs about 399 candles of one gap-free run per coin.', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
          for (final c in coins) _coinRow(p, c),
        ]),
      ),
      if (noData.isNotEmpty)
        OWLCard(
          edge: p.warning,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            _title(p, 'No data - and why'),
            for (final n in noData)
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('${n['symbol']}: ${n['text']}', style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
              ),
          ]),
        ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (r == null || r['ready'] != true) {
      kids = [OWLCard(edge: p.warning, child: Text(r != null && r['ready'] == false ? '${(_s(r['lines']).isNotEmpty ? _s(r['lines']).first : r['note']) ?? 'Not ready.'}' : _problem(r ?? <String, dynamic>{'state': 'error'}), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else {
      kids = _body(p, r);
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
