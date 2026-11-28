import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 34 (Radar 6 of 6): the RADAR on a screen. Read-only: it only asks the backend for /api/v2/radar, /api/v2/radar_outcomes and
/// /api/v2/radar_moves (Parts 29-33), draws the answers and changes nothing (no setting, no position, no order, no file).
/// 7 tabs (Yesterday ... 7 days ago). Each day shows its saved cohort: top GAINERs and top LOSERs at 00:00 UTC, every coin with
/// the change since the snapshot, the 1 / 2 / 3 / 7-day outcome classes and the move numbers (max favourable / adverse, time to peak,
/// drawdown, volume state). Rules shown on screen: AUTHENTIC and PROXY stay labelled; a number that is not saved says UNKNOWN or
/// PENDING, never 0; days and sides are never added together; no prediction and no win rate. Pull down to refresh.
class RadarScreen extends StatefulWidget {
  const RadarScreen({super.key});

  @override
  State<RadarScreen> createState() => _RadarScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _pct(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%' : 'UNKNOWN';
String _mins(Object? v) {
  if (v is! num) return 'UNKNOWN';
  if (v < 60) return '${v.toStringAsFixed(0)} min';
  return '${(v / 60).toStringAsFixed(1)} h';
}

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Radar routes yet. Install the Part 33 zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _RadarScreenState extends State<RadarScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int _sel = 0;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchRadar();
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

  Widget _line(AppPalette p, String label, String value, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(flex: 5, child: Text(label, style: TextStyle(fontSize: 12, color: p.textSecondary))),
          Expanded(
              flex: 5,
              child: Text(value,
                  textAlign: TextAlign.right, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: color ?? p.textPrimary))),
        ]),
      );

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(6), border: Border.all(color: c.withOpacity(0.45))),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  /// Class words describe what the saved prices did. They are not good / bad and not a forecast, so no profit / loss colours.
  Color _classColor(AppPalette p, String c) {
    switch (c) {
      case 'FURTHER_PUMP':
      case 'FURTHER_DUMP':
      case 'CONTINUATION':
        return p.accent;
      case 'REVERSAL':
        return p.purple;
      case 'UNRESOLVED':
        return p.warning;
      default:
        return p.textMuted;
    }
  }

  Map<String, Map<String, dynamic>> _byCoin(Map<String, dynamic>? report, String day, String key) {
    final out = <String, Map<String, dynamic>>{};
    for (final d in _l(report?['days']).whereType<Map>()) {
      if ('${d['day']}' != day) continue;
      for (final r in _l(d['rows']).whereType<Map>()) {
        out['${r['kind']}|${r['symbol']}'] = _m(r[key]);
        if (key == 'outcomes') out['${r['kind']}|${r['symbol']}|ep'] = _m(r['episode']);
      }
    }
    return out;
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    final days = _l(_m(d?['radar'])['days']).whereType<Map>().toList();
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['radar'] is! Map || days.isEmpty) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      final sel = _sel < days.length ? _sel : 0;
      final day = _m(days[sel]);
      kids.add(Text(
          'Read-only. Made ${_t(_m(d['radar'])['made_utc'])}. Each day stands alone. AUTHENTIC and PROXY stay labelled. No prediction, no win rate.',
          style: TextStyle(fontSize: 12, color: p.textMuted)));
      kids.add(SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(children: [
          for (var i = 0; i < days.length; i++)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                label: Text(_t(_m(days[i])['tab'] ?? _m(days[i])['day']), style: const TextStyle(fontSize: 12)),
                selected: i == sel,
                onSelected: (_) => setState(() => _sel = i),
              ),
            ),
        ]),
      ));
      kids.add(_dayCard(p, day));
      if (day['status'] != 'MISSING') {
        final dayKey = '${day['day']}';
        final outs = _byCoin(_m(d['outcomes']), dayKey, 'outcomes');
        final mvs = _byCoin(_m(d['moves']), dayKey, 'moves');
        for (final kind in const ['GAINER', 'LOSER']) {
          final rows = _l(day['rows']).whereType<Map>().where((r) => r['kind'] == kind).toList();
          if (rows.isEmpty) continue;
          kids.add(Text(kind == 'GAINER' ? 'TOP GAINERS (pumped that UTC day)' : 'TOP LOSERS (dumped that UTC day)',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.4, color: p.textSecondary)));
          for (final r in rows) {
            final key = '$kind|${r['symbol']}';
            kids.add(_coinCard(p, _m(r), outs[key] ?? const {}, _m(outs['$key|ep']), mvs[key] ?? const {}));
          }
        }
      }
      kids.add(_notes(p, _l(_m(d['radar'])['notes']), _l(_m(d['moves'])['notes'])));
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

  Widget _dayCard(AppPalette p, Map<String, dynamic> day) {
    final status = _t(day['status']);
    if (status == 'MISSING') {
      return OWLCard(
          edge: p.warning,
          child: Text('${_t(day['day'])}: MISSING. ${_t(day['note'])}', style: TextStyle(fontSize: 12, color: p.textPrimary)));
    }
    final sum = _m(day['summary']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${_t(day['tab'])}  |  cohort of ${_t(day['day'])}',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Cohort', status, color: status == 'COMPLETE' ? null : p.warning),
        _line(p, 'Sources', _m(day['by_source']).entries.map((e) => '${e.key} ${e.value}').join(', ')),
        for (final k in const ['GAINER', 'LOSER'])
          if (_m(sum[k]).isNotEmpty)
            _line(p, '$k median change', '${_pct(_m(sum[k])['median_change_pct'])}  (${_m(sum[k])['priced'] ?? 0} of ${_m(sum[k])['coins'] ?? 0} priced)'),
      ]),
    );
  }

  Widget _coinCard(AppPalette p, Map<String, dynamic> r, Map<String, dynamic> outs, Map<String, dynamic> ep, Map<String, dynamic> mv) {
    final authentic = r['source'] == 'AUTHENTIC';
    final ok = mv['status'] == 'OK';
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(
              child: Text('#${_t(r['rank'])}  ${_t(r['symbol'])}',
                  style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(_t(r['source']), authentic ? p.accent : p.warning),
          if (ep['repeat'] == true) ...[const SizedBox(width: 6), _chip('REPEAT', p.textMuted)],
        ]),
        const SizedBox(height: 4),
        _line(p, 'Change since snapshot', r['change_pct'] == null ? 'UNKNOWN (no price saved)' : '${_pct(r['change_pct'])}  (${_t(r['freshness'])})'),
        if (outs.isNotEmpty) ...[
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 4, children: [
            for (final h in const ['1', '2', '3', '7'])
              if (outs[h] is Map)
                _chip('${h}d ${_t(_m(outs[h])['class'])}${_m(outs[h])['move_pct'] is num ? ' ${_pct(_m(outs[h])['move_pct'])}' : ''}',
                    _classColor(p, '${_m(outs[h])['class']}')),
          ]),
        ],
        const SizedBox(height: 4),
        if (!ok)
          Text('Move numbers: UNKNOWN. ${_t(mv['reason'])}', style: TextStyle(fontSize: 11.5, color: p.warning))
        else ...[
          _line(p, 'Max favourable / adverse', '${_pct(mv['max_favourable_pct'])} / ${_pct(mv['max_adverse_pct'])}'),
          _line(p, 'Time to peak', _mins(mv['time_to_peak_min'])),
          _line(p, 'Max drawdown', _m(mv['max_drawdown'])['value'] is num ? '${(_m(mv['max_drawdown'])['value'] as num).toStringAsFixed(2)}%' : 'UNKNOWN'),
          _line(p, 'Volume vs same hour (7 days)', _volume(_m(mv['volume_state']))),
          if (mv['window_complete'] != true) Text('The first 24 hours are not over: numbers are so far.', style: TextStyle(fontSize: 11, color: p.textMuted)),
        ],
      ]),
    );
  }

  String _volume(Map<String, dynamic> v) {
    if (v['status'] != 'OK') return 'UNKNOWN';
    return '${_t(v['state'])} (x${_t(v['ratio'])}, ${_t(v['baseline_days'])} days)';
  }

  Widget _notes(AppPalette p, List<dynamic> a, List<dynamic> b) {
    final notes = [...a, ...b].map((e) => '$e').toSet().toList();
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('HOW TO READ THIS', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        for (final n in notes.take(12)) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('- $n', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
        Text('Classes (FURTHER_PUMP, CONTINUATION, SIDEWAYS, REVERSAL) describe what the saved prices did. They are not signals.',
            style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }
}
