import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_card.dart';

/// Part 67 (was NEXT-7 Flutter card): shows learn.skip, which the backend (brain_skip.py) already makes.
/// Question it answers: "if we had taken the signals the Brain skipped, would they have done better or worse than the ones we took?"
/// Read only: no new API, no backend change, nothing here controls a trade. Numbers are ROI points net of fee (paper).
/// Colour only for EARLY HINT / SUPPORTED, everything else stays grey. No made-up percentages.
class BrainSkipCard extends StatelessWidget {
  final Map<String, dynamic> learn; // _st['learn']

  const BrainSkipCard({super.key, required this.learn});

  static const _hints = ['EARLY HINT', 'SUPPORTED'];

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static double? _num(dynamic v) => v is num ? v.toDouble() : null;
  static String _sg(double? v, [int nd = 1]) => v == null ? 'n/a' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(nd)}';

  Widget _row(BuildContext context, AppPalette p, List<Widget> chips, String text) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: chips),
          if (text.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(text, style: context.type.secondary)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final sk = _map(learn['skip']);
    if (sk.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    final bad = '${sk['status']}' == 'error';
    final v = '${sk['verdict'] ?? 'NOT ENOUGH DATA'}';
    final done = _num(sk['skipped_done'])?.toInt() ?? 0;
    final open = _num(sk['skipped_open'])?.toInt() ?? 0;
    final taken = _num(sk['taken_done'])?.toInt() ?? 0;
    final minN = _num(sk['min_n'])?.toInt() ?? 30;
    final hint = _hints.contains(v);
    final tf = _map(sk['tf']);
    final worse = (_num(sk['diff']) ?? 0) < 0;
    return OwlFold(
      title: 'SKIPPED SIGNALS',
      headline: bad ? 'NOT ENOUGH DATA' : '$done checked  |  $open still running  |  $v',
      headlineColor: hint ? p.accent : p.textMuted,
      children: [
        Text(
          'The Dual Bot runs every skipped signal to the end as a what-if trade. This compares them with the trades that were taken. Paper numbers only, nothing is traded.',
          style: context.type.metadata,
        ),
        if (bad)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('The skipped-signal check could not be read now. NOT ENOUGH DATA.', style: context.type.secondary))
        else ...[
          _row(
            context,
            p,
            [OwlChip(v, hint ? p.accent : p.textMuted), Text('skipped $done, taken $taken', style: context.type.metadata)],
            done < minN
                ? 'NOT ENOUGH DATA: $done of $minN finished skipped signals so far.'
                : 'Average per skipped signal ${_sg(_num(sk['mean_skip']), 2)} points, per taken trade ${_sg(_num(sk['mean_taken']), 2)} points.'
                    '${hint ? (worse ? ' The skipped signals did worse than the taken trades.' : ' The skipped signals did better than the taken trades.') : ''}',
          ),
          for (final e in tf.entries)
            () {
              final r = _map(e.value);
              return _row(
                context,
                p,
                [OwlChip('${e.key}', p.textMuted), Text('skipped ${_num(r['skipped'])?.toInt() ?? 0}, taken ${_num(r['taken'])?.toInt() ?? 0}', style: context.type.metadata)],
                'Skipped ${_sg(_num(r['mean_skip']), 2)}  |  taken ${_sg(_num(r['mean_taken']), 2)} points per trade.',
              );
            }(),
        ],
      ],
    );
  }
}
