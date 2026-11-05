import '../theme/app_active.dart';
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Tag Lab card (crypto Doctor, under the final scoreboard).
///
/// Answers, in plain words and only by counting (no AI key needed): which combination of the main chart signal, the Z candle,
/// TSI and ZSM really makes money, which exit suits it (does a rally after TP1 / TP4 get missed?), and whether the winners are
/// better than luck. Tap Run: the backend replays old candles in its own low-priority process; nothing is traded.
/// Everything comes from GET /api/tag_lab (backend tag_lab.py). Read-only.
class TagLabCard extends StatefulWidget {
  const TagLabCard({super.key});

  @override
  State<TagLabCard> createState() => _TagLabCardState();
}

class _TagLabCardState extends State<TagLabCard> {
  Map<String, dynamic> _st = {};
  String _tf = '5m';
  int _days = 7;
  String _err = '';
  bool _starting = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = AppActive.every(const Duration(seconds: 15), () { // Part 7b: 6 s -> 15 s
      if (_st['running'] == true) _poll();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll({bool run = false}) async {
    if (!mounted) return;
    try {
      final base = context.read<AppProvider>().baseUrl;
      final q = run ? '?start=run&tf=$_tf&days=$_days' : '?tf=$_tf';
      final res = await http.get(Uri.parse('$base/api/tag_lab$q')).timeout(const Duration(seconds: 20));
      if (res.statusCode != 200) throw 'HTTP ${res.statusCode}';
      final m = jsonDecode(utf8.decode(res.bodyBytes));
      if (m is! Map) throw 'unexpected reply';
      if (mounted) {
        setState(() {
          _st = Map<String, dynamic>.from(m);
          _err = '${_st['error'] ?? ''}';
        });
      }
    } catch (e) {
      if (mounted) setState(() => _err = '$e');
    }
  }

  Future<void> _run() async {
    setState(() => _starting = true);
    await _poll(run: true);
    if (mounted) setState(() => _starting = false);
  }

  void _pickTf(String tf) {
    if (_st['running'] == true || _tf == tf) return;
    setState(() {
      _tf = tf;
      _st = {};
    });
    _poll();
  }

  static List<String> _strs(dynamic v) => (v is List) ? v.map((e) => '$e').toList() : <String>[];
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      (v is List) ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  Widget _line(BuildContext context, AppPalette p, String l) {
    final bullet = l.startsWith('* ');
    final sub = l.startsWith('   ');
    return Padding(
      padding: EdgeInsets.only(bottom: 3, left: sub ? 10 : 0),
      child: Text(
        bullet ? l.substring(2) : l.trim(),
        style: bullet
            ? context.type.primary.copyWith(fontWeight: FontWeight.w700, height: 1.3)
            : (sub ? context.type.metadata : context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final running = _st['running'] == true;
    final busy = running || _starting;
    final res = (_st['result'] is Map) ? Map<String, dynamic>.from(_st['result'] as Map) : <String, dynamic>{};
    final head = _strs(res['head']);
    final secs = _maps(res['sections']);
    final age = _st['age_min'];
    final progress = '${_st['progress'] ?? ''}';
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
          Icon(Icons.hub_outlined, size: 18, color: p.accent),
          const SizedBox(width: 8),
          Expanded(child: Text('Tag Lab: which indicator combo makes money?', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
        ]),
        Text(
            'Counts every combination of the main chart signal, Z candle, TSI and ZSM on old candles, with the fee inside. '
            'No AI key needed, nothing is traded.',
            style: context.type.metadata),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          for (final t in const ['3m', '5m', '15m'])
            ChoiceChip(label: Text(t), selected: _tf == t, onSelected: busy ? null : (_) => _pickTf(t)),
          for (final d in const [3, 7, 14])
            ChoiceChip(label: Text('$d days'), selected: _days == d, onSelected: busy ? null : (_) => setState(() => _days = d)),
        ]),
        const SizedBox(height: 6),
        OutlinedButton(
          onPressed: busy ? null : _run,
          child: Text(running ? 'Running...' : 'Run test ($_tf, $_days days)'),
        ),
        if (running) ...[
          const SizedBox(height: 8),
          const LinearProgressIndicator(),
          const SizedBox(height: 4),
          Text('${progress.isEmpty ? 'starting...' : progress}  (you can leave this screen)', style: context.type.metadata),
        ],
        if (_err.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 8), child: Text(_err, style: context.type.metadata.copyWith(color: p.loss))),
        if (secs.isEmpty && !running && _err.isEmpty)
          Padding(padding: const EdgeInsets.only(top: 10), child: Text('No result for $_tf yet. Tap Run test.', style: context.type.secondary)),
        if (secs.isNotEmpty) ...[
          const SizedBox(height: 10),
          for (final h in head) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text(h, style: context.type.metadata)),
          if (age is num) Text('Made ${age.toInt()} min ago', style: context.type.metadata),
          const SizedBox(height: 6),
          for (var i = 0; i < secs.length; i++)
            Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                key: PageStorageKey('taglab_${_tf}_$i'),
                initiallyExpanded: i == 0,
                tilePadding: EdgeInsets.zero,
                childrenPadding: const EdgeInsets.only(bottom: 6),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                title: Text('${i + 1}. ${secs[i]['title']}', style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.6)),
                children: [for (final l in _strs(secs[i]['lines'])) _line(context, p, l)],
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
                'ROI points after fees, from a replay (no slippage). A combination counts only if it wins in the older AND the newer data, '
                'and the luck check says if that is more than chance. Try a winner on paper first. Full text: ~/owl_data/tag_lab_$_tf.txt',
                style: context.type.metadata),
          ),
        ],
      ]),
    );
  }
}
