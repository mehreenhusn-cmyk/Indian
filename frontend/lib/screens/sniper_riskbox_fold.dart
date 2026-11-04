import 'package:flutter/material.dart';
import '../widgets/lazy_fold.dart';
import '../widgets/risk_box.dart';

/// R17 (Risk Box move): the Risk Box now sits right under the order cards on the Sniper tab, not inside the 'MORE SNIPER PANELS' fold.
/// It shows ONLY when the newest scan has an order card (no card = nothing is drawn, the WHY QUIET fold already explains the silence).
/// The fold is closed and lazy: nothing is requested from GET /api/v2/sniper_riskbox until it is opened.
/// A card that PASSES uses its own side, any other card asks the Sniper's own signal (side empty). Read only, paper only.
/// Use: SniperRiskBoxFold(r: r) with r = the live scan answer. Dart NOT compiled (the APK build is the proof).
Map<String, dynamic>? sniperTopCard(Object? cards) {
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

class SniperRiskBoxFold extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperRiskBoxFold({super.key, required this.r});

  @override
  Widget build(BuildContext context) {
    final top = sniperTopCard(r['cards']);
    if (top == null) return const SizedBox.shrink();
    final sym = '${top['symbol']}';
    final passes = top['action'] == 'SNIPER_LONG' || top['action'] == 'SNIPER_SHORT';
    final side = passes ? '${top['side'] ?? ''}' : '';
    return LazyFold(
      title: 'Risk Box',
      sub: '$sym${side.isEmpty ? '' : ' $side'}',
      builder: () => RiskBox(symbol: sym, side: side),
    );
  }
}
