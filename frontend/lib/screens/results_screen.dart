import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/verdict_card.dart';
import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/stat_tile.dart';
import '../widgets/verdict_header_card.dart';

/// Round 9 (Results, rebuilt on the UI rules of PLAN_400.md). Read-only: /api/v2/results (groups) + /api/v2/verdicts (the "results" card). No setting, no order, no file.
/// Answer first: the verdict header, then ONE hero row (net after fee for the whole period, trades, win rate, average), each number printed once (rules 1, 2, 6).
/// "Making money" / "Losing money" show only groups KNOWN AT ENTRY; a group known only after the trade ended (how it ended, how long it was open) is grey diagnosis,
/// folded away, never green (rule 3). Empty cards collapse to one line (rule 4); long lists sit behind one tap (rule 7); no "None" text (rule 9).
/// The boxes (real / live estimated / paper) are never added together: one chip per box. Dart NOT compiled (the APK build is the proof).
class ResultsScreen extends StatefulWidget {
  const ResultsScreen({super.key});

  @override
  State<ResultsScreen> createState() => _ResultsScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double _d(Object? v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);
int _i(Object? v) => v is num ? v.toInt() : (int.tryParse('$v') ?? 0);
String _usdt(Object? v) {
  final x = _d(v);
  return '${x >= 0 ? '+' : ''}${x.toStringAsFixed(2)}';
}

/// Known only AFTER the trade ended: how it ended (TP / SL / TSL / REVERSED) and how long it was open. Never a filter, never "making money".
const Set<String> _diagKeys = {'exit', 'hold'};
const Set<String> _diagTitles = {'How the trade ended', 'How long it was open'};

class _ResultsScreenState extends State<ResultsScreen> {
  Map<String, dynamic>? _r;
  VerdictCard? _vc;
  bool _busy = true;
  String? _box;
  bool _showEntry = false;
  bool _showDiag = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final prov = context.read<AppProvider>();
    final res = await Future.wait([prov.fetchResults(), prov.fetchVerdicts()]);
    if (!mounted) return;
    final r = res[0];
    VerdictCard? vc;
    for (final c in VerdictCard.listFrom(res[1]['cards'])) {
      if (c.id == 'results') vc = c;
    }
    setState(() {
      _r = r;
      _vc = vc;
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

  String _short(String k) {
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

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.primary.copyWith(fontSize: 14.5, fontWeight: FontWeight.w800)),
          if (sub != null) Text(sub, style: context.type.metadata),
        ]),
      );

  Color _vColor(AppPalette p, String v) => v == 'MAKING_MONEY' ? p.profit : (v == 'LOSING' ? p.loss : p.textMuted);
  String _vText(String v) => v == 'MAKING_MONEY' ? 'MAKING MONEY' : (v == 'LOSING' ? 'LOSING' : (v == 'MIXED' ? 'MIXED' : 'TOO FEW'));

  /// diag = grey: no green / red net, no verdict word (a diagnosis group is never a verdict).
  Widget _row(AppPalette p, Map<String, dynamic> g, {String? dim, bool diag = false}) {
    final net = _d(g['net_usdt']);
    final v = '${g['verdict']}';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (dim != null) Text(dim, style: context.type.metadata),
            Text('${g['label']}', style: context.type.primary.copyWith(fontSize: 13.5, fontWeight: FontWeight.w700)),
            Text('${_i(g['n'])} trades · win ${_d(g['win_pct']).toStringAsFixed(1)}% · avg ${_usdt(g['avg_usdt'])}', style: context.type.metadata),
          ]),
        ),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(_usdt(net), style: context.type.primary.copyWith(fontSize: 15, fontWeight: FontWeight.w800, color: diag ? p.textSecondary : (net >= 0 ? p.profit : p.loss))),
          if (!diag) Text(_vText(v), style: context.type.label.copyWith(fontSize: 10, fontWeight: FontWeight.w700, color: _vColor(p, v))),
        ]),
      ]),
    );
  }

  Widget _proven(AppPalette p, String title, Color edge, List<Map<String, dynamic>> rows) => OWLCard(
        edge: edge,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, title, 'known at entry, 30+ trades, same sign in both halves'),
          for (final g in rows) _row(p, g, dim: '${g['dim']}'),
        ]),
      );

  Widget _dimCard(AppPalette p, Map<String, dynamic> d, {bool diag = false}) {
    final rows = _l(d['rows']);
    final unsaved = _i(d['not_saved']);
    final hidden = _i(d['hidden']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, '${d['title']}'),
        if (rows.isEmpty) Text('Not saved in the trades yet ($unsaved trades without this field).', style: context.type.secondary),
        for (final g in rows) _row(p, g, diag: diag),
        if (hidden > 0) Text('$hidden more groups in the middle are hidden (best and worst are shown).', style: context.type.metadata),
        if (rows.isNotEmpty && unsaved > 0) Text('$unsaved trades did not save this field (not counted here).', style: context.type.metadata),
      ]),
    );
  }

  /// One folded line; tap opens the list behind it (rule 7).
  Widget _fold(AppPalette p, String text, bool open, VoidCallback tap, {Color? color}) {
    final c = color ?? p.textSecondary;
    return OWLPressable(
      onTap: tap,
      pressedScale: 0.985,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 4), border: Border.all(color: p.border)),
        child: Row(children: [
          Expanded(child: Text(text, style: context.type.secondary.copyWith(color: c, fontWeight: FontWeight.w600))),
          Icon(open ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 20, color: p.textMuted),
        ]),
      ),
    );
  }

  List<Widget> _body(AppPalette p, Map<String, dynamic> r) {
    final boxes = _m(r['boxes']);
    final order = (r['order'] is List) ? List<String>.from((r['order'] as List).map((e) => '$e')) : <String>[];
    final b = _m(boxes[_box]);
    final o = _m(b['overall']);
    final net = _d(o['net_usdt']);
    final avg = _d(o['avg_usdt']);
    final mk = _l(b['makes_money']).where((g) => !_diagTitles.contains('${g['dim']}')).toList();
    final ls = _l(b['loses_money']).where((g) => !_diagTitles.contains('${g['dim']}')).toList();
    final dims = _l(b['dims']);
    final entry = dims.where((d) => !_diagKeys.contains('${d['key']}')).toList();
    final diag = dims.where((d) => _diagKeys.contains('${d['key']}')).toList();
    return [
      if (order.length > 1)
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final k in order)
            ChoiceChip(label: Text(_short(k), style: const TextStyle(fontSize: 12)), selected: k == _box, onSelected: (_) => setState(() => _box = k)),
        ]),
      if (_vc != null) VerdictHeaderCard(card: _vc!),
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${b['title'] ?? ''}'.toUpperCase(), style: context.type.label.copyWith(color: p.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.6)),
        const SizedBox(height: 6),
        Row(children: [
          Expanded(child: StatTile(label: 'NET AFTER FEE', value: _usdt(net), sub: 'USDT, whole period', tone: net > 0 ? 'good' : (net < 0 ? 'bad' : ''))),
          const SizedBox(width: 8),
          Expanded(child: StatTile(label: 'CLOSED TRADES', value: '${_i(o['n'])}')),
        ]),
        const SizedBox(height: 8),
        Row(children: [
          Expanded(child: StatTile(label: 'WIN RATE', value: '${_d(o['win_pct']).toStringAsFixed(1)}%')),
          const SizedBox(width: 8),
          Expanded(child: StatTile(label: 'AVG PER TRADE', value: _usdt(avg), tone: avg > 0 ? 'good' : (avg < 0 ? 'bad' : ''))),
        ]),
        const SizedBox(height: 6),
        Text('${b['first_close_utc']} to ${b['last_close_utc']} (UTC)', style: context.type.metadata),
      ]),
      if (mk.isEmpty && ls.isEmpty)
        OWLCard(child: Text('No group known at entry is proven yet (30+ trades and the same sign in both halves). Nothing here is proven profit or proven loss.', style: context.type.secondary)),
      if (mk.isNotEmpty) _proven(p, 'Making money', p.profit, mk),
      if (ls.isNotEmpty) _proven(p, 'Losing money', p.loss, ls),
      if (mk.isEmpty && ls.isNotEmpty) Text('No entry group is steadily making money yet.', style: context.type.metadata),
      if (ls.isEmpty && mk.isNotEmpty) Text('No entry group is steadily losing yet.', style: context.type.metadata),
      if (entry.isNotEmpty) _fold(p, 'Details: ${entry.length} lists known at entry (side, time, coin, timeframe, zone, trend)', _showEntry, () => setState(() => _showEntry = !_showEntry)),
      if (_showEntry) for (final d in entry) _dimCard(p, d),
      if (diag.isNotEmpty) _fold(p, 'Diagnosis only: known after the trade ended (not a filter)', _showDiag, () => setState(() => _showDiag = !_showDiag), color: p.textMuted),
      if (_showDiag) ...[
        Text('How it ended and how long it was open are known only when the trade is over. A long trade is long because it was winning, so these lists describe what happened; they never say what to trade.', style: context.type.metadata),
        for (final d in diag) _dimCard(p, d, diag: true),
      ],
      Text('Closed trades only, net of fee. This is evidence, not an order: a group that made money before can stop.', style: context.type.metadata),
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
      kids = [OWLCard(edge: p.warning, child: Text(r != null && r['ready'] == false ? '${r['note'] ?? 'Not ready.'}' : _problem(r ?? <String, dynamic>{'state': 'error'}), style: context.type.primary))];
    } else if (_box == null) {
      kids = [OWLCard(child: Text('${r['note'] ?? 'No closed trades found yet.'}', style: context.type.primary))];
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
