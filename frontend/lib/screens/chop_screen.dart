import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_button.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';
import '../widgets/owl_status_pill.dart';
import '../widgets/owl_text_tabs.dart';
import 'chop_why_tab.dart';

// Part C4a (README_CHOP): shared helpers, top-level so C4b (chop_why_tab.dart) can copy the same style.
Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _ml(dynamic v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
String _s(dynamic v) => v == null ? '' : '$v';
String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';
String _px(dynamic v) {
  final x = _n(v);
  if (x == 0) return '-';
  return x >= 100 ? x.toStringAsFixed(2) : (x >= 1 ? x.toStringAsFixed(4) : x.toStringAsFixed(6));
}

/// Unix seconds (UTC) -> "dd Mon HH:mm" in IST (the app's day clock).
String _ist(dynamic ts) {
  if (ts is! num) return '';
  final d = DateTime.fromMillisecondsSinceEpoch(ts.toInt() * 1000, isUtc: true).add(const Duration(hours: 5, minutes: 30));
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  String two(int x) => x < 10 ? '0$x' : '$x';
  return '${two(d.day)} ${mon[d.month - 1]} ${two(d.hour)}:${two(d.minute)}';
}

/// Part C4a (README_CHOP): the b3 (Chop Bot) tab, part 1 of 2 = the TODAY tab. PAPER ONLY, nothing here can send an order.
/// Top: day profit for 5m (b3 live) and 15m (the C2 replay of today) apart, with Rally missed / Loss avoided. Then the open b3 trades, the closed trades and the decision list.
/// The second tab (WHY: Skip Ledger, rule report, weight suggestions with the OK button, b3 vs current bot) comes with C4b.
/// Reads GET /api/v2/chop, /api/v2/chop_log and /api/v2/chop_lab. The only write is the ON / OFF switch and the "Run 15m replay" button. Polls every 10 s only while open.
/// Dart NOT compiled (the APK build is the proof).
class ChopScreen extends StatefulWidget {
  const ChopScreen({super.key});

  @override
  State<ChopScreen> createState() => _ChopScreenState();
}

class _ChopScreenState extends State<ChopScreen> {
  // Last good replies are kept for the app session, so re-opening the tab shows data at once.
  static Map<String, dynamic> _cacheMain = {};
  static Map<String, dynamic> _cacheLog = {};
  static Map<String, dynamic> _cacheLab = {};
  Map<String, dynamic> _main = Map<String, dynamic>.from(_cacheMain);
  Map<String, dynamic> _log = Map<String, dynamic>.from(_cacheLog);
  Map<String, dynamic> _lab15 = Map<String, dynamic>.from(_cacheLab);
  String _err = '';
  bool _loaded = false;
  bool _polling = false;
  bool _switching = false;
  bool _starting = false;
  int _tab = 0;
  Timer? _timer;
  int _labTick = 0;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 10), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  bool _bad(Map<String, dynamic> r) => r['state'] != null || r['error'] != null;

  String _problem(Map<String, dynamic> r) {
    if (r['error'] != null) return 'The backend says: ${r['error']}';
    switch (_s(r['state'])) {
      case 'off':
        return 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder, then pull down.';
      case 'old':
        return 'This backend does not have the b3 routes yet. Install the newest zip and restart the backend.';
      default:
        return 'Cannot reach the backend right now. It will try again.';
    }
  }

  Future<void> _poll() async {
    if (!mounted || _polling) return;
    _polling = true;
    try {
      final pr = context.read<AppProvider>();
      final rs = await Future.wait([pr.fetchChop(), pr.fetchChopLog(limit: 50)]);
      // The 15m replay result is read once, then only while a job runs (or every 6th turn), because it is a heavy file read on the backend.
      Map<String, dynamic>? lab;
      final running = _m(_lab15['job'])['running'] == true;
      if (!_loaded || running || _labTick % 6 == 0) lab = await pr.fetchChopLab('15m', 'today');
      _labTick++;
      if (!mounted) return;
      setState(() {
        _loaded = true;
        if (_bad(rs[0])) {
          _err = _problem(rs[0]);
        } else {
          _err = '';
          _main = rs[0];
          _cacheMain = rs[0];
        }
        if (!_bad(rs[1])) {
          _log = rs[1];
          _cacheLog = rs[1];
        }
        if (lab != null && !_bad(lab)) {
          _lab15 = lab;
          _cacheLab = lab;
        }
      });
    } finally {
      _polling = false;
    }
  }

  Future<void> _toggle(bool on) async {
    if (_switching) return;
    setState(() => _switching = true);
    final r = await context.read<AppProvider>().postChopSwitch(on);
    if (!mounted) return;
    setState(() => _switching = false);
    if (r['on'] is bool) {
      setState(() => _main = {..._main, 'on': r['on']});
    } else {
      _snack('Could not change the switch. ${r['error'] ?? 'The backend did not answer.'}');
    }
    _poll();
  }

  Future<void> _runLab() async {
    if (_starting) return;
    setState(() => _starting = true);
    final r = await context.read<AppProvider>().postChopLab('15m', 'today');
    if (!mounted) return;
    setState(() => _starting = false);
    _snack(r['note'] != null ? '${r['note']}' : 'Could not start the replay.');
    _labTick = 0;
    _poll();
  }

  void _snack(String t) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t)));

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: () async {
        _labTick = 0;
        await _poll();
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, AppSpacing.xl),
        children: [
          _header(context),
          if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: AppSpacing.s), child: _notice(context, _err, bad: true)),
          OwlTextTabs(names: const ['Today', 'Why'], index: _tab, onChanged: (i) => setState(() => _tab = i)),
          if (!_loaded && _main.isEmpty)
            const Padding(padding: EdgeInsets.all(AppSpacing.xl), child: Center(child: CircularProgressIndicator()))
          else if (_tab == 0)
            ..._todayTab(context)
          else
            ..._whyTab(context),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------- header
  Widget _header(BuildContext context) {
    final p = context.palette;
    final on = _main['on'] == true;
    final turns = _n(_m(_main['loop'])['turns']).toInt();
    return OWLCard(
      edge: on ? p.profit : null,
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Text('b3 Chop Bot', style: context.type.section.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(width: AppSpacing.s),
              OWLStatusPill(text: on ? 'ON' : 'OFF', color: on ? p.profit : p.textMuted),
              const SizedBox(width: AppSpacing.xs),
              OWLStatusPill(text: 'PAPER', color: p.accent, showDot: false),
            ]),
            const SizedBox(height: 4),
            Text(
              on ? 'Taking only the clean signals on 5m. Checks so far: $turns' : 'OFF: no new decisions. Open trades and verdicts still finish.',
              style: context.type.metadata,
            ),
          ]),
        ),
        _switching
            ? const SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))
            : Switch(value: on, onChanged: _main.isEmpty ? null : _toggle),
      ]),
    );
  }

  Widget _notice(BuildContext context, String text, {bool bad = false}) {
    final p = context.palette;
    return OWLCard(edge: bad ? p.warning : null, padding: const EdgeInsets.all(AppSpacing.m), child: Text(text, style: context.type.secondary));
  }

  // ---------------------------------------------------------------- TODAY tab
  List<Widget> _todayTab(BuildContext context) {
    final open = _ml(_main['open_trades']);
    final closed = _ml(_log['closed_trades']);
    final dec = _ml(_log['decisions']);
    return [
      const OwlSectionLabel('Today'),
      _dayCard(context),
      OwlSectionLabel('Open b3 trades', note: '${open.length}'),
      open.isEmpty ? _notice(context, 'No open b3 trades right now.') : OwlListCard(children: [for (final t in open) _openRow(context, t)]),
      OwlSectionLabel('Closed trades', note: closed.isEmpty ? '' : 'last ${closed.length > 15 ? 15 : closed.length}'),
      closed.isEmpty ? _notice(context, 'No closed b3 trades yet.') : OwlListCard(children: [for (final t in closed.take(15)) _closedRow(context, t)]),
      OwlSectionLabel('Decisions', note: dec.isEmpty ? '' : 'last ${dec.length > 30 ? 30 : dec.length}'),
      dec.isEmpty
          ? _notice(context, 'No decisions yet. Switch b3 ON; it needs about 400 saved 5m candles per coin before it decides.')
          : OwlListCard(children: [for (final d in dec.take(30)) _decisionRow(context, d)]),
    ];
  }

  Widget _dayCard(BuildContext context) {
    final p = context.palette;
    final t = _m(_main['today']);
    final profit = _n(t['profit_usdt']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('5m  -  b3 live', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${_usdt(profit)} USDT', style: context.type.number.copyWith(color: profit >= 0 ? p.profit : p.loss)),
          const SizedBox(width: AppSpacing.m),
          Expanded(child: Text('${_n(t['closed']).toInt()} closed, ${_n(t['wins']).toInt()} won, ${_n(t['taken']).toInt()} taken, ${_n(t['skipped']).toInt()} skipped', style: context.type.metadata)),
        ]),
        const SizedBox(height: AppSpacing.s),
        Row(children: [
          Expanded(child: _stat(context, 'Rally missed', '${_usdt(_n(t['rally_missed_usdt']))} USDT', '${_n(t['rally_missed_n']).toInt()} skips', p.warning)),
          const SizedBox(width: AppSpacing.s),
          Expanded(child: _stat(context, 'Loss avoided', '${_usdt(_n(t['loss_avoided_usdt']))} USDT', '${_n(t['loss_avoided_n']).toInt()} skips', p.profit)),
        ]),
        if (_n(t['skips_waiting']) > 0)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('${_n(t['skips_waiting']).toInt()} skips are still waiting for their verdict.', style: context.type.metadata)),
        Padding(padding: const EdgeInsets.symmetric(vertical: AppSpacing.m), child: Divider(height: 1, color: p.border)),
        ..._lab15Block(context),
        const SizedBox(height: AppSpacing.s),
        Text('Skip money is what the skipped trade would have made at full size (10 USDT), after cost. Not a real trade. Day = UTC day.', style: context.type.caption),
      ]),
    );
  }

  /// The 15m half of the top card: the C2 replay of today (b3 itself runs on 5m only).
  List<Widget> _lab15Block(BuildContext context) {
    final p = context.palette;
    final job = _m(_lab15['job']);
    final res = _lab15['result'];
    final running = job['running'] == true;
    final head = Text('15m  -  replay of today', style: context.type.label.copyWith(fontWeight: FontWeight.w700));
    if (running) {
      return [head, const SizedBox(height: 6), Text('Replay running: ${_n(job['done']).toInt()} of ${_n(job['total']).toInt()} coins...', style: context.type.secondary)];
    }
    if (res is! Map) {
      final err = _s(job['error']);
      return [
        head,
        const SizedBox(height: 6),
        Text(err.isNotEmpty ? 'The last replay failed: $err' : 'Not run yet. The replay reads the saved candles and tests the filter on 15m. It changes nothing.', style: context.type.secondary),
        const SizedBox(height: AppSpacing.s),
        OWLButton(text: 'Run 15m replay (today)', isLoading: _starting, onPressed: _runLab, icon: Icons.play_arrow_rounded),
      ];
    }
    final r = _m(res);
    final vs = _ml(r['variants']);
    Map<String, dynamic> cur = {}, pick = {};
    for (final v in vs) {
      if (v['name'] == 'current') cur = v;
      if (v['name'] == r['best'] || (pick.isEmpty && v['name'] == 'filter 70/50')) pick = v;
    }
    if (pick.isEmpty || cur.isEmpty) return [head, const SizedBox(height: 6), Text('The replay has no result for today yet.', style: context.type.secondary)];
    final cp = _n(_m(cur['all'])['profit_usdt']), fp = _n(_m(pick['all'])['profit_usdt']);
    return [
      head,
      const SizedBox(height: 4),
      Row(children: [
        Expanded(child: _stat(context, 'Current bot', '${_usdt(cp)} USDT', '${_n(_m(cur['all'])['trades']).toInt()} trades', cp >= 0 ? p.profit : p.loss)),
        const SizedBox(width: AppSpacing.s),
        Expanded(child: _stat(context, _s(pick['name']), '${_usdt(fp)} USDT', '${_n(_m(pick['all'])['trades']).toInt()} trades', fp >= 0 ? p.profit : p.loss)),
      ]),
      const SizedBox(height: AppSpacing.s),
      Row(children: [
        Expanded(child: _stat(context, 'Rally missed', '${_usdt(_n(pick['rally_missed_usdt']))} USDT', 'capture ${_s(pick['rally_capture_pct'])}%', p.warning)),
        const SizedBox(width: AppSpacing.s),
        Expanded(child: _stat(context, 'Loss avoided', '${_usdt(_n(pick['loss_avoided_usdt']))} USDT', '${_s(pick['loss_avoided_pct'])}% of losers', p.profit)),
      ]),
      const SizedBox(height: 6),
      Row(children: [
        Expanded(child: Text(_s(pick['verdict']), style: context.type.metadata)),
        TextButton(onPressed: _starting ? null : _runLab, child: const Text('Run again')),
      ]),
    ];
  }

  Widget _stat(BuildContext context, String label, String value, String sub, Color c) {
    final p = context.palette;
    return Container(
      padding: const EdgeInsets.all(AppSpacing.s + 2),
      decoration: BoxDecoration(color: c.withOpacity(0.07), borderRadius: BorderRadius.circular(AppSpacing.radiusSmall), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata),
        const SizedBox(height: 2),
        FittedBox(fit: BoxFit.scaleDown, alignment: Alignment.centerLeft, child: Text(value, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: c))),
        if (sub.isNotEmpty) Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.caption),
      ]),
    );
  }

  // ---------------------------------------------------------------- rows
  Widget _rowBox(Widget child) => Padding(padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.rowPadV), child: child);

  Widget _openRow(BuildContext context, Map<String, dynamic> t) {
    final p = context.palette;
    final up = _n(t['upnl_usdt']);
    final hasPx = t['last_px'] != null;
    return _rowBox(Row(children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(_s(t['symbol']), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(width: 6),
            _sidePill(context, _s(t['side'])),
            const SizedBox(width: 4),
            Text(_s(t['size']), style: context.type.metadata),
          ]),
          const SizedBox(height: 2),
          Text('in ${_px(t['entry_px'])}  now ${hasPx ? _px(t['last_px']) : '-'}  stop ${_px(t['stop'])}  tp4 ${_px(t['tp4'])}', style: context.type.metadata),
          Text('since ${_ist(t['entry_ts'])}  score ${_n(t['score']).toStringAsFixed(0)}', style: context.type.caption),
        ]),
      ),
      if (hasPx)
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text('${_usdt(up)} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: up >= 0 ? p.profit : p.loss)),
          Text('${_usdt(_n(t['upnl_pct']))}%', style: context.type.metadata),
        ]),
    ]));
  }

  Widget _closedRow(BuildContext context, Map<String, dynamic> t) {
    final p = context.palette;
    final net = _n(t['net_usdt']);
    return _rowBox(Row(children: [
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Text(_s(t['symbol']), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(width: 6),
            _sidePill(context, _s(t['side'])),
            const SizedBox(width: 4),
            Text(_s(t['size']), style: context.type.metadata),
          ]),
          const SizedBox(height: 2),
          Text('${_s(t['exit_reason'])}  ${_ist(t['exit_ts'])}', style: context.type.metadata),
        ]),
      ),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text('${_usdt(net)} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: net >= 0 ? p.profit : p.loss)),
        Text('${_usdt(_n(t['net_pct']))}%', style: context.type.metadata),
      ]),
    ]));
  }

  Widget _decisionRow(BuildContext context, Map<String, dynamic> d) {
    final p = context.palette;
    final take = d['action'] == 'TAKE';
    final verdict = d['verdict'];
    final label = _s(d['v_label']);
    final vnet = d['v_net'];
    String vtext = '';
    if (!take && label == 'RALLY_MISSED') vtext = 'rally missed ${_usdt(_n(vnet))}%';
    if (!take && label == 'LOSS_AVOIDED') vtext = 'loss avoided ${_usdt(_n(vnet))}%';
    if (take && vnet != null && (label == 'WIN' || label == 'LOSS')) vtext = '${label == 'WIN' ? 'won' : 'lost'} ${_usdt(_n(vnet))}%';
    return _rowBox(Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Text(_s(d['symbol']), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(width: 6),
        if (_s(d['side']).isNotEmpty) _sidePill(context, _s(d['side'])),
        const SizedBox(width: 6),
        OWLStatusPill(text: take ? 'TAKE ${_s(d['size'])}' : 'SKIP', color: take ? p.profit : p.textMuted, showDot: false),
        if (d['late'] == 1) ...[const SizedBox(width: 4), OWLStatusPill(text: 'LATE', color: p.accent, showDot: false)],
        const Spacer(),
        Text('score ${_n(d['score']).toStringAsFixed(0)}', style: context.type.metadata),
      ]),
      const SizedBox(height: 3),
      Text('${_s(d['rule'])}: ${_s(d['why'])}', maxLines: 3, overflow: TextOverflow.ellipsis, style: context.type.secondary),
      const SizedBox(height: 3),
      Row(children: [
        Text(_ist(d['candle_ts']), style: context.type.caption),
        const Spacer(),
        if (verdict == 'right') OWLStatusPill(text: 'RIGHT${vtext.isEmpty ? '' : '  $vtext'}', color: p.profit, showDot: false),
        if (verdict == 'wrong') OWLStatusPill(text: 'WRONG${vtext.isEmpty ? '' : '  $vtext'}', color: p.loss, showDot: false),
        if (verdict == null && d['v_label'] != 'NA') Text('waiting for verdict', style: context.type.caption),
      ]),
    ]));
  }

  Widget _sidePill(BuildContext context, String side) {
    final p = context.palette;
    final buy = side == 'BUY';
    return OWLStatusPill(text: side, color: buy ? p.profit : p.loss, showDot: false);
  }

  // ---------------------------------------------------------------- WHY tab (C4b, screens/chop_why_tab.dart)
  List<Widget> _whyTab(BuildContext context) => [ChopWhyTab(main: _main)];
}
