import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';
import '../widgets/owl_pressable.dart';

/// R17a: the ONE BANNER on top of the Sniper tab (it replaces the old text headline).
///   1. the word: EXPLORE / LEARNED (or NOT LEARNED YET / OFF), big
///   2. LEARN n of 30 paper trades (+ wins, net USDT when there are trades)
///   3. the unseen-days test in one line: model picks vs take-everything, in R per trade after fees (or why there is no test yet)
///   4. ONE why-quiet chip: the first reason in plain words; tap = all reasons
///   5. small line: checked / learned ago, working in the background, old candles
/// Data: [r] = GET /api/v2/sniper (headline, ages), [learn] = GET /api/v2/sniper_learn (progress), [auto] = GET /api/v2/sniper_autopilot (R3b: state, reasons, compare).
/// Any of the three may be null (still loading) or an error map: the banner then says so in plain words and never prints "null". Read only, paper only. Dart NOT compiled (the APK build is the proof).
class SniperStateBanner extends StatefulWidget {
  final Map<String, dynamic> r;
  final Map<String, dynamic>? learn, auto;
  const SniperStateBanner({super.key, required this.r, this.learn, this.auto});

  @override
  State<SniperStateBanner> createState() => _SniperStateBannerState();
}

class _SniperStateBannerState extends State<SniperStateBanner> {
  bool _more = false;

  static Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static double? _d(Object? v) => v is num && v.isFinite ? v.toDouble() : null;
  static int? _i(Object? v) => v is num && v.isFinite ? v.toInt() : null;
  static String _sg(double v, [int d = 2]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}';

  static String _ago(Object? s) {
    if (s is! num) return 'not yet';
    final n = s.toInt();
    if (n < 90) return '${n}s ago';
    if (n < 5400) return '${(n / 60).round()} min ago';
    return '${(n / 3600).toStringAsFixed(1)} h ago';
  }

  /// The word of the autopilot state.
  String _word(Map<String, dynamic>? a) {
    if (a == null) return 'LOADING';
    if (a['state'] == 'error' || a['state'] == 'old') return 'NO ANSWER';
    switch ('${a['state'] ?? ''}') {
      case 'LEARNED':
        return 'LEARNED';
      case 'EXPLORE':
        return 'PRACTISING';
      case 'off':
        return 'OFF';
    }
    return 'STILL LEARNING';
  }

  Color _color(AppPalette p, String word) => word == 'LEARNED' ? p.profit : (word == 'PRACTISING' ? p.warning : p.textMuted);

  String _learnLine(Map<String, dynamic>? l) {
    if (l == null) return 'LEARN paper trades: loading...';
    final pg = _m(_m(l['learn'])['progress']);
    final n = _i(pg['n']);
    if (n == null) return 'LEARN paper trades: no answer yet.';
    final w = _i(pg['wins']);
    final net = _d(pg['net_usdt']);
    final extra = n == 0 ? '' : '  |  ${w == null ? '' : '$w won  |  '}${net == null ? '' : '${_sg(net)} USDT'}';
    return 'LEARN $n of 30 paper trades$extra';
  }

  /// Part 5: the LEARN progress at hero size: big "n / 30", the bar, then WON | LOST | NET (only what the backend really sent; lost = n - won), and a red chip if the kill switch is on.
  /// No made-up number: a missing value prints "--". (The clean-samples count is not in this answer, so it is not shown here.)
  Widget _learnHero(BuildContext context) {
    final p = context.palette;
    final l = widget.learn;
    if (l == null) return Text('LEARN paper trades: loading...', style: context.type.secondary);
    final pg = _m(_m(l['learn'])['progress']);
    final n = _i(pg['n']);
    if (n == null) return Text('LEARN paper trades: no answer yet.', style: context.type.secondary);
    final w = _i(pg['wins']);
    final net = _d(pg['net_usdt']);
    final lost = w == null ? null : (n - w).clamp(0, n);
    final netColor = net == null || net == 0 ? p.textPrimary : (net > 0 ? p.profit : p.loss);
    final ex = _m(_m(widget.auto)['executor']);
    final killOn = _m(ex['kill'])['on'] == true;
    Widget mini(String label, String value, Color c) => Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, maxLines: 1, style: context.type.label.copyWith(fontSize: 10.5, letterSpacing: 0.6)),
            const SizedBox(height: 1),
            Text(value, maxLines: 1, softWrap: false, overflow: TextOverflow.fade, style: context.type.number.copyWith(fontSize: 16, fontWeight: FontWeight.w700, color: c)),
          ]),
        );
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text('$n', style: context.type.number.copyWith(fontSize: 32, fontWeight: FontWeight.w800, color: n >= 30 ? p.profit : p.textPrimary)),
        Text(' / 30', style: context.type.number.copyWith(fontSize: 18, color: p.textMuted)),
        const SizedBox(width: 10),
        Expanded(child: Padding(padding: const EdgeInsets.only(bottom: 5), child: Text('LEARN paper trades', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(letterSpacing: 0.6)))),
        if (killOn)
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(color: p.loss.withOpacity(0.14), borderRadius: BorderRadius.circular(20), border: Border.all(color: p.loss.withOpacity(0.5))),
            child: Text('KILL SWITCH ON', style: context.type.label.copyWith(color: p.loss, fontWeight: FontWeight.w800, fontSize: 10.5)),
          ),
      ]),
      _bar(p, l),
      if (n > 0) ...[
        const SizedBox(height: 6),
        Row(children: [mini('WON', w == null ? '--' : '$w', p.profit), mini('LOST', lost == null ? '--' : '$lost', lost != null && lost > 0 ? p.loss : p.textPrimary), mini('NET USDT', net == null ? '--' : _sg(net), netColor)]),
      ],
      if (n < 30) Padding(padding: const EdgeInsets.only(top: 6), child: Text('Too early for a verdict: ${30 - n} more trades.', style: context.type.metadata)),
    ]);
  }

  /// Part 13c: a thin bar under the LEARN line (n of 30). Nothing when the count is unknown (never a made-up 0 %).
  Widget _bar(AppPalette p, Map<String, dynamic>? l) {
    final n = l == null ? null : _i(_m(_m(l['learn'])['progress'])['n']);
    if (n == null) return const SizedBox.shrink();
    final frac = (n / 30.0).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 2),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(3),
        child: Stack(children: [
          Container(height: 5, color: p.border),
          FractionallySizedBox(widthFactor: frac, child: Container(height: 5, color: frac >= 1 ? p.profit : p.warning)),
        ]),
      ),
    );
  }

  String _testLine(Map<String, dynamic>? a) {
    if (a == null) return 'Unseen-days test: loading...';
    final c = _m(a['compare']);
    final pick = _m(c['test_picked']);
    final all = _m(c['test_all']);
    final pa = _d(pick['avg_r']);
    final aa = _d(all['avg_r']);
    if (c.isEmpty || aa == null) {
      final nt = _i(a['n_test']);
      return 'Unseen-days test: not done yet${nt == null ? '' : ' ($nt test trades)'}.';
    }
    final pn = _i(pick['trades']) ?? 0;
    final an = _i(all['trades']) ?? 0;
    final left = pa == null ? 'model picked no trade' : 'model picks ${_sg(pa, 3)} R each ($pn trades)';
    return 'Unseen days: $left  vs  take-all ${_sg(aa, 3)} R each ($an trades). After fees.';
  }

  List<String> _reasons(Map<String, dynamic>? a) {
    final v = a?['reasons'];
    return v is List ? [for (final x in v) if ('$x'.trim().isNotEmpty) '$x'.trim()] : <String>[];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final r = widget.r;
    final word = _word(widget.auto);
    final color = _color(p, word);
    final reasons = _reasons(widget.auto);
    final stale = r['stale_coins'] is num ? (r['stale_coins'] as num).toInt() : 0;
    final first = reasons.isEmpty ? '' : (reasons.first.length > 90 ? '${reasons.first.substring(0, 88)}...' : reasons.first);
    return OWLCard(
      edge: color == p.textMuted ? null : color,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: color.withOpacity(0.14), borderRadius: BorderRadius.circular(20), border: Border.all(color: color.withOpacity(0.5))),
            child: Text(word, style: context.type.label.copyWith(color: color, fontWeight: FontWeight.w800, letterSpacing: 0.5)),
          ),
          const SizedBox(width: 8),
          Expanded(child: Text('OwlSniper: paper only, watch', style: context.type.metadata)),
        ]),
        const SizedBox(height: 8),
        _learnHero(context),
        const SizedBox(height: 4),
        Text(_testLine(widget.auto), style: context.type.secondary),
        if (first.isNotEmpty) ...[
          const SizedBox(height: 8),
          OWLPressable(
            onTap: () => setState(() => _more = !_more),
            pressedScale: 0.99,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
              decoration: BoxDecoration(color: p.bg, borderRadius: BorderRadius.circular(12), border: Border.all(color: p.border)),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('Why quiet: ', style: context.type.metadata.copyWith(fontWeight: FontWeight.w800, color: p.textSecondary)),
                Expanded(child: Text(_more ? reasons.join('\n') : first, style: context.type.metadata.copyWith(color: p.textPrimary))),
                Icon(_more ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 18, color: p.textMuted),
              ]),
            ),
          ),
        ],
        const SizedBox(height: 6),
        Text(
          'checked ${_ago(r['updated_ago_sec'])}  |  learned ${_ago(r['model_ago_sec'])}${r['refreshing'] == true ? '  |  working in the background...' : ''}${stale > 0 ? '  |  $stale coins have old candles' : ''}',
          style: context.type.metadata,
        ),
      ]),
    );
  }
}
