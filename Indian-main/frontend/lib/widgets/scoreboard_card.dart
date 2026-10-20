import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Final Scoreboard (crypto Doctor, top). One result per idea: Strategy Lab replay (3m / 5m / 15m) and the bot's
/// saved trades side by side. Reads only /api/scoreboard. Nothing here changes the bot.
class ScoreboardCard extends StatefulWidget {
  const ScoreboardCard({super.key});

  @override
  State<ScoreboardCard> createState() => _ScoreboardCardState();
}

class _ScoreboardCardState extends State<ScoreboardCard> {
  Map<String, dynamic> _d = {};
  String _err = '';
  bool _loading = true;
  bool _starting = false;
  final Set<String> _open = {};
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 8), (_) {
      if (_d['replay_running'] == true) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final res = await http.get(Uri.parse('$base/api/scoreboard')).timeout(const Duration(seconds: 25));
      if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is! Map) throw 'unexpected reply';
      if (mounted) {
        setState(() {
          _d = Map<String, dynamic>.from(m);
          _err = '${_d['error'] ?? ''}';
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _err = '$e';
          _loading = false;
        });
      }
    }
  }

  Future<void> _run() async {
    setState(() => _starting = true);
    try {
      final base = context.read<AppProvider>().baseUrl;
      await http.get(Uri.parse('$base/api/variant_lab?start=1&days=14')).timeout(const Duration(seconds: 20));
    } catch (_) {}
    await _load();
    if (mounted) setState(() => _starting = false);
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static String _f(double v) => (v > 0 ? '+' : '') + v.toStringAsFixed(0);
  static List<Map<String, dynamic>> _list(dynamic v) =>
      (v is List) ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final running = _d['replay_running'] == true;
    final headline = (_d['headline'] is List) ? (_d['headline'] as List).map((e) => '$e').toList() : <String>[];
    final groups = _list(_d['groups']);
    final byTf = _list(_d['by_tf']);
    final tfsDone = (_d['replay_tfs'] is List) ? (_d['replay_tfs'] as List).map((e) => '$e').toList() : <String>[];
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.accent.withOpacity(0.55)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.scoreboard_outlined, size: 18, color: p.accent),
          const SizedBox(width: 8),
          Expanded(child: Text('Final scoreboard', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
          TextButton(
            onPressed: running || _starting ? null : _run,
            child: Text(running ? 'Running...' : (tfsDone.isEmpty ? 'Run tests' : 'Run again')),
          ),
        ]),
        Text('Does the idea make real money after fees? Numbers are the idea\'s own result, not "better than bot".', style: context.type.metadata),
        if (running) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
          const SizedBox(height: 4),
          Text('${_d['replay_progress'] ?? ''}  (a few minutes, you can leave this screen)', style: context.type.metadata),
        ],
        if (_loading) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
        if (_err.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
        if (_d['answer_box'] is Map) _answerBox(context, Map<String, dynamic>.from(_d['answer_box'] as Map)),
        if (groups.isNotEmpty) ...[
          const SizedBox(height: 10),
          _tableHeader(context),
          _botRow(context, Map<String, dynamic>.from((_d['bot_row'] as Map?) ?? {}), tfsDone),
          if (_list(_d['profit_ideas']).isNotEmpty) ...[
            const SizedBox(height: 8),
            _label(context, 'MADE PROFIT'),
            for (final r in _list(_d['profit_ideas'])) _tableRow(context, r, tfsDone, 'top'),
          ] else if (_list(_d['closest']).isNotEmpty) ...[
            const SizedBox(height: 8),
            _label(context, 'CLOSEST 3 (all still losing)'),
            for (final r in _list(_d['closest'])) _tableRow(context, r, tfsDone, 'top'),
          ],
        ],
        if (_list(_d['bot_by_day']).isNotEmpty) _dayFold(context, 'Day by day: normal bot', 'Last 7 days of your saved trades', [
          for (final x in _list(_d['bot_by_day'])) Text('${x['day']}:  ${x['bot_n']} trades, net ${_f(_n(x['bot_net']))}', style: context.type.metadata),
        ]),
        if (groups.isNotEmpty)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('All ideas (${_d['total'] ?? ''})', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
              subtitle: Text('Grouped. Tap an idea to see what it does and day by day.', style: context.type.metadata),
              children: [
                for (final h in headline)
                  Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(h, style: context.type.metadata.copyWith(height: 1.35))),
                if (byTf.isNotEmpty) ...[
                  const SizedBox(height: 6),
                  _label(context, 'BY TIMEFRAME (replay)'),
                  for (final t in byTf) _tfLine(context, t),
                ],
                const SizedBox(height: 6),
                _tableHeader(context),
                for (final g in groups) ...[
                  const SizedBox(height: 8),
                  _groupHead(context, g, _list(_d['counts'])),
                  for (final r in _list(g['rows'])) _tableRow(context, r, tfsDone, 'all'),
                ],
              ],
            ),
          ),
        if (_d['sd_length'] is Map) _sdBlock(context, Map<String, dynamic>.from(_d['sd_length'] as Map)),
        if (groups.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text('ROI points after fees. PROFIT = the idea\'s own result is above zero. Saved = your closed trades (n/a = not enough data). Try a winner on paper first.',
                style: context.type.metadata),
          ),
      ]),
    );
  }

  Widget _answerBox(BuildContext context, Map<String, dynamic> a) {
    final p = context.palette;
    final k = '${a['kind']}';
    final c = k == 'profit' ? p.profit : (k == 'none' ? p.warning : p.textSecondary);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(10), border: Border.all(color: c.withOpacity(0.5))),
      child: Text('${a['text']}', style: context.type.secondary.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700, height: 1.35)),
    );
  }

  Widget _dayFold(BuildContext context, String title, String sub, List<Widget> kids) {
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: const EdgeInsets.only(bottom: 8),
        expandedCrossAxisAlignment: CrossAxisAlignment.start,
        title: Text(title, style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
        subtitle: Text(sub, style: context.type.metadata),
        children: kids,
      ),
    );
  }

  Widget _label(BuildContext context, String t) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text(t, style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.8, color: p.textSecondary)),
    );
  }

  Widget _tfLine(BuildContext context, Map<String, dynamic> t) {
    final p = context.palette;
    final b = Map<String, dynamic>.from((t['best'] as Map?) ?? {});
    final w = Map<String, dynamic>.from((t['worst'] as Map?) ?? {});
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text.rich(TextSpan(style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35), children: [
        TextSpan(text: '${t['tf']}: ', style: const TextStyle(fontWeight: FontWeight.w800)),
        const TextSpan(text: 'best '),
        TextSpan(text: '${b['title']} ${_f(_n(b['vs_bot']))}', style: TextStyle(color: p.profit)),
        const TextSpan(text: ', worst '),
        TextSpan(text: '${w['title']} ${_f(_n(w['vs_bot']))}', style: TextStyle(color: p.loss)),
      ])),
    );
  }

  static const _wIdea = 5, _wTf = 2, _wSaved = 2, _wVerdict = 3;

  Widget _cell(BuildContext context, String text, {Color? color, bool bold = false, int flex = _wTf, TextAlign align = TextAlign.right}) {
    final p = context.palette;
    return Expanded(
      flex: flex,
      child: Align(
        alignment: align == TextAlign.right ? Alignment.centerRight : Alignment.centerLeft,
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(text, maxLines: 1, style: context.type.metadata.copyWith(color: color ?? p.textPrimary, fontWeight: bold ? FontWeight.w800 : FontWeight.w600, fontSize: 12)),
        ),
      ),
    );
  }

  Widget _tableHeader(BuildContext context) {
    final p = context.palette;
    Widget h(String t, int flex, {bool left = false}) => Expanded(
        flex: flex,
        child: Text(t, textAlign: left ? TextAlign.left : TextAlign.right, style: context.type.label.copyWith(color: p.textSecondary, fontWeight: FontWeight.w800, fontSize: 11)));
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.textSecondary.withOpacity(0.35)))),
      child: Row(children: [h('Idea', _wIdea, left: true), h('3m', _wTf), h('5m', _wTf), h('15m', _wTf), h('Saved', _wSaved), h('Answer', _wVerdict)]),
    );
  }

  Widget _botRow(BuildContext context, Map<String, dynamic> bot, List<String> tfsDone) {
    final p = context.palette;
    final rep = (bot['replay'] is Map) ? Map<String, dynamic>.from(bot['replay'] as Map) : <String, dynamic>{};
    final saved = bot['saved'];
    String net(dynamic v) => v is num ? v.toStringAsFixed(0) : '-';
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6),
      decoration: BoxDecoration(color: p.accent.withOpacity(0.08), border: Border(bottom: BorderSide(color: p.textSecondary.withOpacity(0.2)))),
      child: Row(children: [
        _cell(context, 'NORMAL BOT (net)', bold: true, flex: _wIdea, align: TextAlign.left),
        for (final tf in const ['3m', '5m', '15m']) _cell(context, net(rep[tf]), color: (rep[tf] is num && rep[tf] < 0) ? p.loss : p.textPrimary),
        _cell(context, net(saved), flex: _wSaved, color: (saved is num && saved < 0) ? p.loss : p.textPrimary),
        _cell(context, 'bot', flex: _wVerdict, color: p.textSecondary),
      ]),
    );
  }

  Widget _groupHead(BuildContext context, Map<String, dynamic> g, List<Map<String, dynamic>> counts) {
    final p = context.palette;
    final c = counts.firstWhere((x) => x['title'] == g['title'], orElse: () => <String, dynamic>{});
    final extra = c.isEmpty ? '' : '  -  ${c['n']} ideas, ${c['better']} better, ${c['worse']} worse';
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Text('${g['title']}'.toUpperCase() + extra,
          style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.4, color: p.textSecondary, fontSize: 11)),
    );
  }

  Widget _tableRow(BuildContext context, Map<String, dynamic> r, List<String> tfsDone, String where) {
    final p = context.palette;
    final id = '$where:${r['key']}';
    final open = _open.contains(id);
    final rep = (r['replay'] is Map) ? Map<String, dynamic>.from(r['replay'] as Map) : <String, dynamic>{};
    final sv = (r['saved'] is Map) ? Map<String, dynamic>.from(r['saved'] as Map) : <String, dynamic>{};
    Widget tfCell(String tf) {
      final x = rep[tf];
      if (x is! Map) return _cell(context, '-', color: p.textSecondary);
      if (x['taken'] == 0) return _cell(context, '0 trades', color: p.textSecondary);
      final nt = _n(x['net']);
      return _cell(context, _f(nt), color: nt > 0 ? p.profit : (nt < 0 ? p.loss : p.textSecondary), bold: nt > 0);
    }
    Widget savedCell() {
      if (sv['state'] != 'ok') return _cell(context, 'n/a', color: p.textSecondary, flex: _wSaved);
      final nt = _n(sv['net']);
      return _cell(context, _f(nt), color: nt > 0 ? p.profit : (nt < 0 ? p.loss : p.textSecondary), flex: _wSaved);
    }
    final profit = (r['profit_tfs'] is List && (r['profit_tfs'] as List).isNotEmpty);
    return InkWell(
      onTap: () => setState(() => open ? _open.remove(id) : _open.add(id)),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 6),
        decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.textSecondary.withOpacity(0.15)))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
            Expanded(
              flex: _wIdea,
              child: Text('${r['short'] ?? r['title']}', style: context.type.metadata.copyWith(color: p.textPrimary, fontWeight: FontWeight.w600, fontSize: 12)),
            ),
            tfCell('3m'),
            tfCell('5m'),
            tfCell('15m'),
            savedCell(),
            _cell(context, '${r['answer'] ?? ''}', color: r['answer'] == 'PROFIT' ? p.profit : (r['answer'] == 'LOSING' ? p.loss : p.textSecondary), bold: true, flex: _wVerdict),
          ]),
          if (open)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${r['title']}', style: context.type.metadata.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700)),
                if ('${r['desc'] ?? ''}'.isNotEmpty) Text('${r['desc']}', style: context.type.metadata),
                for (final tf in tfsDone)
                  if (rep[tf] is Map)
                    Text('$tf: took ${rep[tf]['taken']} trades, net ${_f(_n(rep[tf]['net']))}, ${_f(_n(rep[tf]['vs_bot']))} vs bot (${rep[tf]['verdict']})', style: context.type.metadata),
                Text(sv['state'] == 'ok'
                    ? 'Saved trades: rule would skip ${sv['n_skip']} of ${sv['n_known']} trades, ${_f(_n(sv['vs_bot']))} vs bot'
                    : (sv['state'] == 'no_data' ? 'Saved trades: only ${sv['n_known']} trades have this data, not enough' : 'Saved trades: this idea cannot be tested on saved trades'),
                    style: context.type.metadata),
                Text('Old verdict (bot vs idea): ${r['label'] ?? r['vshort']}', style: context.type.metadata),
                if (sv['state'] == 'ok' && _list(sv['by_day']).isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Text('Day by day (your saved trades):', style: context.type.metadata.copyWith(fontWeight: FontWeight.w700)),
                  for (final x in _list(sv['by_day']))
                    Text('${x['day']}:  bot ${x['bot_n']} trades ${_f(_n(x['bot_net']))}   |   this idea ${x['idea_n']} trades ${_f(_n(x['idea_net']))}', style: context.type.metadata),
                ],
                Text(profit ? 'PROFIT after fees on: ${(r['profit_tfs'] as List).join(', ')}' : (rep.isNotEmpty ? 'Still losing after fees (it only loses less than the bot)' : ''),
                    style: context.type.metadata.copyWith(color: profit ? p.profit : p.warning, fontWeight: FontWeight.w700)),
              ]),
            ),
        ]),
      ),
    );
  }

  Widget _sdBlock(BuildContext context, Map<String, dynamic> sd) {
    final p = context.palette;
    final ans = (sd['answer'] is List) ? (sd['answer'] as List).map((e) => '$e').toList() : <String>[];
    String line(dynamic xs) {
      final l = _list(xs);
      if (l.isEmpty) return 'no data';
      return l.map((x) => 'SD ${x['len']} ${x['avg'] is num ? (x['avg'] as num).toStringAsFixed(1) : '-'}').join('   ');
    }
    return Padding(
      padding: const EdgeInsets.only(top: 6),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          childrenPadding: EdgeInsets.zero,
          title: Text('SD length test (200 / 150 / 100 / 50)', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
          subtitle: Text('Average result per trade after fees, majors only', style: context.type.metadata),
          children: [
            for (final a in ans) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(a, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
            for (final t in _list(sd['tfs'])) ...[
              const SizedBox(height: 6),
              Text('${t['tf']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
              Text('Every signal:  ${line(t['plain'])}', style: context.type.metadata),
              Text('With SD 0 rule:  ${line(t['rule'])}', style: context.type.metadata),
            ],
          ],
        ),
      ),
    );
  }
}
