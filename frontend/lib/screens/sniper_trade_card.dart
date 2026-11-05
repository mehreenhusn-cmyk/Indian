import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// R29a (Sniper tab): the TRADE RECORD. Data: GET /api/v2/sniper_trades (read only, paper only), loaded by sniper_screen.dart.
/// One card per Sniper trade (open first, then the newest closed): coin + side + lane chip, the signal and WHY (basis), entry / TP / SL, expected profit and risk in USDT, how long it may be held,
/// and for a closed trade the result, the exit reason, expected vs real and the lesson. Every word and number comes from the backend. The live chart and positions list come in Part 4. Dart NOT compiled.
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List _l(Object? v) => v is List ? v : const [];
double? _n(Object? v) => v is num ? v.toDouble() : null;
String _px(Object? v) {
  final x = _n(v);
  if (x == null) return '-';
  return x.abs() >= 100 ? x.toStringAsFixed(2) : (x.abs() >= 1 ? x.toStringAsFixed(4) : x.toStringAsPrecision(4));
}

String _usd(Object? v) => _n(v) == null ? '-' : '${_n(v)! >= 0 ? '+' : ''}${_n(v)!.toStringAsFixed(2)} USDT';
String _mins(Object? s) => _n(s) == null ? '-' : (_n(s)! >= 3600 ? '${(_n(s)! / 3600).toStringAsFixed(1)} h' : '${(_n(s)! / 60).round()} min');

class SniperTradeRecord extends StatelessWidget {
  final Map<String, dynamic>? g;
  const SniperTradeRecord({super.key, required this.g});

  Widget _line(AppPalette p, String t, {Color? c, double size = 12, bool bold = false}) =>
      Padding(padding: const EdgeInsets.only(top: 3), child: Text(t, style: TextStyle(fontSize: size, color: c ?? p.textSecondary, fontWeight: bold ? FontWeight.w700 : FontWeight.w400)));

  Widget _card(AppPalette p, Map<String, dynamic> t, bool open) {
    final pnl = _n(t['pnl_usdt']);
    final long = t['side'] == 'LONG';
    final basis = _l(t['basis']).take(3).map((e) => '$e').join(' + ');
    final c = open ? p.warning : ((pnl ?? 0) >= 0 ? p.profit : p.loss);
    return OWLCard(
      edge: c,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('${t['symbol']}  ${long ? 'LONG' : 'SHORT'}', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary))),
          Text(open ? 'OPEN  ${t['lane'] ?? ''}' : '${t['lane'] ?? ''}', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: c)),
        ]),
        if (t['signal'] != null && '${t['signal']}'.isNotEmpty) _line(p, 'Signal: ${t['reason'] != null && '${t['reason']}'.isNotEmpty ? t['reason'] : t['signal']}', c: p.textPrimary),
        if (basis.isNotEmpty) _line(p, 'Why: $basis'),
        _line(p, 'Entry ${_px(t['entry'] ?? t['entry_price'])}  |  TP ${_px(t['take_profit'])}  |  SL ${_px(t['stop_loss'])}', c: p.textPrimary),
        if (_n(t['expected_usdt']) != null)
          _line(p, 'Expected ${_usd(t['expected_usdt'])} if the target is hit, risk -${_n(t['risk_usdt'])!.toStringAsFixed(2)} USDT (after fees)  |  ${t['rr'] ?? '-'}R'),
        if (_n(t['max_hold_sec']) != null)
          _line(p, 'Hold: up to ${_mins(t['max_hold_sec'])}${_n(t['typical_hold_sec']) != null ? ', typical ${_mins(t['typical_hold_sec'])}' : ''}${open ? '  |  open ${_mins(t['age_sec'])}' : ''}', size: 11.5),
        if (!open) ...[
          _line(p, 'Result ${_usd(pnl)}  |  held ${_mins(t['held_sec'])}  |  exit ${t['exit_reason'] ?? '-'}', c: c, bold: true),
          if (_n(t['vs_expected']) != null) _line(p, 'Against the expected profit: ${_usd(t['vs_expected'])}', size: 11.5),
          if ('${t['lesson'] ?? ''}'.isNotEmpty) _line(p, 'Learned: ${t['lesson']}', size: 11.5),
        ],
        if (t['note'] != null) _line(p, '${t['note']}', size: 11, c: p.textMuted),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (g == null || g!['open'] == null) {
      return OWLCard(child: Text(g == null ? 'Loading the trade record...' : 'The trade record is not available from this backend yet. Install the newest backend zip, restart it, then pull down.', style: TextStyle(fontSize: 12, color: p.textSecondary)));
    }
    final o = _l(g!['open']), c = _l(g!['closed']);
    if (o.isEmpty && c.isEmpty) {
      return OWLCard(child: Text('No Sniper trade yet. Every paper trade will be listed here with its signal, why, entry, TP, SL, expected profit and what it learned.', style: TextStyle(fontSize: 12, color: p.textSecondary)));
    }
    return Column(children: [
      for (final t in o) Padding(padding: const EdgeInsets.only(bottom: 8), child: _card(p, _m(t), true)),
      for (final t in c.take(10)) Padding(padding: const EdgeInsets.only(bottom: 8), child: _card(p, _m(t), false)),
    ]);
  }
}
