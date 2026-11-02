import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Round 27 (OwlSniper), part 2 of 2 of the new Sniper tab: the SNIPER vs MAIN BOT panel. Read-only. Fed by r['compare'] of GET /api/v2/sniper (backend owl_sniper_cmp.py).
/// Left = the Sniper's replay on the unseen TEST days (saved candles, 10 USDT base, fees + slippage). Right = the main paper bot's REAL closed paper trades of the same number of days.
/// A word (SNIPER AHEAD / MAIN BOT AHEAD) only comes from the backend when BOTH sides have 15+ trades and the gap is clear; else TOO CLOSE or NOT ENOUGH DATA.
/// Then: for each live Sniper card, is the main bot in that coin and whose entry price is better. Different coins, days and sizes: a hint, never a proof. A missing number prints "--".
/// Nothing here sends an order or changes anything. Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
double? _n(Object? v) => v is num ? v.toDouble() : null;
String _net(double? v) => v == null ? '--' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';
String _pc(double? v) => v == null ? '--' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%';

class SniperComparePanel extends StatelessWidget {
  final Map<String, dynamic> r;
  const SniperComparePanel({super.key, required this.r});

  Widget _col(AppPalette p, String title, String sub, Map<String, dynamic> d, {bool bot = false}) {
    final net = _n(d['net_usdt']);
    final c = net == null || net == 0 ? p.textPrimary : (net > 0 ? p.profit : p.loss);
    final n = (_n(d['trades']) ?? 0).toInt();
    return Expanded(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text(sub, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
        const SizedBox(height: 6),
        Text('${_net(net)} USDT', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: c)),
        Text('$n trades', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
        Text('${_pc(_n(d['avg_pct']))} per trade', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
        if (bot) Text('${(_n(d['wins']) ?? 0).toInt()} won, ${(_n(d['losses']) ?? 0).toInt()} lost', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final cmp = _m(r['compare']);
    if (cmp.isEmpty || cmp['state'] != null) {
      return OWLCard(
        child: Text(cmp['state'] == 'error' ? 'The comparison could not be made right now.' : 'The comparison is not in this backend answer yet. Install the newest backend zip.',
            style: TextStyle(fontSize: 12, color: p.textMuted)),
      );
    }
    final v = '${cmp['verdict'] ?? 'NOT_ENOUGH_DATA'}';
    final label = v == 'SNIPER_AHEAD' ? 'SNIPER AHEAD' : v == 'BOT_AHEAD' ? 'MAIN BOT AHEAD' : v == 'TOO_CLOSE' ? 'TOO CLOSE' : 'NOT ENOUGH DATA';
    final c = v == 'SNIPER_AHEAD' ? p.profit : v == 'BOT_AHEAD' ? p.warning : p.textMuted;
    final days = (_n(cmp['days']) ?? 0).toInt();
    final coins = _l(cmp['same_coin']).take(5).toList();
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('Sniper vs Main Bot', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
            child: Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: c)),
          ),
        ]),
        const SizedBox(height: 6),
        Text('${cmp['text'] ?? ''}', style: TextStyle(fontSize: 12, color: p.textSecondary)),
        const SizedBox(height: 10),
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _col(p, 'Sniper', 'replay, $days days', _m(cmp['sniper'])),
          const SizedBox(width: 12),
          _col(p, 'Main bot', 'real paper trades, $days days', _m(cmp['bot']), bot: true),
        ]),
        if (coins.isNotEmpty) ...[
          const Divider(height: 20),
          Text('Same coin right now', style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary)),
          const SizedBox(height: 4),
          for (final k in coins)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text.rich(TextSpan(children: [
                TextSpan(text: '${k['symbol'] ?? '--'}  ${k['sniper_side'] ?? ''}: ', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: p.textPrimary)),
                TextSpan(text: '${_m(k['versus'])['text'] ?? k['text'] ?? '--'}', style: TextStyle(fontSize: 11.5, color: p.textSecondary)),
              ])),
            ),
        ],
        const SizedBox(height: 8),
        Text('${cmp['caveat'] ?? ''}', style: TextStyle(fontSize: 10.5, color: p.textMuted)),
      ]),
    );
  }
}
