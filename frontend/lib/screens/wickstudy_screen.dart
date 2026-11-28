import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/study_verdict_header.dart';

/// Part 61 (Stop-wick Study 4 of 4): the STOP-WICK STUDY on a screen. Read-only: it only asks the backend for /api/v2/wickstudy (Part 58, the marks),
/// /api/v2/wickstudy_forward (Part 59, price after the wick) and /api/v2/wickstudy_reentry (Part 60, HYPOTHETICAL re-entry replay), draws the answers and changes
/// nothing (no setting, no position, no order, no file). Two types, never added: STOP_WICK_DOWN (a wick swept the lows of the 20 candles before and the close is back above)
/// and STOP_WICK_UP (the mirror). Each type card shows: how many marks (with medians of pierce, wick share, volume), what the price did 15 min to 4 h after the wick
/// (medians with n, wick-tip retakes) and the hypothetical re-entry (status counts, delay, risk, 15 min to 1 h medians). The baselines of ordinary candles are shown on top.
/// Rules shown on screen: PENDING = window not over, UNAVAILABLE = a candle is missing, never 0; fewer than 30 cases says "too few"; the re-entry is a replay with no fees,
/// no slippage and no real stop; no prediction, no win rate, no profit number, no order. Pull down to refresh.
class WickStudyScreen extends StatefulWidget {
  const WickStudyScreen({super.key});

  @override
  State<WickStudyScreen> createState() => _WickStudyScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _pct(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%' : 'UNKNOWN';
String _n(Object? v, [int d = 2]) => v is num ? v.toStringAsFixed(d) : 'UNKNOWN';
int _int(Object? v) => v is num ? v.toInt() : 0;
String _hz(String h) {
  switch (h) {
    case '15m':
      return '15 min';
    case '30m':
      return '30 min';
    case '1h':
      return '1 h';
    case '4h':
      return '4 h';
    default:
      return h;
  }
}

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Stop-wick routes yet. Install the newest zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _WickStudyScreenState extends State<WickStudyScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int _days = 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchWickStudy(_days);
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

  /// One horizon row: "n 12   end +0.12%   up +0.40%   down 0.30%" (+ the wick-tip count) or the honest reason there is no number.
  Widget _hRow(AppPalette p, String h, Map<String, dynamic> c, {String tipKey = ''}) {
    final n = _int(c['n']);
    final String body;
    if (n == 0) {
      body = 'no finished window yet (PENDING ${_int(c['pending'])}, UNAVAILABLE ${_int(c['unavailable'])})';
    } else {
      final tip = tipKey.isEmpty || c[tipKey] == null ? '' : '  tip hit ${_int(c[tipKey])} of $n';
      body = 'end ${_pct(c['median_end_pct'])}  up ${_pct(c['median_max_up_pct'])}  down ${_pct(c['median_max_down_pct'])}$tip';
    }
    final few = n > 0 && '${c['note'] ?? ''}'.isNotEmpty;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 52, child: Text(_hz(h), style: TextStyle(fontSize: 12, color: p.textSecondary))),
        SizedBox(width: 46, child: Text('n $n', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: few ? p.warning : p.textPrimary))),
        Expanded(child: Text(body, style: TextStyle(fontSize: 12, color: n == 0 ? p.textMuted : p.textPrimary))),
      ]),
    );
  }

  Widget _baseCard(AppPalette p, String title, List<String> hs, Map<String, dynamic> base) => OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          for (final h in hs) _hRow(p, h, _m(base[h])),
        ]),
      );

  Widget _typeCard(AppPalette p, Map<String, dynamic> mark, Map<String, dynamic> fwd, Map<String, dynamic> re) {
    final type = _t(mark['type']);
    final down = type == 'STOP_WICK_DOWN';
    final hits = _int(mark['hits']);
    final rhs = _m(re['horizons']).keys.toList();
    final sc = _m(re['status_counts']);
    final entries = _int(re['entries']);
    final markFew = '${mark['note'] ?? ''}'.isNotEmpty;
    final reFew = '${re['note'] ?? ''}'.isNotEmpty;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(type, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(down ? 'LOWS SWEPT' : 'HIGHS SWEPT', down ? p.accent : p.purple),
        ]),
        const SizedBox(height: 4),
        Text(markFew ? 'Marked $hits times  (too few to say anything)' : 'Marked $hits times', style: TextStyle(fontSize: 12, color: markFew ? p.warning : p.textSecondary)),
        if (hits > 0)
          Text('median pierce ${_n(mark['median_pierce_pct'], 3)}%   wick share ${_n(mark['median_wick_share'])}   volume x${_n(mark['median_volume_x'], 1)}', style: TextStyle(fontSize: 12, color: p.textPrimary)),
        _title(p, 'AFTER THE WICK (reversal side: ${_t(fwd['reversal_side'])})'),
        for (final h in _m(fwd['horizons']).keys) _hRow(p, h, _m(_m(fwd['horizons'])[h]), tipKey: 'tip_retaken'),
        _title(p, 'HYPOTHETICAL RE-ENTRY (${_t(re['side'])}, replay only)'),
        Text('wicks ${_int(re['wicks'])}:  entry ${_int(sc['ENTRY'])}  tip retaken first ${_int(sc['TIP_RETAKEN_FIRST'])}  no re-entry ${_int(sc['NO_REENTRY'])}  pending ${_int(sc['PENDING'])}  unavailable ${_int(sc['UNAVAILABLE'])}',
            style: TextStyle(fontSize: 12, color: p.textPrimary)),
        if (entries > 0)
          Text('median delay ${_n(re['median_delay_min'], 1)} min   median risk to the wick tip ${_n(re['median_risk_pct'], 3)}%${reFew ? '  (too few to say anything)' : ''}',
              style: TextStyle(fontSize: 12, color: reFew ? p.warning : p.textPrimary))
        else
          Text('no entry yet: nothing to measure (never 0)', style: TextStyle(fontSize: 12, color: p.textMuted)),
        for (final h in rhs) _hRow(p, h, _m(_m(re['horizons'])[h]), tipKey: 'stop_at_tip_hit'),
      ]),
    );
  }

  Widget _notes(AppPalette p, List<List<dynamic>> lists) {
    final notes = [for (final l in lists) ...l].map((e) => '$e').toSet().toList();
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('HOW TO READ THIS', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        const SizedBox(height: 4),
        for (final n in notes.take(14)) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('- $n', style: TextStyle(fontSize: 11.5, color: p.textSecondary))),
        Text('The re-entry is a replay of saved candles with a made-up rule: no fees, no slippage, no real stop. Medians are descriptions, not signals.', style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [
      const StudyVerdictHeader(
        cardId: 'stopwick',
        why: 'Stops often get swept by a wick that closes back inside.',
        what: 'What price did 15 min to 4 h after such a wick, against ordinary candles. A replay: no order, no prediction.',
      ),
    ];
    final marks = _m(d?['marks']);
    final fwd = _m(d?['forward']);
    final re = _m(d?['reentry']);
    final types = _l(marks['types']).whereType<Map>().toList();
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['marks'] is! Map || types.isEmpty) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else if (marks['ready'] != true) {
      kids.add(OWLCard(edge: p.warning, child: Text('No saved candles yet, so nothing can be marked. The collectors fill this in by themselves.', style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      kids.add(Text('Read-only replay. Stop-wicks of the last $_days day(s), ${_t(marks['symbols_scanned'])} coins scanned. No EMA, no indicator. No prediction, no win rate, no order.',
          style: TextStyle(fontSize: 12, color: p.textMuted)));
      kids.add(Row(children: [
        for (final n in const [1, 3, 7])
          Padding(
            padding: const EdgeInsets.only(right: 6),
            child: ChoiceChip(
              label: Text(n == 1 ? '1 day' : '$n days', style: const TextStyle(fontSize: 12)),
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
      ]));
      if (fwd['baseline'] is Map) kids.add(_baseCard(p, 'BASELINE after ordinary candles (no wick)', _l(fwd['horizons']).map((e) => '$e').toList(), _m(fwd['baseline'])));
      final fBy = <String, Map<String, dynamic>>{for (final t in _l(fwd['types']).whereType<Map>()) '${t['type']}': _m(t)};
      final rBy = <String, Map<String, dynamic>>{for (final t in _l(re['types']).whereType<Map>()) '${t['type']}': _m(t)};
      for (final t in types) {
        kids.add(_typeCard(p, _m(t), fBy['${t['type']}'] ?? const {}, rBy['${t['type']}'] ?? const {}));
      }
      if (re['baseline'] is Map) kids.add(_baseCard(p, 'BASELINE for the re-entry windows (ordinary candles)', _l(re['horizons']).map((e) => '$e').toList(), _m(re['baseline'])));
      kids.add(_notes(p, [_l(marks['notes']), _l(fwd['notes']), _l(re['notes'])]));
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
