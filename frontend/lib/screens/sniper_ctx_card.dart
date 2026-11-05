import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R30 (Part 5, Sniper tab): MARKET CONTEXT = what the Sniper now sees besides the coin itself: the BTC move (1 / 3 / 12 candles of 5m), the BTC trend (EMA30 vs EMA50) and the session (Asia / Europe / US).
/// Data: GET /api/v2/sniper_ctx (read only), loaded by sniper_screen.dart. BTC is only a set of NUMBERS for the Sniper to learn from: it is never added to any P&L, win rate or equity (the card says so).
/// A missing number prints "--", never "null". Every word and number comes from the backend. Dart NOT compiled.
double? _n(Object? v) => v is num ? v.toDouble() : null;
String _pct(Object? v) => _n(v) == null ? '--' : '${_n(v)! >= 0 ? '+' : ''}${_n(v)!.toStringAsFixed(2)}%';

class SniperCtxCard extends StatelessWidget {
  final Map<String, dynamic>? g;
  const SniperCtxCard({super.key, required this.g});

  Widget _line(AppPalette p, String t, {Color? c, double size = 12.5, bool bold = false}) =>
      Padding(padding: const EdgeInsets.only(top: 4), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w400)));

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (g == null) return OWLCard(child: Text('Loading the market context...', style: TextStyle(fontSize: 12, color: p.textSecondary)));
    final c = g!['ctx'] is Map ? Map<String, dynamic>.from(g!['ctx'] as Map) : null;
    if (g!['state'] != 'ok' || c == null) {
      return OWLCard(edge: p.warning, child: Text('${g!['text'] ?? 'The market context is not available from this backend yet. Install the newest backend zip, restart it, then pull down.'}', style: TextStyle(fontSize: 12.5, color: p.textPrimary)));
    }
    final tr = _n(c['btc_trend']);
    final trend = tr == null ? '--' : (tr > 0 ? 'UP (EMA30 above EMA50)' : (tr < 0 ? 'DOWN (EMA30 below EMA50)' : 'FLAT'));
    final col = tr == null || tr == 0 ? p.textPrimary : (tr > 0 ? p.profit : p.loss);
    final age = _n(g!['age_sec']);
    return OWLCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('BTC  |  session ${g!['session'] ?? '--'}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Move: 1 candle ${_pct(c['btc_1'])}  |  3 candles ${_pct(c['btc_3'])}  |  12 candles ${_pct(c['btc_12'])}', c: p.textPrimary),
        _line(p, 'Trend: $trend', c: col, bold: true),
        if (age != null) _line(p, 'Newest BTC candle is ${(age / 60).round()} min old', size: 11.5, c: p.textMuted),
        _line(p, 'The Sniper learns from 7 of these numbers (BTC move, BTC trend, hour of day, coin vs BTC), so it can see when the whole market moves against a trade. BTC is only a hint for learning: it is never added to any P&L, win rate or equity.', size: 11.5),
      ]),
    );
  }
}
