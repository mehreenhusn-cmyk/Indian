import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_button.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_row.dart';
import '../widgets/owl_sentence.dart';

Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _ml(dynamic v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
double _n(dynamic v) => v is num ? v.toDouble() : 0.0;
String _s(dynamic v) => v == null ? '' : '$v';
String _usdt(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

/// Durations over 60 min are written as hours + minutes (owner rule), never "220 min".
String _dur(num sec) {
  final mins = (sec / 60).round();
  if (mins < 1) return '${sec.round()} s';
  if (mins < 60) return '$mins min';
  final h = mins ~/ 60, m = mins % 60;
  return m == 0 ? '$h h' : '$h h $m min';
}

String _ago(dynamic ts) {
  if (ts is! num) return 'never';
  final sec = DateTime.now().millisecondsSinceEpoch / 1000 - ts;
  if (sec < 60) return 'just now';
  return '${_dur(sec)} ago';
}

/// Unix seconds (UTC) -> "dd Mon HH:mm" in IST (the app's day clock).
String _ist(dynamic ts) {
  if (ts is! num) return _s(ts);
  final d = DateTime.fromMillisecondsSinceEpoch(ts.toInt() * 1000, isUtc: true).add(const Duration(hours: 5, minutes: 30));
  const mon = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  String two(int x) => x < 10 ? '0$x' : '$x';
  return '${two(d.day)} ${mon[d.month - 1]} ${two(d.hour)}:${two(d.minute)}';
}

/// Part 8A-2 (README_FILTER): the OVERVIEW tab of the Filter Lab. Four blocks, top to bottom:
/// 1) GATE: status in words, the OFF / LOG / BLOCK switch (BLOCK asks first, it is the only thing here that changes trading), counters since the backend started.
/// 2) RULES: the rules the gate built by itself from the Part 4 PASS filters, with TRAIN / TEST numbers and LUCK %, and the numbers of all rules together.
/// 3) STUDY RUN: is it running, which Part, how long each Part took, what failed, run-now button, auto-run ON / OFF, and when each Part's summary was saved.
/// 4) GATE LOG: the last lines of what the gate hit (log mode = would block, block mode = blocked).
/// Data comes from the shell (filter_lab_screen.dart); this tab only shows it and sends the two writes (gate mode, run now). Dart NOT compiled.
class FilterOverviewTab extends StatefulWidget {
  final Map<String, dynamic> data; // GET /api/v2/filter
  final Map<String, dynamic> rules; // GET /api/v2/filter_rules (or {state: none})
  final Future<void> Function() onReload;

  const FilterOverviewTab({super.key, required this.data, required this.rules, required this.onReload});

  @override
  State<FilterOverviewTab> createState() => _FilterOverviewTabState();
}

class _FilterOverviewTabState extends State<FilterOverviewTab> {
  bool _switching = false;
  bool _starting = false;

  void _snack(String t) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(t)));

  String _modeNote(String mode) {
    switch (mode) {
      case 'log':
        return 'LOG: the gate only writes what it WOULD block. No trade is stopped.';
      case 'block':
        return 'BLOCK: the gate skips the entry when a rule hits. Current bot (b1), 5m only.';
      default:
        return 'OFF: nothing runs. The bot trades exactly as before.';
    }
  }

  Future<void> _setMode(String mode, String current) async {
    if (_switching || mode == current) return;
    if (mode == 'block') {
      final ok = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          title: const Text('Switch the gate to BLOCK?'),
          content: const Text('From now on the current bot (b1, 5m) will SKIP an entry when a rule hits. This changes trading. Use LOG first to see what it would block.'),
          actions: [
            TextButton(onPressed: () => Navigator.of(c).pop(false), child: const Text('Cancel')),
            TextButton(onPressed: () => Navigator.of(c).pop(true), child: const Text('Yes, BLOCK')),
          ],
        ),
      );
      if (ok != true || !mounted) return;
    }
    setState(() => _switching = true);
    final r = await context.read<AppProvider>().postFilterGate(mode);
    if (!mounted) return;
    setState(() => _switching = false);
    if (r['mode'] != null) {
      _snack(_s(r['note']).isEmpty ? 'Gate is ${mode.toUpperCase()}.' : _s(r['note']));
    } else {
      _snack('Could not change the gate. ${r['error'] ?? 'The backend did not answer.'}');
    }
    await widget.onReload();
  }

  Future<void> _runNow() async {
    if (_starting) return;
    setState(() => _starting = true);
    final r = await context.read<AppProvider>().postFilterRun();
    if (!mounted) return;
    setState(() => _starting = false);
    _snack(r['note'] != null ? _s(r['note']) : 'Could not start the study run.');
    await widget.onReload();
  }

  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      const OwlSectionLabel('Gate (Part 7)'),
      _gateCard(context),
      ..._rulesBlock(context),
      ..._runBlock(context),
      ..._logBlock(context),
      const SizedBox(height: AppSpacing.s),
      Text('Day = crypto day, 00:00 UTC (5:30 AM IST). Rules are measured on MAIN 5m paper trades only. A rule is a candidate that passed TRAIN and TEST, not a promise.', style: context.type.caption),
    ]);
  }

  // ---------------------------------------------------------------- 1) GATE
  Widget _gateCard(BuildContext context) {
    final p = context.palette;
    final g = _m(widget.data['gate']);
    final mode = _s(g['mode']).isEmpty ? 'off' : _s(g['mode']);
    final status = _s(g['status']);
    final nRules = _n(g['rules']).toInt();
    final err = _s(g['last_error']);
    final noRules = status.startsWith('NO_RULES');
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(_modeNote(mode), style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: AppSpacing.s),
        _switching
            ? const Padding(padding: EdgeInsets.symmetric(vertical: 12), child: Center(child: SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2))))
            : OwlSegmented(items: const [('off', 'OFF'), ('log', 'LOG'), ('block', 'BLOCK')], active: mode, onPick: (k) => _setMode(k, mode)),
        Text('Rules: $nRules. ${status.isEmpty ? 'No rules file yet.' : status}${g['made_utc'] != null ? ' Made ${_s(g['made_utc'])}.' : ''}', style: context.type.secondary),
        if (mode != 'off' && (nRules == 0 || noRules))
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('No rule passed yet, so the gate does nothing. It rebuilds the rules by itself (max once per 6 h, a few minutes).', style: context.type.metadata.copyWith(color: p.warning))),
        if (mode == 'off')
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('Rules are only built after the gate is LOG or BLOCK. Start with LOG.', style: context.type.metadata)),
        Padding(padding: const EdgeInsets.symmetric(vertical: AppSpacing.m), child: Divider(height: 1, color: p.border)),
        Row(children: [
          Expanded(child: _stat(context, 'Checked', '${_n(g['signals_checked']).toInt()}', 'signals since start', p.textSecondary)),
          const SizedBox(width: AppSpacing.s),
          Expanded(child: _stat(context, mode == 'block' ? 'Blocked' : 'Would block', '${_n(g['signals_hit']).toInt()}', 'rule hits', mode == 'block' ? p.warning : p.accent)),
          const SizedBox(width: AppSpacing.s),
          Expanded(child: _stat(context, 'No numbers', '${_n(g['signals_skipped_no_numbers']).toInt()}', 'taken anyway', p.textMuted)),
        ]),
        if (err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text('Last gate error: $err (the trade was taken, the gate never blocks on an error).', style: context.type.metadata.copyWith(color: p.warning))),
      ]),
    );
  }

  Widget _stat(BuildContext context, String label, String value, String sub, Color c) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
      const SizedBox(height: 2),
      Text(value, style: context.type.number.copyWith(color: c)),
      Text(sub, style: context.type.caption),
    ]);
  }

  // ---------------------------------------------------------------- 2) RULES
  List<Widget> _rulesBlock(BuildContext context) {
    final p = context.palette;
    final r = widget.rules;
    final list = _ml(r['rules']);
    final comb = _m(r['combined']);
    final te = _m(comb['test']), tr = _m(comb['train']);
    final head = OwlSectionLabel('Rules the gate uses', note: list.isEmpty ? '' : '${list.length}');
    if (list.isEmpty) {
      final st = _s(r['status']);
      return [
        head,
        OWLCard(
          padding: const EdgeInsets.all(AppSpacing.m),
          child: Text(st.isNotEmpty ? st : 'No rules file yet. It is made after the gate is LOG or BLOCK (a few minutes). Nothing passing is a normal answer: then the gate does nothing.', style: context.type.secondary),
        ),
      ];
    }
    final luck = comb['luck_random_as_good_pct'];
    return [
      head,
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('All rules together, on TEST (the last 40% of trades, never used to pick a rule)', style: context.type.label.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(
            'Blocks ${_n(te['blocked']).toInt()} trades${te['blocked_pct'] != null ? ' (${_n(te['blocked_pct']).toStringAsFixed(1)}%)' : ''}, cuts ${_n(te['losers_cut']).toInt()} losers and ${_n(te['winners_cut']).toInt()} winners, saves ${_usdt(_n(te['net_gain']))} USDT, loses ${_n(te['moves_lost']).toInt()} big moves.',
            style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: _n(te['net_gain']) > 0 ? p.profit : p.textPrimary),
          ),
          const SizedBox(height: 4),
          Text('TRAIN: saves ${_usdt(_n(tr['net_gain']))} USDT.${luck is num ? ' Luck: a random block of the same size does as well in ${_n(luck).toStringAsFixed(0)}% of tries.' : ''}', style: context.type.metadata),
        ]),
      ),
      const SizedBox(height: AppSpacing.s),
      OwlListCard(children: [for (final x in list) _ruleRow(context, x)]),
    ];
  }

  Widget _ruleRow(BuildContext context, Map<String, dynamic> x) {
    final p = context.palette;
    final te = _m(x['test']), tr = _m(x['train']);
    final gain = _n(te['net_gain']);
    final luck = x['luck_random_as_good_pct'];
    return OwlRow(
      title: _s(x['name']).isEmpty ? _s(x['id']) : _s(x['name']),
      sub: 'TEST blocks ${_n(te['blocked']).toInt()}, TRAIN ${_usdt(_n(tr['net_gain']))}${luck is num ? ', luck ${_n(luck).toStringAsFixed(0)}%' : ''}',
      trailing: Text('${_usdt(gain)} USDT', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, color: gain >= 0 ? p.profit : p.loss)),
    );
  }

  // ---------------------------------------------------------------- 3) STUDY RUN
  List<Widget> _runBlock(BuildContext context) {
    final p = context.palette;
    final run = _m(widget.data['run']);
    final parts = _ml(widget.data['parts']);
    final running = run['running'] == true;
    final done = _ml(run['done']);
    final failed = _ml(run['failed']);
    final auto = widget.data['auto'] != false;
    final labels = {for (final x in parts) _s(x['id']): _s(x['label'])};
    final cur = _s(run['current']);
    final finished = run['finished_ts'];
    final String line;
    if (running) {
      line = 'Running now: ${labels[cur] ?? (cur.isEmpty ? 'starting' : cur)}. ${done.length} of ${parts.length} Parts done. It runs at low priority.';
    } else if (finished is num) {
      line = 'Last run finished ${_ago(finished)}: ${done.length} of ${parts.length} Parts OK${failed.isEmpty ? '' : ', ${failed.length} failed'}.';
    } else {
      line = 'The study has not run yet. It starts by itself (first wait 5 min after the backend starts) or press the button.';
    }
    return [
      OwlSectionLabel('Study run', note: auto ? 'auto every 24 h' : 'auto OFF'),
      OWLCard(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(line, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          if (failed.isNotEmpty) ...[
            const SizedBox(height: 6),
            for (final f in failed) Text('${_s(f['label']).isEmpty ? _s(f['id']) : _s(f['label'])} failed: ${_s(f['why'])}', style: context.type.metadata.copyWith(color: p.warning)),
          ],
          const SizedBox(height: AppSpacing.s),
          OWLButton(text: running ? 'Study is running' : 'Run study now', isLoading: _starting, onPressed: running ? null : _runNow, icon: Icons.play_arrow_rounded),
          const SizedBox(height: 6),
          Text('Read only: it reads saved trades and candles and writes only its own summary files.', style: context.type.caption),
        ]),
      ),
      const SizedBox(height: AppSpacing.s),
      OwlListCard(children: [for (final x in parts) _partRow(context, x, done, failed, running ? cur : '')]),
    ];
  }

  Widget _partRow(BuildContext context, Map<String, dynamic> x, List<Map<String, dynamic>> done, List<Map<String, dynamic>> failed, String current) {
    final p = context.palette;
    final id = _s(x['id']);
    final saved = x['saved_ts'];
    Map<String, dynamic> d = {};
    for (final e in done) {
      if (_s(e['id']) == id) d = e;
    }
    final isFailed = failed.any((e) => _s(e['id']) == id);
    final isCur = current == id;
    final sub = saved is num ? 'Saved ${_ago(saved)}${d['seconds'] is num ? ', took ${_dur(_n(d['seconds']))}' : ''}' : 'Not made yet';
    final String tag;
    final Color c;
    if (isCur) {
      tag = 'RUNNING';
      c = p.accent;
    } else if (isFailed) {
      tag = 'FAILED';
      c = p.warning;
    } else if (saved is num) {
      tag = 'READY';
      c = p.profit;
    } else {
      tag = 'WAITING';
      c = p.textMuted;
    }
    return OwlRow(title: _s(x['label']).isEmpty ? id : _s(x['label']), sub: sub, trailing: Text(tag, style: context.type.metadata.copyWith(color: c, fontWeight: FontWeight.w700)));
  }

  // ---------------------------------------------------------------- 4) GATE LOG
  List<Widget> _logBlock(BuildContext context) {
    final log = _ml(widget.data['gate_log']).reversed.toList(); // newest first
    final p = context.palette;
    return [
      OwlSectionLabel('Gate log', note: log.isEmpty ? '' : 'last ${log.length}'),
      if (log.isEmpty)
        OWLCard(padding: const EdgeInsets.all(AppSpacing.m), child: Text('Nothing yet. A line is written each time a rule hits a b1 signal on 5m (LOG: would block, BLOCK: blocked).', style: context.type.secondary))
      else
        OwlListCard(children: [
          for (final x in log)
            OwlRow(
              title: '${_s(x['sym'])} ${_s(x['side'])}',
              sub: '${_ist(x['t'])}  -  ${_ruleText(x['rules'])}',
              trailing: Text(x['blocked'] == true ? 'BLOCKED' : 'WOULD BLOCK', style: context.type.metadata.copyWith(color: x['blocked'] == true ? p.warning : p.accent, fontWeight: FontWeight.w700)),
            ),
        ]),
    ];
  }

  String _ruleText(dynamic v) {
    if (v is List) return v.map((e) => '$e').join(', ');
    return _s(v);
  }
}
