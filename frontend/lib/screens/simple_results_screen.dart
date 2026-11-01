import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/equity_line.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_route.dart';
import 'results_screen.dart';

/// Part 91b (Simple Results): read-only, on the Part 91a route /api/v2/brain_verdict.
/// ONE verdict word + one sentence, the net result, four small numbers (closed trades, wins / losses, worst dip, losing streak), the equity line and the plain USE / STOP lines.
/// The old long Results screen (Part 81) is behind the "Show details" button. Tabs PAPER / SHADOW / REPLAY are never added together; LIVE is locked and has no tab.
/// Nothing here trades, saves or switches anything. Dart NOT compiled (the APK build is the proof).
class SimpleResultsScreen extends StatefulWidget {
  const SimpleResultsScreen({super.key});

  @override
  State<SimpleResultsScreen> createState() => _SimpleResultsScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : 0.0;
String _sg(Object? v) => '${_d(v) >= 0 ? '+' : ''}${_d(v).toStringAsFixed(2)}';

class _SimpleResultsScreenState extends State<SimpleResultsScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String _src = 'PAPER';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchBrainVerdict(_src);
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return '${r['error']}';
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Simple Results route yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  Widget _msg(AppPalette p, Map<String, dynamic>? r) {
    final note = r != null && r['ready'] == false && r['note'] != null ? '${r['note']}' : _problem(r ?? <String, dynamic>{'state': 'error'});
    return OWLCard(edge: p.warning, child: Text(note, style: TextStyle(fontSize: 13, color: p.textPrimary)));
  }

  Color _wordColor(AppPalette p, String w) => w == 'PROFIT' ? p.profit : w == 'LOSS' ? p.loss : p.warning;

  Widget _tabs(AppPalette p, Map<String, dynamic> r) {
    final tabs = _l(r['tabs']);
    return Wrap(spacing: 8, children: [
      for (final t in tabs)
        ChoiceChip(
          label: Text('${t['source']} (${t['closed'] ?? 0})'),
          selected: _src == t['source'],
          onSelected: (_) {
            if (_src == t['source']) return;
            _src = '${t['source']}';
            _load();
          },
        ),
    ]);
  }

  Widget _verdict(AppPalette p, Map<String, dynamic> r) {
    final v = _m(r['verdict']);
    final n = _m(r['numbers']);
    final w = '${v['word']}';
    final c = _wordColor(p, w);
    final net = _d(n['net_usdt']);
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Net result', style: TextStyle(fontSize: 13, color: p.textSecondary)),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_sg(net), style: TextStyle(fontSize: 38, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss)),
          Padding(padding: const EdgeInsets.only(left: 6, bottom: 6), child: Text('USDT', style: TextStyle(fontSize: 14, color: p.textMuted))),
        ]),
        Text('${_sg(n['avg_usdt'])} per trade  |  today ${_sg(n['today_usdt'])}  |  7 days ${_sg(n['week_usdt'])}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 12),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
          decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
          child: Text(w, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: c)),
        ),
        const SizedBox(height: 8),
        Text('${v['text'] ?? ''}', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
      ]),
    );
  }

  Widget _stat(AppPalette p, String big, String label, [Color? c]) => Expanded(
        child: Column(children: [
          Text(big, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: c ?? p.textPrimary)),
          const SizedBox(height: 2),
          Text(label, textAlign: TextAlign.center, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        ]),
      );

  Widget _numbers(AppPalette p, Map<String, dynamic> r) {
    final n = _m(r['numbers']);
    final k = _m(r['risk']);
    final dd = _m(k['drawdown']);
    final st = _m(k['streak']);
    return OWLCard(
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _stat(p, '${n['trades'] ?? 0}', 'Closed trades'),
        _stat(p, '${n['wins'] ?? 0} / ${n['losses'] ?? 0}', 'Wins / losses'),
        _stat(p, '-${_d(dd['max_usdt']).toStringAsFixed(2)}', 'Worst dip (USDT)', p.warning),
        _stat(p, '${st['longest'] ?? 0}', 'Longest losing streak (now ${st['current'] ?? 0})'),
      ]),
    );
  }

  Widget _equity(AppPalette p, Map<String, dynamic> r) {
    final pts = [for (final e in _l(r['equity'])) _d(e['v'])];
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Equity curve (USDT)', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text('Running net after each closed trade.', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 10),
        if (pts.length < 2)
          Text('No closed trades yet.', style: TextStyle(fontSize: 12.5, color: p.textMuted))
        else
          EquityLine(values: pts, line: p.accent, grid: p.border),
      ]),
    );
  }

  Widget _lines(AppPalette p, String title, String sub, List<dynamic> xs, Color c) {
    return OWLCard(
      edge: xs.isEmpty ? null : c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
        Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 8),
        if (xs.isEmpty) Text('Nothing yet. A line needs 30+ trades and the same sign in both halves.', style: TextStyle(fontSize: 12.5, color: p.textMuted)),
        for (final x in xs) Padding(padding: const EdgeInsets.only(bottom: 6), child: Text('$x', style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
      ]),
    );
  }

  void _details() {
    final p = context.palette;
    Navigator.of(context).push(OwlRoute(
      builder: (_) => Scaffold(
        backgroundColor: p.bg,
        appBar: AppBar(backgroundColor: p.bg, elevation: 0, title: Text('Results details', style: context.type.section.copyWith(fontWeight: FontWeight.w700))),
        body: const ResultsScreen(),
      ),
    ));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (_bad(r)) {
      kids = [_msg(p, r)];
    } else {
      kids = [
        _tabs(p, r!),
        _verdict(p, r),
        _numbers(p, r),
        _equity(p, r),
        _lines(p, 'USE', 'Groups that made money in both halves of their history', (r['use'] as List?) ?? const [], p.profit),
        _lines(p, 'STOP', 'Groups that lost money in both halves of their history', (r['stop'] as List?) ?? const [], p.loss),
        OutlinedButton(onPressed: _details, child: const Text('Show details')),
        Text('${r['note'] ?? ''}', style: TextStyle(fontSize: 11, color: p.textMuted)),
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
