import 'dart:async';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/verdict_style.dart';
import 'owl_card.dart';

/// R12: the ONE "Exit rules by market state" card of the Study Lab. Shows what GET /api/v2/lab_exit sends: the 9 exit rules (rows) x the market states (columns, regime + interval),
/// each cell = mean R per trade after fees on the old replayed trades (green = 0.05 R or more above the fixed 2R, red = 0.05 R or more below). A dot marks the rule the OLDER days picked for that state;
/// the last row says what the UNSEEN days said about that pick (EDGE / hint / none / wait). Read only, nothing trades, advice only. Folded by default (one line); asks once, then every 10 minutes while on screen.
class LabExitTableCard extends StatefulWidget {
  const LabExitTableCard({super.key});

  @override
  State<LabExitTableCard> createState() => _LabExitTableCardState();
}

class _LabExitTableCardState extends State<LabExitTableCard> {
  static const _tab = [FontFeature.tabularFigures()];
  static const _short = {'EDGE': 'EDGE', 'DIAGNOSIS_ONLY': 'hint', 'NO_EDGE': 'none', 'NOT_ENOUGH_DATA': 'wait', 'LOSING': 'loses'};
  Map<String, dynamic> _d = {};
  Timer? _timer;
  bool _busy = false;

  static double? _n(dynamic v) => v is num && v.isFinite ? v.toDouble() : null;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) => v is List ? [for (final x in v) _m(x)] : <Map<String, dynamic>>[];

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(minutes: 10), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    try {
      final d = await context.read<AppProvider>().fetchLabExit();
      if (mounted && d.isNotEmpty) setState(() => _d = d);
    } catch (_) {
      // keep the last good answer
    } finally {
      _busy = false;
    }
  }

  String _head(Map<String, dynamic> s) {
    final r = '${s['regime'] ?? '?'}';
    return '${r.length > 5 ? r.substring(0, 5) : r}\n${s['tf'] ?? ''}';
  }

  Widget _cell(String t, {Color? c, bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Text(t, textAlign: TextAlign.center, style: context.type.secondary.copyWith(color: c, fontWeight: bold ? FontWeight.w800 : null, fontFeatures: _tab)),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final states = _l(_d['states']).take(4).toList();
    final rules = _l(_d['rules']);
    final def = '${_d['default'] ?? 'tp2'}';
    final ok = states.isNotEmpty && rules.isNotEmpty;
    final head = _d.isEmpty ? 'Loading' : '${_d['line'] ?? 'No answer yet'}';
    final extra = _l(_d['states']).length - states.length;
    Widget grid() {
      final rows = <TableRow>[
        TableRow(children: [const SizedBox.shrink(), for (final s in states) _cell(_head(s), bold: true)]),
        for (final r in rules)
          TableRow(children: [
            Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text('${r['name']}${r['name'] == def ? '*' : ''}${r['live'] == true ? '' : ' ~'}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700))),
            for (final s in states)
              () {
                final mean = _m(s['mean']);
                final v = _n(mean['${r['name']}']);
                final base = _n(mean[def]);
                final d = v != null && base != null ? v - base : 0.0;
                final c = d >= 0.05 ? p.profit : (d <= -0.05 ? p.loss : null);
                final mark = s['pick'] == r['name'] && r['name'] != def ? ' \u25CF' : '';
                return _cell(v == null ? '--' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}$mark', c: c, bold: s['pick'] == r['name']);
              }(),
          ]),
        TableRow(children: [
          Padding(padding: const EdgeInsets.symmetric(vertical: 4), child: Text('Unseen days', style: context.type.metadata)),
          for (final s in states) _cell(_short['${s['verdict']}'] ?? 'wait', c: VerdictStyle.of(p, '${s['verdict']}').color, bold: true),
        ]),
      ];
      return Table(columnWidths: const {0: FlexColumnWidth(1.5)}, defaultColumnWidth: const FlexColumnWidth(1), children: rows);
    }

    return OwlFold(
      title: 'EXIT RULES BY MARKET STATE',
      headline: head,
      children: [
        Text('The 9 exit rules on the same old replayed trades (R per trade after fees). * = the fixed 2R default, \u25CF = the rule the older days picked, ~ = needs an exit engine (advice only). The pick is judged ONCE on the newest unseen days.', style: context.type.metadata),
        const SizedBox(height: 6),
        if (ok) ...[
          grid(),
          if (extra > 0) Text('+$extra more market states with fewer trades (see Study results).', style: context.type.metadata),
          const SizedBox(height: 6),
          for (final s in states) Padding(padding: const EdgeInsets.only(bottom: 3), child: Text('${s['key']}: ${s['text'] ?? ''}', style: context.type.secondary)),
          const SizedBox(height: 4),
          for (final r in rules) Text('${r['name']}: ${r['text'] ?? ''}', style: context.type.metadata),
        ] else
          Text(_d.isEmpty ? 'Loading' : '${_d['line'] ?? 'No answer yet'} The first run starts by itself a few minutes after the backend starts.', style: context.type.secondary),
      ],
    );
  }
}
