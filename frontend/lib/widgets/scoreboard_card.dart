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

  Color _vcol(AppPalette p, String v) {
    if (v == 'helps') return p.profit;
    if (v == 'hurts') return p.loss;
    if (v == 'mixed') return p.warning;
    if (v == 'replay_up' || v == 'saved_up') return p.profit.withOpacity(0.75);
    if (v == 'replay_down' || v == 'saved_down') return p.loss.withOpacity(0.75);
    return p.textSecondary;
  }

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
        Text('One line per idea. Replay = the bot\'s signals on old candles. Saved = your own closed trades. HELPS needs both to agree.',
            style: context.type.metadata),
        if (running) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
          const SizedBox(height: 4),
          Text('${_d['replay_progress'] ?? ''}  (a few minutes, you can leave this screen)', style: context.type.metadata),
        ],
        if (_loading) const Padding(padding: EdgeInsets.only(top: 12), child: LinearProgressIndicator()),
        if (_err.isNotEmpty)
          Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
        if (headline.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final h in headline)
            Padding(padding: const EdgeInsets.only(bottom: 4), child: Text(h, style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35))),
        ],
        if (byTf.isNotEmpty) ...[
          const SizedBox(height: 10),
          _label(context, 'BY TIMEFRAME (replay)'),
          for (final t in byTf) _tfLine(context, t),
        ],
        for (final g in groups) ...[
          const SizedBox(height: 12),
          _label(context, '${g['title']}'.toUpperCase()),
          for (final r in _list(g['rows'])) _ideaRow(context, r, tfsDone),
        ],
        if (groups.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(
                'Numbers are ROI points after fees. + means the idea beat the normal bot. Many tests on the same data can still give a lucky winner, so try a winner on paper first. '
                'Saved trades have no Bollinger, CVD, TSI or exit data, so those ideas show replay only.',
                style: context.type.metadata),
          ),
      ]),
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

  Widget _ideaRow(BuildContext context, Map<String, dynamic> r, List<String> tfsDone) {
    final p = context.palette;
    final v = '${r['verdict']}';
    final col = _vcol(p, v);
    final rep = (r['replay'] is Map) ? Map<String, dynamic>.from(r['replay'] as Map) : <String, dynamic>{};
    final sv = (r['saved'] is Map) ? Map<String, dynamic>.from(r['saved'] as Map) : <String, dynamic>{};
    final spans = <InlineSpan>[];
    for (final tf in tfsDone) {
      final x = rep[tf];
      if (x is! Map) continue;
      final vs = _n(x['vs_bot']);
      spans.add(TextSpan(text: '$tf '));
      spans.add(TextSpan(text: _f(vs), style: TextStyle(color: vs > 0 ? p.profit : (vs < 0 ? p.loss : p.textSecondary), fontWeight: FontWeight.w700)));
      spans.add(const TextSpan(text: '   '));
    }
    spans.add(const TextSpan(text: 'saved '));
    if (sv['state'] == 'ok') {
      final vs = _n(sv['vs_bot']);
      spans.add(TextSpan(text: _f(vs), style: TextStyle(color: vs > 0 ? p.profit : (vs < 0 ? p.loss : p.textSecondary), fontWeight: FontWeight.w700)));
      spans.add(TextSpan(text: ' (skips ${sv['n_skip']} of ${sv['n_known']})'));
    } else if (sv['state'] == 'no_data') {
      spans.add(TextSpan(text: 'no data (${sv['n_known']} trades have it)'));
    } else {
      spans.add(const TextSpan(text: 'not available'));
    }
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Text('${r['title']}', style: context.type.primary)),
          const SizedBox(width: 8),
          Text('${r['label']}', style: context.type.label.copyWith(color: col, fontWeight: FontWeight.w800)),
        ]),
        Text.rich(TextSpan(style: context.type.metadata, children: spans)),
      ]),
    );
  }
}
