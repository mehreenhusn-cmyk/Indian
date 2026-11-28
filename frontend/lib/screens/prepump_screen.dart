import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 49 (Pre-pump / Pre-dump Watch 3 of 3): the PUMP WATCH and DUMP WATCH on a screen. Read-only: it only asks the backend for /api/v2/prepump_watch
/// (Part 48, today's two watch lists) and /api/v2/prepump (Part 47, the old cases), draws the answers and changes nothing (no setting, no position, no order, no file).
/// Two tabs: PUMP (today's top 20 GAINERS) and DUMP (today's top 20 LOSERS); they are never mixed. For every coin: when it FIRST stood in the top 20 today (rank, change,
/// price), whether that first moment lies inside the range of the old cases (MATCH / OUTSIDE / NOT ENOUGH DATA / NOT JUDGED, AUTHENTIC and PROXY apart) and what the price did since
/// (change since entry, highest / lowest saved price, coverage). MATCH is common and is only a description of old cases: read it with the base count. Rules shown on screen:
/// after a coin leaves the top 20 its price is UNKNOWN (not flat), ENTRY_CENSORED coins are never judged early, a snapshot older than 15 min is STALE; no prediction, no win rate, no order.
class PrepumpScreen extends StatefulWidget {
  const PrepumpScreen({super.key});

  @override
  State<PrepumpScreen> createState() => _PrepumpScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _pct(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%' : 'UNKNOWN';
String _num(Object? v, [int d = 2]) => v is num ? v.toStringAsFixed(d) : 'UNKNOWN';
int _int(Object? v) => v is num ? v.toInt() : 0;
String _range(Object? v) {
  final r = _l(v);
  return r.length == 2 && r[0] is num && r[1] is num ? '${_num(r[0], 1)} to ${_num(r[1], 1)}' : '--';
}

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Pre-pump routes yet. Install the newest zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _PrepumpScreenState extends State<PrepumpScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  bool _pump = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchPrepump();
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

  Color _matchColor(AppPalette p, String s) => s == 'MATCH' ? p.accent : (s == 'OUTSIDE' ? p.textSecondary : p.warning);

  Widget _line(AppPalette p, String k, String v, {Color? c}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          SizedBox(width: 120, child: Text(k, style: TextStyle(fontSize: 12, color: p.textSecondary))),
          Expanded(child: Text(v, style: TextStyle(fontSize: 12, color: c ?? p.textPrimary))),
        ]),
      );

  /// The old cases of this side (Part 47 numbers used by Part 48): n and the range, AUTHENTIC and PROXY apart.
  Widget _oldCard(AppPalette p, String kind, Map<String, dynamic> old) => OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('OLD CASES (${kind == 'GAINER' ? 'pumped' : 'dumped'} coins, new episodes only)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          for (final s in const ['AUTHENTIC', 'PROXY']) ...[
            _line(p, s, _int(_m(old['$kind/$s'])['n']) >= 10 ? 'n ${_int(_m(old['$kind/$s'])['n'])}' : '${_t(_m(old['$kind/$s'])['status'])}',
                c: _int(_m(old['$kind/$s'])['n']) >= 10 ? null : p.warning),
            if (_m(old['$kind/$s'])['rank'] != null)
              Padding(
                padding: const EdgeInsets.only(left: 120),
                child: Text('rank ${_range(_m(old['$kind/$s'])['rank'])}   change ${_range(_m(old['$kind/$s'])['change'])}%   hour ${_range(_m(old['$kind/$s'])['hours'])}',
                    style: TextStyle(fontSize: 11, color: p.textMuted)),
              ),
          ],
        ]),
      );

  Widget _coinCard(AppPalette p, Map<String, dynamic> c) {
    final cens = c['entry_status'] == 'ENTRY_CENSORED';
    final path = _m(c['path']);
    final m = _m(c['matches']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(_t(c['symbol']), style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          if (cens) _chip('ENTRY CENSORED', p.warning),
          if (c['in_top20_now'] == true) ...[const SizedBox(width: 4), _chip('IN TOP 20 NOW', p.accent)],
        ]),
        const SizedBox(height: 4),
        Wrap(spacing: 6, runSpacing: 4, children: [
          for (final s in const ['AUTHENTIC', 'PROXY']) _chip('$s ${_t(_m(m[s])['status'])}', _matchColor(p, '${_m(m[s])['status']}')),
        ]),
        const SizedBox(height: 4),
        _line(p, 'First in top 20', '${_t(c['first_top20_utc'])}  (hour ${_num(c['hours_into_day'], 1)} of the UTC day)'),
        _line(p, 'Rank / change then', '#${_t(c['rank_at_first'])}  ${_pct(c['change_at_first_pct'])}'),
        _line(p, 'Entry price', _t(c['entry_price'])),
        if (c['latest_price'] == null)
          _line(p, 'Since entry', '${_t(c['note'])}', c: p.warning)
        else ...[
          _line(p, 'Since entry', '${_pct(c['change_since_entry_pct'])}  after ${_num(c['hours_since_entry'], 1)} h  (${_t(c['freshness'])})'),
          if (_int(path['snapshots']) > 0)
            _line(p, 'Saved high / low', 'up ${_pct(path['max_up_pct'])}   down ${_pct(path['max_down_pct'])}   coverage ${_num(path['coverage_pct'], 0)}%')
          else
            _line(p, 'Saved high / low', 'UNKNOWN: no snapshot after entry (not flat)', c: p.warning),
        ],
        if (cens) Text('${_t(c['entry_note'])}', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  /// Part 47 early sign per old day: how many observed / censored / unavailable and the medians (AUTHENTIC and PROXY apart).
  Widget _earlyCard(AppPalette p, String kind, Map<String, dynamic> early) {
    final rows = <Widget>[];
    for (final d in _l(early['days']).whereType<Map>()) {
      final sum = _m(_m(d['summary']));
      for (final s in const ['AUTHENTIC', 'PROXY']) {
        final e = _m(_m(sum[s])[kind]);
        if (e.isEmpty) continue;
        final ob = _int(e['observed']);
        rows.add(_line(p, '${_t(d['day'])} $s',
            ob == 0 ? 'observed 0, censored ${_int(e['censored'])}, unavailable ${_int(e['unavailable'])}' : 'observed $ob, median hour ${_num(e['median_hours_into_day'], 1)}, still ahead ${_num(e['median_share_still_ahead'], 2)}'));
      }
    }
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('EARLY SIGN OF OLD DAYS (Part 47)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        if (rows.isEmpty) Text('NOT ENOUGH DATA: no saved cohort day has early-sign numbers yet.', style: TextStyle(fontSize: 12, color: p.textMuted)) else ...rows,
      ]),
    );
  }

  Widget _notes(AppPalette p, List<dynamic> a, List<dynamic> b) {
    final notes = [...a, ...b].map((e) => '$e').toSet().toList();
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('HOW TO READ THIS', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        for (final n in notes.take(12)) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('- $n', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    final watch = _m(d?['watch']);
    final today = _m(watch['today']);
    final kind = _pump ? 'GAINER' : 'LOSER';
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['watch'] is! Map || today.isEmpty) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      kids.add(Text('Read-only watch. Today ${_t(today['day'])} (UTC). Nothing is ordered, nothing is predicted, no win rate.', style: TextStyle(fontSize: 12, color: p.textMuted)));
      kids.add(Row(children: [
        for (final e in const [true, false])
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(label: Text(e ? 'PUMP (gainers)' : 'DUMP (losers)', style: const TextStyle(fontSize: 12)), selected: _pump == e, onSelected: (_) => setState(() => _pump = e)),
          ),
      ]));
      if (today['status'] != 'OK') {
        kids.add(OWLCard(edge: p.warning, child: Text('${_t(today['status'])}: ${_t(today['note'])}', style: TextStyle(fontSize: 13, color: p.textPrimary))));
      } else {
        if (today['freshness'] != 'fresh') {
          kids.add(OWLCard(edge: p.warning, child: Text('${_t(today['note'])}  (newest snapshot ${_t(today['last_snapshot_utc'])})', style: TextStyle(fontSize: 12.5, color: p.textPrimary))));
        }
        final list = _m(_m(today['lists'])[_pump ? 'PRE_PUMP' : 'PRE_DUMP']);
        final rows = _l(list['rows']).whereType<Map>().toList();
        final mt = _m(list['matching']);
        kids.add(_oldCard(p, kind, _m(watch['old_cases'])));
        kids.add(OWLCard(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_pump ? 'PRE-PUMP WATCH LIST' : 'PRE-DUMP WATCH LIST', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
            const SizedBox(height: 4),
            _line(p, 'Coins in list today', '${_int(list['coins_in_top20_today'])}  (showing ${_int(list['shown'])})'),
            _line(p, 'MATCH AUTHENTIC', '${_int(mt['AUTHENTIC'])} of ${_int(list['coins_in_top20_today'])}'),
            _line(p, 'MATCH PROXY', '${_int(mt['PROXY'])} of ${_int(list['coins_in_top20_today'])}'),
            Text(_t(list['base_note']), style: TextStyle(fontSize: 11, color: p.textMuted)),
          ]),
        ));
        if (rows.isEmpty) kids.add(OWLCard(child: Text('No coin of this side has stood in the top 20 today yet.', style: TextStyle(fontSize: 12.5, color: p.textMuted))));
        for (final c in rows) {
          kids.add(_coinCard(p, _m(c)));
        }
        kids.add(_earlyCard(p, kind, _m(d['early'])));
      }
      kids.add(_notes(p, _l(watch['notes']), _l(_m(d['early'])['notes'])));
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
