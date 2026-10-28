import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_card.dart';

/// NEXT-2 part 1: BRAIN EVIDENCE on the Brain tab. Reads only what the backend already sends (no new API, no backend change):
///  - learn.stats.overall = what happened after each Brain state (S / T / W / R): sample size, verdict, lean (hold / exit_now)
///  - edge.items = the open Dual trades with their state, ROI, MFE, giveback and state history
/// It shows the evidence and says clearly when there is NOT ENOUGH DATA. It never shows a made-up percentage, never uses a strong
/// action colour without evidence, and nothing here controls a trade (shadow / observation only).
class BrainEvidenceCard extends StatelessWidget {
  final Map<String, dynamic> learn; // _st['learn']
  final Map<String, dynamic> edge; // _st['edge']
  final bool loading; // nothing received from the backend yet
  final String err; // last load error (empty = none)

  const BrainEvidenceCard({super.key, required this.learn, required this.edge, this.loading = false, this.err = ''});

  static const _names = {'S': 'STRONG', 'T': 'STABLE', 'W': 'WEAKENING', 'R': 'REVERSED', 'N': 'NEW', '?': 'UNKNOWN'};
  static const _letters = {'STRONG': 'S', 'STABLE': 'T', 'WEAKENING': 'W', 'REVERSED': 'R', 'NEW': 'N', 'UNKNOWN': '?'};
  static const _hints = ['EARLY HINT', 'SUPPORTED'];

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static double? _num(dynamic v) => v is num ? v.toDouble() : null;
  static String _sg(double? v, [int nd = 1]) => v == null ? 'n/a' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(nd)}';

  static Map<String, dynamic>? _find(List<Map<String, dynamic>> overall, String letter) {
    for (final r in overall) {
      if ('${r['state']}' == letter) return r;
    }
    return null;
  }

  Color _stColor(AppPalette p, String name) => name == 'STRONG'
      ? p.profit
      : name == 'STABLE'
          ? p.accent
          : name == 'WEAKENING'
              ? p.warning
              : name == 'REVERSED'
                  ? p.loss
                  : p.textMuted;

  // Evidence colour: only a real hint or support gets a colour; everything else stays grey.
  Color _evColor(AppPalette p, String v) => v == 'SUPPORTED' ? p.accent : (v == 'EARLY HINT' ? p.warning : p.textMuted);

  Color _recColor(AppPalette p, String rec) => rec == 'HOLD' ? p.profit : (rec == 'PROTECT' ? p.warning : p.textMuted);

  /// Same idea as backend rule r1, but on TODAY's evidence for display only (the frozen r1 rows are stored by the backend):
  /// HOLD = hint / supported and lean hold; PROTECT = hint / supported, lean exit_now and the trade is in profit; else NO OPINION.
  static Map<String, String> _rec(Map<String, dynamic>? ev, double? roi) {
    if (ev == null) return {'rec': 'NO OPINION', 'why': 'NOT ENOUGH DATA: this state has too few finished trades to judge.'};
    final v = '${ev['verdict']}';
    final lean = '${ev['lean']}';
    final hint = _hints.contains(v);
    if (hint && lean == 'hold') {
      return {'rec': 'HOLD', 'why': 'In earlier trades, holding after this state did better than leaving at the call.'};
    }
    if (hint && lean == 'exit_now') {
      if (roi != null && roi > 0) {
        return {'rec': 'PROTECT', 'why': 'In earlier trades, leaving at this state beat holding, and this trade is in profit.'};
      }
      return {'rec': 'NO OPINION', 'why': 'Leaving looked better in the past, but this trade is not in profit: nothing to protect.'};
    }
    if (v == 'NOT ENOUGH DATA') return {'rec': 'NO OPINION', 'why': 'NOT ENOUGH DATA: not enough finished trades in this state yet.'};
    return {'rec': 'NO OPINION', 'why': 'No clear pattern between holding and leaving in earlier trades.'};
  }

  Widget _box(AppPalette p, Color c, Widget child) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(color: c.withOpacity(0.07), border: Border.all(color: c.withOpacity(0.35)), borderRadius: BorderRadius.circular(12)),
        child: child,
      );

  // One Brain state: sample, evidence level and what holding vs leaving did.
  Widget _stateRow(BuildContext context, AppPalette p, String s, List<Map<String, dynamic>> overall) {
    final ev = _find(overall, s);
    final v = ev == null ? 'NOT ENOUGH DATA' : '${ev['verdict'] ?? 'NOT ENOUGH DATA'}';
    final n = ev == null ? 0 : (_num(ev['n'])?.toInt() ?? 0);
    final lean = '${ev?['lean']}';
    final ex = _num(ev?['excess']);
    final hint = _hints.contains(v);
    String result = 'Not enough finished trades yet to compare holding with leaving.';
    if (hint && lean == 'hold') {
      result = 'Holding beat leaving at this call by ${_sg(ex)} points more than usual.';
    } else if (hint && lean == 'exit_now') {
      result = 'Leaving at this call beat holding (${_sg(ex)} points vs the usual).';
    } else if (v != 'NOT ENOUGH DATA') {
      result = 'No clear pattern between holding and leaving.';
    }
    final avail = _num(ev?['avail']), back = _num(ev?['back']);
    final c = _stColor(p, _names[s]!);
    return _box(
      p,
      hint ? c : p.textMuted,
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          OwlChip(_names[s]!, c),
          OwlChip(v, _evColor(p, v)),
          Text('$n trades', style: context.type.metadata),
        ]),
        const SizedBox(height: 4),
        Text(result, style: context.type.secondary),
        if (hint && (avail != null || back != null))
          Text('Average profit still available ${_sg(avail)} points, given back ${_sg(back)} points.', style: context.type.metadata),
      ]),
    );
  }

  // ENTRY -> state runs (from the state history letters) -> NOW, then peak / now / giveback in numbers.
  Widget _journey(BuildContext context, AppPalette p, Map<String, dynamic> it) {
    final hs = '${it['hs'] ?? ''}';
    final runs = <MapEntry<String, int>>[];
    for (final ch in hs.split('')) {
      if (runs.isNotEmpty && runs.last.key == ch) {
        runs[runs.length - 1] = MapEntry(ch, runs.last.value + 1);
      } else {
        runs.add(MapEntry(ch, 1));
      }
    }
    final steps = <Widget>[OwlChip('ENTRY', p.textMuted)];
    for (final r in runs) {
      final name = _names[r.key] ?? 'UNKNOWN';
      steps.add(Icon(Icons.arrow_forward_rounded, size: 12, color: p.textMuted));
      steps.add(OwlChip(r.value > 1 ? '$name x${r.value}' : name, _stColor(p, name)));
    }
    steps.add(Icon(Icons.arrow_forward_rounded, size: 12, color: p.textMuted));
    steps.add(OwlChip('NOW', p.accent));
    final roi = _num(it['roi']), mfe = _num(it['mfe']), gb = _num(it['gb']);
    final n = _num(it['n'])?.toInt();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (runs.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(4),
            child: Row(children: [
              for (final r in runs) Expanded(flex: r.value, child: Container(height: 6, color: _stColor(p, _names[r.key] ?? 'UNKNOWN').withOpacity(0.85))),
            ]),
          ),
        ),
      Wrap(spacing: 4, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: steps),
      const SizedBox(height: 4),
      Text('Peak (MFE) ${_sg(mfe)}%  \u2192  now ${_sg(roi)}%  |  given back ${gb == null ? 'n/a' : gb.toStringAsFixed(1)}%',
          style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
      if (n != null) Text('${n == 1 ? '1 candle' : '$n candles'} since entry${hs.length < n ? ' (last ${hs.length} states shown)' : ''}', style: context.type.metadata),
    ]);
  }

  // Secondary facts one tap away: what the evidence for this state says and how it was compared.
  Widget _details(BuildContext context, String st, Map<String, dynamic>? ev) {
    final lean = '${ev?['lean']}';
    final lines = <String>[
      ev == null ? 'No judged result for the state $st yet (under the minimum number of finished trades).' : '${ev['text'] ?? ''}',
      if (ev != null) 'Compared with ${_num(ev['n'])?.toInt() ?? 0} finished trades: ${lean == 'hold' ? 'holding looked better' : (lean == 'exit_now' ? 'leaving looked better' : 'no clear lean')}.',
      'The Brain refreshes this evidence at most every 10 minutes.',
    ];
    return Theme(
      data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
      child: ExpansionTile(
        tilePadding: EdgeInsets.zero,
        childrenPadding: EdgeInsets.zero,
        dense: true,
        title: Text('Evidence details', style: context.type.metadata.copyWith(fontWeight: FontWeight.w700)),
        children: [
          Align(
            alignment: Alignment.centerLeft,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              for (final l in lines) if (l.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(l, style: context.type.metadata)),
            ]),
          ),
        ],
      ),
    );
  }

  Widget _tradeRow(BuildContext context, AppPalette p, Map<String, dynamic> it, List<Map<String, dynamic>> overall) {
    final st = '${it['st'] ?? 'UNKNOWN'}';
    final buy = (_num(it['d']) ?? 0) > 0;
    final letter = _letters[st];
    final ev = letter == null ? null : _find(overall, letter);
    final roi = _num(it['roi']);
    final r = _rec(ev, roi);
    final v = ev == null ? 'NOT ENOUGH DATA' : '${ev['verdict'] ?? 'NOT ENOUGH DATA'}';
    final n = ev == null ? 0 : (_num(ev['n'])?.toInt() ?? 0);
    final side = buy ? p.profit : p.loss;
    return _box(
      p,
      _stColor(p, st),
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(
            child: Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Text('${it['s'] ?? ''}'.replaceAll('USDT', ''), style: context.type.primary.copyWith(fontWeight: FontWeight.w800)),
              OwlChip(buy ? 'BUY' : 'SELL', side),
              Text('${it['f'] ?? ''}', style: context.type.metadata),
              OwlChip(st, _stColor(p, st)),
            ]),
          ),
          Text(roi == null ? 'n/a' : '${_sg(roi)}%',
              style: context.type.primary.copyWith(fontSize: 18, fontWeight: FontWeight.w800, color: roi == null ? p.textMuted : (roi >= 0 ? p.profit : p.loss))),
        ]),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          OwlChip(r['rec']!, _recColor(p, r['rec']!)),
          OwlChip(v, _evColor(p, v)),
          Text('sample $n trades', style: context.type.metadata),
        ]),
        const SizedBox(height: 4),
        Text(r['why']!, style: context.type.secondary),
        const SizedBox(height: 8),
        _journey(context, p, it),
        _details(context, st, ev),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (learn.isEmpty) {
      final wait = loading && err.isEmpty;
      return OwlSectionCard(title: 'BRAIN EVIDENCE', edge: p.textMuted, children: [
        Row(children: [
          if (wait) const Padding(padding: EdgeInsets.only(right: 8), child: SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2))),
          Expanded(
            child: Text(
              wait
                  ? 'Loading the Brain evidence...'
                  : (err.isNotEmpty ? 'The Brain could not be loaded now ($err). It tries again by itself.' : 'No Brain evidence yet. It appears after the Brain has finished its first cycle.'),
              style: context.type.secondary,
            ),
          ),
        ]),
      ]);
    }
    final stats = _map(learn['stats']);
    final overall = _maps(stats['overall']);
    final items = _maps(edge['items']);
    final failed = '${stats['status']}' == 'error';
    final seen = overall.any((r) => _hints.contains('${r['verdict']}'));
    final minN = _num(stats['min_n'])?.toInt() ?? 30;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      OwlSectionCard(
        title: 'BRAIN EVIDENCE',
        edge: seen ? p.accent : p.textMuted,
        hint: 'Paper only. Observation only: nothing here controls a trade.',
        children: [
          Text('${learn['text'] ?? ''}', style: context.type.primary),
          if (failed)
            Padding(padding: const EdgeInsets.only(top: 6), child: Text('The Brain statistics could not be read now. NOT ENOUGH DATA.', style: context.type.secondary))
          else if (!seen)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('NOT ENOUGH DATA yet. This is normal at the start: a result needs $minN judged trades in a state, and no green or red action is shown before that.',
                  style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
            ),
          if (!failed) for (final s in const ['S', 'T', 'W', 'R']) _stateRow(context, p, s, overall),
          const SizedBox(height: 6),
          Text('Evidence level is NOT a win chance. EARLY HINT = a weak sign, SUPPORTED = a stronger sign, still no promise.', style: context.type.metadata),
        ],
      ),
      OwlSectionCard(
        title: 'OPEN TRADES - BRAIN VIEW',
        hint: "Today's evidence applied to each open Dual trade. Shadow only, not advice.",
        children: [
          if (items.isEmpty)
            Text('No open Dual trade with Brain data yet. It appears after the next closed candle.', style: context.type.metadata)
          else
            for (final it in items) _tradeRow(context, p, it, overall),
        ],
      ),
    ]);
  }
}
