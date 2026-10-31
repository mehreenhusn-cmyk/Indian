import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 57 (Scalp Lab 8 of 8): the SCALP LAB on a screen. Read-only: it only asks the backend for /api/v2/scalp_report (Part 54, the ledger of finished replay records)
/// and /api/v2/scalp_large5 (Part 56, big real trades replayed on 3m and 5m beside the real result), draws the answers and changes nothing (no setting, no order, no file).
/// Tab 1 LEDGER: every category / version / side is its own card, TRAIN (older) and HOLDOUT (newer) apart, never added; the evidence word is only "Insufficient data" or "Exploratory".
/// Tab 2 BIG TRADES: per box (real live, live estimated, paper 1, paper 2, never added): REAL vs ONE vs IN3 medians over the SAME trades, and the honesty gap ONE minus REAL.
/// Rules shown on screen: hypothetical replay of saved candles, fees and slippage already taken off, raw price %, not leveraged; under 30 cases says "too few"; no win rate, no prediction, no order.
class ScalpLabScreen extends StatefulWidget {
  const ScalpLabScreen({super.key});

  @override
  State<ScalpLabScreen> createState() => _ScalpLabScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _pct(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%' : '--';
int _int(Object? v) => v is num ? v.toInt() : 0;

const _boxNames = {
  'real_live': 'Real live trades',
  'live_estimated': 'Live trades (estimated)',
  'paper_b1': 'Paper bot 1',
  'paper_b2': 'Paper bot 2',
};

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Scalp Lab routes yet. Install the newest zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _ScalpLabScreenState extends State<ScalpLabScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int _tab = 0;
  int _days = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchScalpLab(_days);
    if (!mounted) return;
    setState(() {
      _data = d;
      _loading = false;
    });
  }

  Future<void> _refresh() async {
    setState(() => _loading = true);
    await _load();
  }

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(6), border: Border.all(color: c.withOpacity(0.45))),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _title(AppPalette p, String s) => Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 2),
        child: Text(s, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
      );

  Widget _msg(AppPalette p, String s) => OWLCard(edge: p.warning, child: Text(s, style: TextStyle(fontSize: 13, color: p.textPrimary)));

  /// One TRAIN / HOLDOUT line of the ledger: counts per exit and the median, or the honest reason there is no number.
  Widget _sumRow(AppPalette p, String label, Map<String, dynamic> s) {
    final n = _int(s['n']);
    final few = '${s['note'] ?? ''}'.isNotEmpty;
    final body = n == 0
        ? 'no finished record yet'
        : 'target ${_int(s['TARGET'])}  stop ${_int(s['STOP'])}  time ${_int(s['TIME'])}' + (few ? '  (too few to say anything)' : '  median ${_pct(s['median_net_pct'])}  total ${_pct(s['sum_net_pct'])}');
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 74, child: Text(label, style: TextStyle(fontSize: 12, color: p.textSecondary))),
        SizedBox(width: 40, child: Text('n $n', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: few ? p.warning : p.textPrimary))),
        Expanded(child: Text(body, style: TextStyle(fontSize: 12, color: n == 0 ? p.textMuted : p.textPrimary))),
      ]),
    );
  }

  Widget _catCard(AppPalette p, Map<String, dynamic> c) {
    final sides = _m(c['sides']);
    final def = _m(c['definition']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${_t(c['category'])}  v${_t(c['version'])}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip('REPLAY ONLY', p.purple),
        ]),
        const SizedBox(height: 2),
        Text('rule saved ${_t(c['saved_utc'])} UTC   HOLDOUT from ${_t(c['holdout_from_utc'])} UTC', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        for (final k in def.keys.take(6)) Text('$k: ${_t(def[k])}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
        for (final sd in sides.keys) ...[
          _title(p, '$sd   ${_int(_m(sides[sd])['records'])} records, ${_int(_m(sides[sd])['coins'])} coins'),
          Align(alignment: Alignment.centerLeft, child: _chip(_t(_m(sides[sd])['evidence']), _t(_m(sides[sd])['evidence']) == 'Exploratory' ? p.accent : p.warning)),
          _sumRow(p, 'TRAIN', _m(_m(sides[sd])['TRAIN'])),
          _sumRow(p, 'HOLDOUT', _m(_m(sides[sd])['HOLDOUT'])),
        ],
      ]),
    );
  }

  List<Widget> _ledger(AppPalette p, Map<String, dynamic> r) {
    if (r['categories'] is! List) return [_msg(p, r['ready'] == false ? _t(r['note']) : _problem(r['state']))];
    final cats = _l(r['categories']).whereType<Map>().toList();
    if (cats.isEmpty) return [_msg(p, 'No category has been replayed yet. Run backend/v2_scalp_run.py once; the ledger then fills in.')];
    return [for (final c in cats) _catCard(p, _m(c)), _notes(p, _l(r['notes']))];
  }

  /// One side-by-side line: REAL / ONE / IN3 medians over the same trades, the gap, and how often IN3 was better.
  Widget _sbsRow(AppPalette p, Map<String, dynamic> x) {
    final n = _int(x['n_paired']);
    final few = '${x['note'] ?? ''}'.isNotEmpty;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${_t(x['interval'])} ${_t(x['sample'])}   n $n${few ? '  (too few to say anything)' : ''}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: few ? p.warning : p.textPrimary)),
        if (n == 0)
          Text('no replayed trade yet', style: TextStyle(fontSize: 12, color: p.textMuted))
        else ...[
          if (!few)
            Text('REAL ${_pct(x['REAL_net_pct'])}   ONE ${_pct(x['ONE_net_pct'])}   IN3 ${_pct(x['IN3_net_pct'])}   gap ${_pct(x['ONE_minus_REAL'])}', style: TextStyle(fontSize: 12, color: p.textPrimary)),
          Text('IN3 better ${_int(x['IN3_better'])}   worse ${_int(x['IN3_worse'])}   same ${_int(x['same'])}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        ],
      ]),
    );
  }

  Widget _boxCard(AppPalette p, String box, Map<String, dynamic> b, List<Map<String, dynamic>> lines) {
    final st = _m(b['statuses']);
    final cut = b['large_cutoff_notional'];
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_boxNames[box] ?? box, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 2),
        if (cut == null)
          Text('${_int(b['trades'])} trades: ${_t(b['note'])}', style: TextStyle(fontSize: 12, color: p.warning))
        else ...[
          Text('${_int(b['trades'])} trades, ${_int(b['large_trades'])} large (notional from $cut USDT), ${_int(b['replayed'])} replayed', style: TextStyle(fontSize: 12, color: p.textSecondary)),
          Text('not replayed: no candles ${_int(st['NO_CANDLES'])}, gap ${_int(st['GAP'])}, too short ${_int(st['TOO_SHORT'])}, bad row ${_int(st['BAD_ROW'])}', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
          for (final x in lines) _sbsRow(p, x),
        ],
      ]),
    );
  }

  List<Widget> _big(AppPalette p, Map<String, dynamic> r) {
    if (r['boxes'] is! Map) return [_msg(p, r['ready'] == false ? _t(r['note']) : _problem(r['state']))];
    final lines = _l(r['side_by_side']).whereType<Map>().map((e) => _m(e)).toList();
    final boxes = _m(r['boxes']);
    return [
      Row(children: [
        for (final n in const [0, 30, 7])
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(
              label: Text(n == 0 ? 'All trades' : '$n days', style: const TextStyle(fontSize: 12)),
              selected: _days == n,
              onSelected: (_) {
                setState(() {
                  _days = n;
                  _loading = true;
                });
                _load();
              },
            ),
          ),
      ]),
      for (final k in _boxNames.keys)
        if (boxes[k] is Map) _boxCard(p, k, _m(boxes[k]), [for (final x in lines) if (x['box'] == k) x]),
      _notes(p, _l(r['notes'])),
    ];
  }

  Widget _notes(AppPalette p, List<dynamic> notes) => OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('HOW TO READ THIS', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          for (final n in notes.take(8)) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('- $n', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
          Text('Everything here is a hypothetical replay of saved candles. No prediction, no win rate, no order, no advice to change a real trade.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else {
      kids.add(Row(children: [
        for (final e in const [MapEntry(0, 'Ledger'), MapEntry(1, 'Big trades')])
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(label: Text(e.value, style: const TextStyle(fontSize: 12.5)), selected: _tab == e.key, onSelected: (_) => setState(() => _tab = e.key)),
          ),
      ]));
      kids.addAll(_tab == 0 ? _ledger(p, _m(d?['report'])) : _big(p, _m(d?['large'])));
    }
    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.l, AppSpacing.l, AppSpacing.xl),
        children: [for (final w in kids) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: w)],
      ),
    );
  }
}
