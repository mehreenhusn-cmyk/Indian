import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 81 (Results 2 of 2): the Results screen. Read-only: it shows the answer of /api/v2/results (Part 80) and nothing else (no setting, no order, no file).
/// Top: the net result of the closed trades. Then two cards: "Making money" and "Losing money" (only groups with 30+ trades whose older AND newer half have the
/// same sign). Below: every list (BUY or SELL, how it ended, time of day, hold time, coin, timeframe, zone, trend) with trades, win rate and net USDT.
/// The boxes (real / live estimated / paper) are never added together: one chip per box. A group with fewer than 30 trades has no verdict. Dart NOT compiled (the
/// owner's APK build is the proof).
class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key});

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);
String _usdt(Object? v) {
  final x = _d(v);
  return '${x >= 0 ? '+' : ''}${x.toStringAsFixed(2)}';
}

class _ResultsScreenState extends State<ResultsScreen> {
  Map<String, dynamic>? _r;
  bool _busy = true;
  String? _box;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().fetchResults();
    if (!mounted) return;
    setState(() {
      _r = r;
      _busy = false;
      final order = (r['order'] is List) ? List<String>.from((r['order'] as List).map((e) => '$e')) : <String>[];
      if (_box == null || !order.contains(_box)) _box = order.isEmpty ? null : order.first;
    });
  }

  String _problem(Map<String, dynamic> r) {
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the Results route yet. Install the newest zip, restart the backend, then pull down to refresh.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Color _vColor(AppPalette p, String v) => v == 'MAKING_MONEY' ? p.profit : (v == 'LOSING' ? p.loss : p.textMuted);
  String _vText(String v) => v == 'MAKING_MONEY' ? 'MAKING MONEY' : (v == 'LOSING' ? 'LOSING' : (v == 'MIXED' ? 'MIXED' : 'TOO FEW'));

  Widget _row(AppPalette p, Map<String, dynamic> g, {String? dim}) {
    final net = _d(g['net_usdt']);
    final v = '${g['verdict']}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (dim != null) Text(dim, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
            Text('${g['label']}', style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
            Text('${g['n']} trades - win ${_d(g['win_pct']).toStringAsFixed(1)}% - avg ${_usdt(g['avg_usdt'])}',
                style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_usdt(net), style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss)),
          Text(_vText(v), style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: _vColor(p, v))),
        ]),
      ]),
    );
  }

  Widget _verdictCard(AppPalette p, String title, String empty, Color edge, List<Map<String, dynamic>> rows) {
    return OWLCard(
      edge: edge,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, title),
        if (rows.isEmpty) Text(empty, style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        for (final g in rows) _row(p, g, dim: '${g['dim']}'),
      ]),
    );
  }

  Widget _dimCard(AppPalette p, Map<String, dynamic> d) {
    final rows = _l(d['rows']);
    final unsaved = (d['not_saved'] as num?)?.toInt() ?? 0;
    final hidden = (d['hidden'] as num?)?.toInt() ?? 0;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, '${d['title']}'),
        if (rows.isEmpty) Text('Not saved in the trades yet ($unsaved trades without this field).', style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
        for (final g in rows) _row(p, g),
        if (hidden > 0) Text('$hidden more groups in the middle are hidden (best and worst are shown).', style: TextStyle(fontSize: 11, color: p.textMuted)),
        if (rows.isNotEmpty && unsaved > 0) Text('$unsaved trades did not save this field (not counted here).', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  List<Widget> _body(AppPalette p, Map<String, dynamic> r) {
    final boxes = _m(r['boxes']);
    final order = (r['order'] is List) ? List<String>.from((r['order'] as List).map((e) => '$e')) : <String>[];
    final b = _m(boxes[_box]);
    final o = _m(b['overall']);
    final net = _d(o['net_usdt']);
    return [
      if (order.length > 1)
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final k in order)
            ChoiceChip(
              label: Text(_short(k, _m(boxes[k])['title']), style: const TextStyle(fontSize: 12)),
              selected: k == _box,
              onSelected: (_) => setState(() => _box = k),
            ),
        ]),
      OWLCard(
        hasPositiveGlow: net > 0,
        hasNegativeGlow: net < 0,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('${b['title'] ?? ''}'.toUpperCase(), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: p.textMuted)),
          const SizedBox(height: 4),
          Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(_usdt(net), style: TextStyle(fontSize: 30, fontWeight: FontWeight.w800, color: net >= 0 ? p.profit : p.loss)),
            const SizedBox(width: 6),
            Padding(padding: const EdgeInsets.only(bottom: 5), child: Text('USDT net after fee', style: TextStyle(fontSize: 12, color: p.textSecondary))),
          ]),
          const SizedBox(height: 4),
          Text('${o['n']} closed trades - win rate ${_d(o['win_pct']).toStringAsFixed(1)}% - avg ${_usdt(o['avg_usdt'])} per trade',
              style: TextStyle(fontSize: 12.5, color: p.textPrimary)),
          Text('From ${b['first_close_utc']} to ${b['last_close_utc']} (UTC)', style: TextStyle(fontSize: 11, color: p.textMuted)),
          const SizedBox(height: 8),
          for (final s in (b['say'] is List ? (b['say'] as List) : const []).skip(1))
            Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('$s', style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
        ]),
      ),
      _verdictCard(p, 'Making money', 'No group has 30+ trades and profit in both halves yet. Nothing here is proven profit.', p.profit, _l(b['makes_money'])),
      _verdictCard(p, 'Losing money', 'No group is losing steadily in both halves yet.', p.loss, _l(b['loses_money'])),
      for (final d in _l(b['dims'])) _dimCard(p, d),
      Text(
          'Closed trades only, net of fee. A group needs 30+ trades and profit in BOTH halves of its history to be called MAKING MONEY. This is evidence, not an order: a group that made money before can stop.',
          style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  String _short(String k, Object? title) {
    switch (k) {
      case 'real_live':
        return 'REAL';
      case 'live_estimated':
        return 'LIVE (est.)';
      case 'paper_b2':
        return 'PAPER Bot 2';
      default:
        return 'PAPER';
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = _r;
    final List<Widget> kids;
    if (_busy && r == null) {
      kids = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    } else if (r == null || r['ready'] != true) {
      kids = [OWLCard(edge: p.warning, child: Text(r != null && r['ready'] == false ? '${r['note'] ?? 'Not ready.'}' : _problem(r ?? <String, dynamic>{'state': 'error'}), style: TextStyle(fontSize: 13, color: p.textPrimary)))];
    } else if (_box == null) {
      kids = [OWLCard(child: Text('${r['note'] ?? 'No closed trades found yet.'}', style: TextStyle(fontSize: 13, color: p.textPrimary)))];
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
