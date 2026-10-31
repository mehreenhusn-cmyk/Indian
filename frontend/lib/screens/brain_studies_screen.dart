import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 89c (Zone, squeeze and limits studies): read-only. Three tabs on the Part 89a / 89b routes, which only read the study files the auto-runner makes every 6 hours.
/// ZONES = /api/v2/brain_zones: what price did after it ARRIVED in an SD zone (median move after 3 / 6 / 12 / 24 candles in R, the hypothetical BT-01 trade, TRAIN / HOLDOUT, against ordinary candles).
/// SQUEEZE = /api/v2/brain_limits (squeeze_rows): what the break did after a squeeze ended. LIMITS = /api/v2/brain_limits (limit_rows): BT-01's stop / target / hold / stop band replayed with other values.
/// Nothing is saved or applied. A BETTER CANDIDATE is only an idea for a future BT-02 and needs the owner's OK. Dart NOT compiled (the APK build is the proof).
class BrainStudiesScreen extends StatefulWidget {
  const BrainStudiesScreen({super.key});

  @override
  State<BrainStudiesScreen> createState() => _BrainStudiesScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
List<String> _s(Object? v) => v is List ? [for (final e in v) '$e'] : <String>[];
String _f(Object? v, [int d = 2]) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}' : '-';

class _BrainStudiesScreenState extends State<BrainStudiesScreen> {
  Map<String, dynamic>? _zn;
  Map<String, dynamic>? _lm;
  bool _busy = true;
  String _side = 'ALL';
  bool _words = false;
  bool _allLimits = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _busy = true);
    final prov = context.read<AppProvider>();
    final r = await Future.wait([prov.fetchBrainZones(), prov.fetchBrainLimits()]);
    if (!mounted) return;
    setState(() {
      _zn = r[0];
      _lm = r[1];
      _busy = false;
    });
  }

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return '${r['error']}';
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down to refresh.';
      case 'old':
        return 'This backend does not have the study routes yet. Install the newest zip, restart the backend, then pull down.';
      default:
        return 'Cannot reach the backend right now. Pull down to try again.';
    }
  }

  bool _bad(Map<String, dynamic>? r) => r == null || r['state'] != null || r['error'] != null || r['ready'] != true;

  Widget _msg(AppPalette p, Map<String, dynamic>? r) {
    final lines = r == null ? <String>[] : _s(r['lines']);
    final text = r != null && r['ready'] == false && lines.isNotEmpty ? lines.first : _problem(r ?? <String, dynamic>{'state': 'error'});
    return OWLCard(edge: p.warning, child: Text(text, style: TextStyle(fontSize: 13, color: p.textPrimary)));
  }

  Color _vc(AppPalette p, String v) {
    if (v == 'USE' || v == 'BETTER CANDIDATE') return p.profit;
    if (v == 'AVOID' || v == 'WORSE') return p.loss;
    if (v == 'MIXED' || v == 'NO CLEAR GAIN') return p.warning;
    return p.textMuted;
  }

  Widget _chip(String t, Color c) => Container(
        margin: const EdgeInsets.only(right: 6, top: 4),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
        child: Text(t, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: c)),
      );

  Widget _title(AppPalette p, String t, [String? sub]) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub != null) Text(sub, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        ]),
      );

  Widget _small(AppPalette p, String t, {Color? c}) => Padding(padding: const EdgeInsets.only(top: 2), child: Text(t, style: TextStyle(fontSize: 12, color: c ?? p.textSecondary)));

  String _fwd(Object? v) {
    final f = _m(v);
    return ['3', '6', '12', '24'].map((h) => _f(f[h])).join(' / ');
  }

  String _grp(String g) {
    if (g == 'ALL') return 'all squeezes';
    if (g.startsWith('len:')) return 'squeeze length ${g.substring(4)}';
    if (g.startsWith('end:')) return 'squeeze ended in ${g.substring(4)}';
    if (g.startsWith('vol:')) return 'volume ${g.substring(4)}';
    return g;
  }

  Widget _head(AppPalette p, String title, Map<String, dynamic> r) {
    final age = r['age_hours'];
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        _title(p, title, age is num ? 'Made ${age.toStringAsFixed(1)} hours ago (the auto-runner makes it again every 6 hours). Pretend money, read-only.' : 'Pretend money, read-only.'),
        for (final s in _s(r['lines'])) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(s, style: TextStyle(fontSize: 12.5, color: p.textPrimary))),
      ]),
    );
  }

  Widget _zoneRow(AppPalette p, Map<String, dynamic> r) {
    final v = '${r['verdict']}';
    final all = r['state'] == 'ALL';
    return OWLCard(
      edge: _vc(p, v),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${r['side']} - SD zone ${r['zone']} - ${all ? 'all market states' : r['state']}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
        _small(p, '${r['n']} cases from ${r['coins']} coins. Mean net ${_f(r['mean_net_r'])} R per trade (TRAIN ${_f(r['train_net_r'])}, HOLDOUT ${_f(r['holdout_net_r'])}).'),
        _small(p, 'Against ordinary candles: ${_f(r['edge_vs_baseline_r'])} R. Median move after 3 / 6 / 12 / 24 candles: ${_fwd(r['fwd_median_r'])} R.'),
        Wrap(children: [_chip(v, _vc(p, v))]),
      ]),
    );
  }

  List<Widget> _zones(AppPalette p) {
    final r = _zn;
    if (_bad(r)) return [_msg(p, r)];
    final b = _m(r!['baseline']);
    var rows = _l(r['rows']).where((x) => _side == 'ALL' || x['side'] == _side).toList();
    if (_words) rows = rows.where((x) => x['verdict'] == 'USE' || x['verdict'] == 'AVOID').toList();
    final shown = rows.take(40).toList();
    return [
      _head(p, 'SD-zone study', r),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(p, 'Ordinary candles (baseline)', 'The same BT-01 trade from any ready candle: what "no idea at all" gives'),
          _small(p, 'LONG ${_f(_m(b['LONG'])['mean_net_r'])} R, SHORT ${_f(_m(b['SHORT'])['mean_net_r'])} R net per trade'),
          Wrap(spacing: 8, children: [
            for (final s in ['ALL', 'LONG', 'SHORT']) ChoiceChip(label: Text(s == 'ALL' ? 'Both sides' : s), selected: _side == s, onSelected: (_) => setState(() => _side = s)),
            FilterChip(label: const Text('Only USE / AVOID'), selected: _words, onSelected: (v) => setState(() => _words = v)),
          ]),
        ]),
      ),
      if (shown.isEmpty) _small(p, 'No row matches this filter.'),
      for (final x in shown) _zoneRow(p, x),
      Text('${r['limit']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  Widget _sqRow(AppPalette p, Map<String, dynamic> r) {
    final v = '${r['verdict']}';
    return OWLCard(
      edge: _vc(p, v),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Break ${r['dir']} - ${_grp('${r['group']}')}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
        _small(p, '${r['n']} squeeze ends from ${r['coins']} coins. Mean net ${_f(r['mean_net_r'])} R per trade (TRAIN ${_f(r['train_net_r'])}, HOLDOUT ${_f(r['holdout_net_r'])}).'),
        _small(p, 'Went back inside within 6 candles: ${r['went_back']} of ${r['n']}. Median move after 3 / 6 / 12 / 24 candles: ${_fwd(r['fwd_median_r'])} R.'),
        Wrap(children: [_chip(v, _vc(p, v))]),
      ]),
    );
  }

  List<Widget> _squeeze(AppPalette p) {
    final r = _lm;
    if (_bad(r)) return [_msg(p, r)];
    final rows = _l(r!['squeeze_rows']);
    return [
      _head(p, 'Squeeze study', r),
      if (rows.isEmpty) _small(p, 'No squeeze has ended in the saved candles yet.'),
      for (final x in rows.take(40)) _sqRow(p, x),
      Text('${r['limit']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  Widget _limRow(AppPalette p, Map<String, dynamic> r) {
    final v = '${r['verdict']}';
    final band = r['band'] is List ? (r['band'] as List) : <dynamic>[];
    final ex = _m(r['exits']);
    final ref = v == 'REFERENCE';
    final bandTxt = r['kind'] == 'band' && band.length == 2 ? ', stop distance ${band[0]}-${band[1]} % of price' : '';
    return OWLCard(
      edge: ref ? p.accent : _vc(p, v),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${ref ? 'BT-01 now: ' : ''}stop ${r['stop_sd']} SD, target ${r['target_r']} R, ${r['hold']} candles$bandTxt', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: p.textPrimary)),
        _small(p, '${r['n']} trades, ${_f(r['mean_net_pct'], 3)} % of price per trade after cost (${_f(r['usdt_per_trade'], 3)} USDT per 100 USDT trade).'),
        if (!ref) _small(p, 'Against BT-01 on ${r['n_common']} common trades: ${_f(r['diff_pct'], 3)} points (TRAIN ${_f(r['train_diff'], 3)}, HOLDOUT ${_f(r['holdout_diff'], 3)}).'),
        _small(p, 'Ended by stop ${ex['S'] ?? 0}, target ${ex['T'] ?? 0}, time ${ex['H'] ?? 0}.', c: p.textMuted),
        Wrap(children: [_chip(v, ref ? p.accent : _vc(p, v))]),
      ]),
    );
  }

  List<Widget> _limits(AppPalette p) {
    final r = _lm;
    if (_bad(r)) return [_msg(p, r)];
    final rows = _l(r!['limit_rows']);
    final shown = _allLimits ? rows : rows.take(12).toList();
    return [
      _head(p, 'Starting-limits study', r),
      for (final x in shown) _limRow(p, x),
      if (rows.length > 12) OutlinedButton(onPressed: () => setState(() => _allLimits = !_allLimits), child: Text(_allLimits ? 'Show fewer rows' : 'Show all ${rows.length} rows')),
      Text('${r['limit']}', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  Widget _tab(AppPalette p, List<Widget> kids) => RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.l),
          children: [for (final k in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: k)],
        ),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final loading = [const Padding(padding: EdgeInsets.all(40), child: Center(child: CircularProgressIndicator()))];
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(title: const Text('Zone, squeeze and limits studies'), bottom: const TabBar(tabs: [Tab(text: 'Zones'), Tab(text: 'Squeeze'), Tab(text: 'Limits')])),
        body: TabBarView(children: [
          _tab(p, _busy && _zn == null ? loading : _zones(p)),
          _tab(p, _busy && _lm == null ? loading : _squeeze(p)),
          _tab(p, _busy && _lm == null ? loading : _limits(p)),
        ]),
      ),
    );
  }
}
