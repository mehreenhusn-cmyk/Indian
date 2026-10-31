import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 46 (EMA-free Setup Finder 4 of 4): the SETUP FINDER on a screen. Read-only: it only asks the backend for /api/v2/setups and
/// /api/v2/setups_forward (Parts 43-45), draws the answers and changes nothing (no setting, no position, no order, no file).
/// For each of the 7 formation types (no EMA, no indicator: only price and volume) it shows how many times the formation was marked and,
/// for 15 min, 30 min, 1 h, 4 h, 1 d and 7 d after it, the MEDIAN end change, the median highest move up and the median lowest move down,
/// with n, next to the BASELINE of ordinary candles. A formation only means something if it differs from the baseline AND n is big.
/// Rules shown on screen: a window that is not over says PENDING, a window with a missing candle says UNAVAILABLE, never 0; fewer than
/// 30 cases says "too few"; no prediction, no win rate, no order. Pull down to refresh.
class SetupScreen extends StatefulWidget {
  const SetupScreen({super.key});

  @override
  State<SetupScreen> createState() => _SetupScreenState();
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];
String _t(Object? v) => (v == null || '$v'.trim().isEmpty) ? '--' : '$v';
String _pct(Object? v) => v is num ? '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%' : 'UNKNOWN';
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
    case '1d':
      return '1 day';
    case '7d':
      return '7 days';
    default:
      return h;
  }
}

String _problem(Object? state) {
  switch (state) {
    case 'off':
      return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then pull down to refresh.';
    case 'old':
      return 'This backend does not have the Setup routes yet. Install the newest zip, restart the backend, then pull down.';
    default:
      return 'Cannot reach the backend right now. Pull down to try again.';
  }
}

class _SetupScreenState extends State<SetupScreen> {
  Map<String, dynamic>? _data;
  bool _loading = true;
  int _days = 1;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchSetups(_days);
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

  /// One horizon row: "n 42   end +0.12%   up +0.40%   down 0.30%" or the honest reason there is no number.
  Widget _hRow(AppPalette p, String h, Map<String, dynamic> c) {
    final n = c['n'] is num ? (c['n'] as num).toInt() : 0;
    final pend = c['pending'] ?? 0;
    final un = c['unavailable'] ?? 0;
    final String body;
    if (n == 0) {
      body = 'no finished window yet (PENDING $pend, UNAVAILABLE $un)';
    } else {
      body = 'end ${_pct(c['median_end_pct'])}  up ${_pct(c['median_max_up_pct'])}  down ${_pct(c['median_max_down_pct'])}';
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

  Widget _baselineCard(AppPalette p, List<String> hs, Map<String, dynamic> base) => OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('BASELINE (ordinary candles, no formation)', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          for (final h in hs) _hRow(p, h, _m(base[h])),
        ]),
      );

  Widget _typeCard(AppPalette p, List<String> hs, Map<String, dynamic> t, Map<String, dynamic> hits) {
    final dir = _t(t['direction']);
    final hitN = hits['hits'] is num ? (hits['hits'] as num).toInt() : 0;
    final few = '${hits['note'] ?? ''}'.isNotEmpty;
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(_t(t['type']), style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          _chip(dir == 'NONE' ? 'NO DIRECTION' : dir, dir == 'UP' ? p.accent : (dir == 'DOWN' ? p.purple : p.textMuted)),
        ]),
        const SizedBox(height: 4),
        Text('Marked $hitN times${few ? '  (too few to say anything)' : ''}', style: TextStyle(fontSize: 12, color: few ? p.warning : p.textSecondary)),
        const SizedBox(height: 4),
        for (final h in hs) _hRow(p, h, _m(_m(t['horizons'])[h])),
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
        Text('end = change of the close at the end of the window, up / down = highest / lowest point inside it, all from the close of the formation candle. These are medians of what the saved candles did, not signals.',
            style: TextStyle(fontSize: 11, color: p.textMuted)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final List<Widget> kids = [];
    final fwd = _m(d?['forward']);
    final types = _l(fwd['types']).whereType<Map>().toList();
    if (_loading && d == null) {
      kids.add(const Padding(padding: EdgeInsets.only(top: 80), child: Center(child: CircularProgressIndicator())));
    } else if (d == null || d['forward'] is! Map || types.isEmpty) {
      kids.add(OWLCard(edge: p.warning, child: Text(_problem(d?['state']), style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else if (fwd['ready'] != true) {
      kids.add(OWLCard(edge: p.warning, child: Text('No saved candles yet, so nothing can be marked. The collectors fill this in by themselves.', style: TextStyle(fontSize: 13, color: p.textPrimary))));
    } else {
      final hs = _l(fwd['horizons']).map((e) => '$e').toList();
      final hitsBy = <String, Map<String, dynamic>>{for (final t in _l(_m(d['setups'])['types']).whereType<Map>()) '${t['type']}': _m(t)};
      kids.add(Text('Read-only. Formations of the last $_days day(s), ${_t(fwd['symbols_scanned'])} coins scanned. No EMA, no indicator. No prediction, no win rate.',
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
      kids.add(_baselineCard(p, hs, _m(fwd['baseline'])));
      for (final t in types) {
        kids.add(_typeCard(p, hs, _m(t), hitsBy['${t['type']}'] ?? const {}));
      }
      kids.add(_notes(p, _l(fwd['notes']), _l(_m(d['setups'])['notes'])));
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
