import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import 'compare_table.dart';

/// Part 41 (FILE 49 helper): fills the shared CompareTable from routes that ALREADY exist. READ ONLY, no new backend, nothing is written or sent.
///   Main bot        = the app's status (today_pnl_usdt; the closed count of today is not in that answer, so Trades / Won print --)
///   Dual Bot paper  = GET /api/dual_desk (trades opened since 5:30 AM IST, summed over its own groups and 5m / 15m; same book)
///   Brain           = GET /api/v2/brain_dash (today: closed + net; the answer has no win count, so Won prints --)
///   Sniper LEARN    = GET /api/v2/sniper_learn (all LEARN paper trades so far, tiny size)
///   Sniper Replay   = GET /api/v2/sniper -> compare.sniper (replay on the unseen test days, simulated money)
/// Every row keeps its own period text; the table warns when they differ. Each source is loaded alone with a 12 s limit: a slow or broken one
/// only turns ITS row into a plain reason line, the other rows still show. Books are never added. Dart NOT compiled.

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
double? _n(Object? v) => v is num ? v.toDouble() : null;
int? _i(Object? v) => v is num ? v.toInt() : null;

const _day = 'Today (from 5:30 AM IST)';

/// Turns the {state: off / old / error / busy} words of the Sniper style fetches into one plain reason, or '' when the answer is a real one.
String _why(Map<String, dynamic> r, String what) {
  switch ('${r['state'] ?? ''}') {
    case 'off':
      return '$what is switched off in the backend.';
    case 'old':
      return '$what is not in this backend yet (old backend).';
    case 'error':
      return '$what could not be read right now.';
    case 'busy':
      return '$what is still being built. Refresh in a minute.';
  }
  return '';
}

CompareRow _bad(String book, String sub, String period, String note, {String state = 'error'}) =>
    CompareRow(book: book, sub: sub, period: period, state: state, note: note);

CompareRow mainRow(AppProvider pr) {
  const sub = 'paper, all coins';
  if (pr.statsMode == 'live') return _bad('Main bot', sub, _day, 'Live mode: the paper numbers are not shown here.', state: 'off');
  if (pr.status.isEmpty) return _bad('Main bot', sub, _day, 'Waiting for the bot status.', state: 'wait');
  final v = _n(pr.status['today_pnl_usdt']);
  if (v == null) return _bad('Main bot', sub, _day, 'No number from the bot yet.', state: 'wait');
  return CompareRow(book: 'Main bot', sub: sub, period: _day, net: v, note: 'Closed count of today is not in the status answer.');
}

CompareRow dualRow(Map<String, dynamic> r) {
  const sub = 'paper, learns from both indicators';
  if (r.isEmpty) return _bad('Dual Bot paper', sub, _day, 'Dual Bot numbers could not be read right now.');
  if ('${r['state']}' == 'error') return _bad('Dual Bot paper', sub, _day, 'Dual Bot numbers could not be read right now.');
  if ('${r['state']}' == 'none') return _bad('Dual Bot paper', sub, _day, 'No Dual Bot archive yet.', state: 'empty');
  final dt = _m(r['today']); // R16a: the one "Dual today" (alt coins, closed since 5:30 AM IST, from the permanent archive; BTC apart). Old backends have no 'today': the group sum below stays as the fallback.
  if ('${dt['state']}' == 'ok') {
    final al = _m(dt['alts']);
    final c = _i(al['closed']) ?? 0;
    if (c == 0) return _bad('Dual Bot paper', sub, _day, 'No trade closed today yet.', state: 'empty');
    return CompareRow(book: 'Dual Bot paper', sub: sub, period: _day, trades: c, wins: _i(al['wins']), net: _n(al['realized']), note: 'Alt coins only. BTC is kept apart. Same number as the Dual screen.');
  }
  var n = 0, w = 0;
  var net = 0.0;
  for (final g in _m(r['groups']).values) {
    for (final c in _m(g).values) {
      final d = _m(c);
      n += _i(d['n']) ?? 0;
      w += _i(d['wins']) ?? 0;
      net += _n(d['net']) ?? 0;
    }
  }
  if (n == 0) return _bad('Dual Bot paper', sub, _day, 'No trade closed today yet.', state: 'empty');
  return CompareRow(book: 'Dual Bot paper', sub: sub, period: _day, trades: n, wins: w, net: net, note: 'BTC and alt coins at their own sizes.');
}

CompareRow brainRow(Map<String, dynamic> r) {
  const sub = 'paper pretend trades';
  final w = _why(r, 'Brain dashboard');
  if (w.isNotEmpty) return _bad('Brain', sub, _day, w, state: '${r['state']}' == 'busy' ? 'wait' : ('${r['state']}' == 'error' ? 'error' : 'off'));
  if (r['ready'] != true) return _bad('Brain', sub, _day, 'No Brain trade saved yet.', state: 'empty');
  final t = _m(r['today']);
  final closed = _i(t['closed']) ?? 0;
  if (closed == 0) return _bad('Brain', sub, _day, 'No Brain trade closed today yet.', state: 'empty');
  return CompareRow(book: 'Brain', sub: sub, period: _day, trades: closed, net: _n(t['net_usdt']), note: 'The answer has no win count.');
}

CompareRow learnRow(Map<String, dynamic> r) {
  const sub = 'paper, tiny size';
  const per = 'All LEARN trades so far';
  final w = _why(r, 'Sniper LEARN');
  if (w.isNotEmpty) return _bad('Sniper LEARN', sub, per, w, state: 'off');
  final pg = _m(_m(r['learn'])['progress']);
  final n = _i(pg['n']) ?? 0;
  if (n == 0) return _bad('Sniper LEARN', sub, per, 'No LEARN trade closed yet.', state: 'empty');
  return CompareRow(book: 'Sniper LEARN', sub: sub, period: per, trades: n, wins: _i(pg['wins']), net: _n(pg['net_usdt']), note: n < 30 ? 'Only $n of 30 trades: too early for a verdict.' : '');
}

CompareRow replayRow(Map<String, dynamic> r) {
  const sub = 'replay on unseen days';
  final w = _why(r, 'Sniper replay');
  if (w.isNotEmpty) return _bad('Sniper Replay', sub, 'Test days', w, state: 'off');
  final c = _m(r['compare']);
  final s = _m(c['sniper']);
  if (c.isEmpty || c['state'] != null || s.isEmpty) return _bad('Sniper Replay', sub, 'Test days', 'No replay result in this backend answer.', state: 'empty');
  final n = _i(s['trades']) ?? 0;
  final days = _i(s['days']) ?? 0;
  final per = days > 0 ? 'Last $days test days' : 'Test days';
  if (n == 0) return _bad('Sniper Replay', sub, per, 'The model has no test trade yet.', state: 'empty');
  return CompareRow(book: 'Sniper Replay', sub: sub, period: per, trades: n, net: _n(s['net_usdt']), simulated: true, note: 'Simulated 10 USDT base, fees included.');
}

class CompareBooks extends StatefulWidget {
  const CompareBooks({super.key});

  @override
  State<CompareBooks> createState() => _CompareBooksState();
}

class _CompareBooksState extends State<CompareBooks> {
  static const _limit = Duration(seconds: 12);
  Map<String, dynamic>? _dual, _brain, _learn, _replay; // null = still loading
  int _gen = 0; // a late answer of an older refresh is thrown away

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<Map<String, dynamic>> _safe(Future<Map<String, dynamic>> f) async {
    try {
      return await f.timeout(_limit);
    } catch (_) {
      return {'state': 'error'};
    }
  }

  Future<Map<String, dynamic>> _dualGet(AppProvider pr) async {
    final res = await http.get(Uri.parse('${pr.baseUrl}/api/dual_desk'));
    if (res.statusCode != 200) return {'state': 'error'};
    final d = jsonDecode(res.body);
    return d is Map ? Map<String, dynamic>.from(d) : {'state': 'error'};
  }

  void _load() {
    final pr = context.read<AppProvider>();
    final g = ++_gen;
    setState(() => _dual = _brain = _learn = _replay = null);
    void put(void Function(Map<String, dynamic>) set, Future<Map<String, dynamic>> f) => _safe(f).then((r) {
          if (mounted && g == _gen) setState(() => set(r));
        });
    put((r) => _dual = r, _dualGet(pr));
    put((r) => _brain = r, pr.fetchBrainDash());
    put((r) => _learn = r, pr.fetchSniperLearn());
    put((r) => _replay = r, pr.fetchSniper());
  }

  CompareRow _wait(String book, String period) => CompareRow(book: book, period: period, state: 'wait', note: 'Loading...');

  @override
  Widget build(BuildContext context) {
    final pr = context.read<AppProvider>();
    final rows = <CompareRow>[
      mainRow(pr),
      _dual == null ? _wait('Dual Bot paper', _day) : dualRow(_dual!),
      _brain == null ? _wait('Brain', _day) : brainRow(_brain!),
      _learn == null ? _wait('Sniper LEARN', 'All LEARN trades so far') : learnRow(_learn!),
      _replay == null ? _wait('Sniper Replay', 'Test days') : replayRow(_replay!),
    ];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: CompareTable(title: 'Books side by side', rows: rows, onRetry: _load),
    );
  }
}
