import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/lazy_fold.dart';
import '../widgets/risk_box.dart';
import 'capital_card.dart';
import 'sniper_selflog.dart';

/// Part 46 (FILE 55): the finished Sniper cards of Parts 12, 35 and 44 on the Sniper tab, as three CLOSED folds: Risk Box, Small account, Self log.
/// Nothing is requested until a fold is opened (LazyFold). The Risk Box uses the first order card of the newest scan: a card that PASSES uses its own side, any other card asks the Sniper's own signal (side empty).
/// No card = a plain line, no request. Read only, paper only. Use: SniperExtras(r: r) with r = the live scan answer. Dart NOT compiled (the APK build is the proof).
Map<String, dynamic>? _top(Object? cards) {
  if (cards is! List) return null;
  Map<String, dynamic>? first;
  for (final c in cards) {
    if (c is! Map || '${c['symbol'] ?? ''}'.isEmpty) continue;
    final m = Map<String, dynamic>.from(c);
    first ??= m;
    if (m['action'] == 'SNIPER_LONG' || m['action'] == 'SNIPER_SHORT') return m;
  }
  return first;
}

class SniperExtras extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperExtras({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final top = _top(r['cards']);
    final sym = top == null ? '' : '${top['symbol']}';
    final passes = top != null && (top['action'] == 'SNIPER_LONG' || top['action'] == 'SNIPER_SHORT');
    final side = passes ? '${top!['side'] ?? ''}' : '';
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      LazyFold(
        title: 'Risk Box',
        sub: sym.isEmpty ? 'No signal yet' : '$sym${side.isEmpty ? '' : ' $side'}',
        builder: () => sym.isEmpty
            ? Padding(padding: const EdgeInsets.all(6), child: Text('No order card yet, so there is no coin to check. The Risk Box opens when a signal appears.', style: TextStyle(fontSize: 12, color: p.textMuted)))
            : RiskBox(symbol: sym, side: side),
      ),
      const SizedBox(height: 8),
      LazyFold(title: 'Small account', sub: '10 USDT paper replay, one book at a time', builder: () => const CapitalCard(capital: 10)),
      const SizedBox(height: 8),
      LazyFold(title: 'Self log', sub: 'What Sniper learned, its mistakes, what changed', builder: () => const SniperSelfLog()),
    ]);
  }
}
