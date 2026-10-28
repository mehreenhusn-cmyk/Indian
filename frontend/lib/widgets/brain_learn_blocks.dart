import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'owl_card.dart';

/// NEXT-2 part 2: three folded blocks on the Brain tab, read only from learn.look, learn.stats.ledger and learn.shadow
/// (no new API, no backend change). Each block has its key fact in the headline and the detail one tap away.
///  - LOOK-ALIKE: how earlier look-alike situations pointed (needs enough scored calls, else NOT ENOUGH DATA)
///  - MISTAKE PATTERNS: counts of Brain calls that were wrong, plus the "observed historical difference" of the numbers (NOT a trading rule)
///  - SHADOW CHECK: what the stored HOLD / PROTECT recommendations would have given in paper numbers
/// Evidence colours only for EARLY HINT / SUPPORTED. Everything else stays grey. No made-up percentages.
class BrainLearnBlocks extends StatelessWidget {
  final Map<String, dynamic> learn; // _st['learn']

  const BrainLearnBlocks({super.key, required this.learn});

  static const _hints = ['EARLY HINT', 'SUPPORTED'];
  static const _names = {'S': 'STRONG', 'T': 'STABLE', 'W': 'WEAKENING', 'R': 'REVERSED'};
  static const _feat = {
    'tsi': 'TSI',
    'hist': 'TSI histogram',
    'z': 'Z-score',
    'zg': 'Z minus Z-SMA',
    'sm': 'Main chart sideways %',
    'bw': 'SD width',
    'ed': 'EMA50 distance',
    'sc': 'reasons still with trade',
  };

  static Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _maps(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static double? _num(dynamic v) => v is num ? v.toDouble() : null;
  static String _sg(double? v, [int nd = 1]) => v == null ? 'n/a' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(nd)}';

  Color _vColor(AppPalette p, String v) => v == 'SUPPORTED' ? p.accent : (v == 'EARLY HINT' ? p.warning : p.textMuted);

  Color _stColor(AppPalette p, String name) => name == 'STRONG'
      ? p.profit
      : name == 'STABLE'
          ? p.accent
          : name == 'WEAKENING'
              ? p.warning
              : name == 'REVERSED'
                  ? p.loss
                  : p.textMuted;

  Widget _row(BuildContext context, AppPalette p, List<Widget> chips, String text, [String? extra]) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(border: Border.all(color: p.border), borderRadius: BorderRadius.circular(12)),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: chips),
          if (text.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(text, style: context.type.secondary)),
          if (extra != null) Padding(padding: const EdgeInsets.only(top: 2), child: Text(extra, style: context.type.metadata)),
        ]),
      );

  Widget _note(BuildContext context, String t) => Text(t, style: context.type.metadata);

  // ---- LOOK-ALIKE ----
  Widget _look(BuildContext context, AppPalette p) {
    final look = _map(learn['look']);
    final rows = _maps(_map(look['roi'])['overall']);
    final minN = _num(look['min_n'])?.toInt() ?? 30;
    final bad = look.isEmpty || '${look['status']}' == 'error';
    final hit = rows.where((r) => _hints.contains('${r['verdict']}')).length;
    return OwlFold(
      title: 'LOOK-ALIKE',
      headline: hit > 0 ? '$hit of ${rows.length} states have a hint' : 'NOT ENOUGH DATA',
      headlineColor: hit > 0 ? p.accent : p.textMuted,
      children: [
        _note(context, 'Have we seen a situation like this before? The Brain compares the market numbers of a call with earlier finished trades (same side, timeframe and state).'),
        if (bad)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('Look-alike learning could not be read now. NOT ENOUGH DATA.', style: context.type.secondary))
        else
          for (final r in rows)
            () {
              final v = '${r['verdict'] ?? 'NOT ENOUGH DATA'}';
              final n = _num(r['n'])?.toInt() ?? 0;
              final name = '${r['name'] ?? _names[r['state']] ?? ''}';
              return _row(
                context,
                p,
                [OwlChip(name, _stColor(p, name)), OwlChip(v, _vColor(p, v)), Text('$n scored calls', style: context.type.metadata)],
                n < minN ? 'NOT ENOUGH DATA: $n of $minN scored calls so far.' : '${r['text'] ?? ''}',
              );
            }(),
      ],
    );
  }

  // ---- MISTAKE PATTERNS ----
  Widget _mistakes(BuildContext context, AppPalette p) {
    final stats = _map(learn['stats']);
    final led = _maps(stats['ledger']);
    final gaps = _map(_map(learn['look'])['gaps']);
    final total = led.fold<int>(0, (a, r) => a + (_num(r['mistakes'])?.toInt() ?? 0));
    final hint = led.any((r) => _hints.contains('${r['verdict']}'));
    return OwlFold(
      title: 'MISTAKE PATTERNS',
      headline: led.isEmpty ? 'NOT ENOUGH DATA' : '$total wrong Brain calls recorded',
      headlineColor: hint ? p.warning : p.textMuted,
      children: [
        _note(context, 'Where the Brain was wrong before. These are observed facts about past trades, NOT trading rules.'),
        if (led.isEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text('No finished trades with Brain calls yet. NOT ENOUGH DATA.', style: context.type.secondary)),
        for (final r in led)
          () {
            final v = '${r['verdict'] ?? 'NOT ENOUGH DATA'}';
            final st = '${r['state']}';
            final name = _names[st] ?? st;
            final n = _num(r['n'])?.toInt() ?? 0;
            final m = _num(r['mistakes'])?.toInt() ?? 0;
            return _row(
              context,
              p,
              [OwlChip(name, _stColor(p, name)), OwlChip(v, _vColor(p, v)), Text('$m of $n calls', style: context.type.metadata)],
              '${r['label'] ?? ''}',
              _hints.contains(v) ? '${r['text'] ?? ''}' : null,
            );
          }(),
        if (gaps.values.any((e) => e is List && e.isNotEmpty))
          for (final e in gaps.entries)
            if (e.value is List && (e.value as List).isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text(
                  'Observed historical difference (not a rule), ${_names[e.key] ?? e.key}: ${_maps(e.value).map((x) => '${_feat['${x['feat']}'] ?? x['feat']} ${_sg(_num(x['gap']), 2)}').join(', ')} (wrong calls vs right calls, in standard deviations).',
                  style: context.type.metadata,
                ),
              ),
      ],
    );
  }

  // ---- SHADOW CHECK ----
  Widget _shadow(BuildContext context, AppPalette p) {
    final sh = _map(learn['shadow']);
    final cnt = _map(sh['counts']);
    final sc = _map(sh['score']);
    final minN = _num(sh['min_n'])?.toInt() ?? 30;
    final bad = sh.isEmpty || '${sh['status']}' == 'error';
    int c(String k) => _num(cnt[k])?.toInt() ?? 0;
    final seen = sc.values.any((e) => _hints.contains('${_map(e)['verdict']}'));
    return OwlFold(
      title: 'SHADOW CHECK',
      headline: bad ? 'NOT ENOUGH DATA' : 'HOLD ${c('HOLD_OK')}  |  PROTECT ${c('PROTECT_LOOKS_BETTER')}  |  NO OPINION ${c('NO_OPINION')}',
      headlineColor: seen ? p.accent : p.textMuted,
      children: [
        _note(context, 'What the Brain would have said on each closed candle of open trades, saved at that moment and never changed. Paper numbers only, nothing is traded.'),
        if (bad)
          Padding(padding: const EdgeInsets.only(top: 6), child: Text('The shadow check could not be read now. NOT ENOUGH DATA.', style: context.type.secondary))
        else
          for (final k in const ['HOLD_OK', 'PROTECT_LOOKS_BETTER'])
            () {
              final r = _map(sc[k]);
              final v = '${r['verdict'] ?? 'NOT ENOUGH DATA'}';
              final n = _num(r['n'])?.toInt() ?? 0;
              final pend = _num(r['pending'])?.toInt() ?? 0;
              final dir = '${r['dir']}';
              String t = 'NOT ENOUGH DATA: $n of $minN judged trades so far.';
              if (n >= minN) t = 'Paper result if followed: ${_sg(_num(r['if_followed']))} points per trade.';
              if (_hints.contains(v)) t += dir == 'right' ? ' Following it did better than usual.' : ' Following it did worse than usual.';
              return _row(
                context,
                p,
                [OwlChip(k == 'HOLD_OK' ? 'HOLD' : 'PROTECT', p.textMuted), OwlChip(v, _vColor(p, v)), Text('judged $n, waiting $pend', style: context.type.metadata)],
                t,
              );
            }(),
        if (!bad) Padding(padding: const EdgeInsets.only(top: 8), child: _note(context, 'NO OPINION is a normal answer: it means the Brain had no evidence to speak.')),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    if (learn.isEmpty) return const SizedBox.shrink();
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [_look(context, p), _mistakes(context, p), _shadow(context, p)]);
  }
}
