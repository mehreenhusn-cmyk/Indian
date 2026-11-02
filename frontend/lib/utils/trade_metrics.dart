/// Round 16: pure maths for the position detail screen (no widgets, no network, nothing is traded).
/// Candles come from AppProvider.fetchCandles (maps with timestamp / open / high / low / close, oldest first, the last one may still be forming).
/// A number that cannot be worked out is null and the screen prints "--", never "None".
class TradeMetrics {
  final int candlesHeld;
  final int candlesUsed; // full candles after the entry that were used for the extremes
  final double? mfePct; // best move in the trade's favour, % of entry price (from candle wicks + now)
  final double? maePct; // worst move against the trade, % of entry price
  final double? nowPct;
  final double? givebackPct; // MFE minus where the trade is now (0 when it sits at its best)
  final double? givebackShare; // give-back as % of the MFE
  final bool olderThanCandles; // the trade is older than the loaded candles, so MFE / MAE are only a part of the story
  const TradeMetrics({required this.candlesHeld, required this.candlesUsed, this.mfePct, this.maePct, this.nowPct, this.givebackPct, this.givebackShare, this.olderThanCandles = false});
}

/// One line of "indicator health": does this indicator stand WITH the trade, AGAINST it, or is it unknown / neutral.
class HealthLine {
  final String label;
  final String text;
  final String state; // 'with' | 'against' | 'unknown'
  const HealthLine(this.label, this.text, this.state);
}

double _tsSec(dynamic v) {
  final t = v is num ? v.toDouble() : 0.0;
  return t > 1e11 ? t / 1000.0 : t; // the app sends milliseconds; seconds are accepted too
}

double? _num(dynamic v) => v is num ? v.toDouble() : null;

TradeMetrics tradeMetrics({required List<dynamic> candles, required bool isLong, double? entry, double? ltp, double? openedSec}) {
  if (entry == null || entry <= 0 || openedSec == null || candles.length < 2) return const TradeMetrics(candlesHeld: 0, candlesUsed: 0);
  final tf = (_tsSec((candles.last as Map)['timestamp']) - _tsSec((candles[candles.length - 2] as Map)['timestamp'])).abs();
  var held = 0, used = 0;
  var hi = entry, lo = entry;
  for (final c in candles) {
    if (c is! Map) continue;
    final t = _tsSec(c['timestamp']);
    if (t + tf > openedSec) held++; // the candle that was running at the entry counts as the first one held
    final h = _num(c['high']), l = _num(c['low']);
    if (t >= openedSec && h != null && l != null) { // only candles that started after the entry: the entry candle's wick may be older than the trade
      used++;
      if (h > hi) hi = h;
      if (l < lo) lo = l;
    }
  }
  if (ltp != null) {
    if (ltp > hi) hi = ltp;
    if (ltp < lo) lo = ltp;
  }
  final mfe = isLong ? (hi - entry) / entry * 100 : (entry - lo) / entry * 100;
  final mae = isLong ? (entry - lo) / entry * 100 : (hi - entry) / entry * 100;
  final now = ltp == null ? null : (isLong ? (ltp - entry) / entry * 100 : (entry - ltp) / entry * 100);
  final give = now == null ? null : (mfe - now).clamp(0.0, double.infinity).toDouble();
  final first = _tsSec((candles.first as Map)['timestamp']);
  return TradeMetrics(candlesHeld: held, candlesUsed: used, mfePct: mfe, maePct: mae, nowPct: now, givebackPct: give,
      givebackShare: (give == null || mfe <= 0) ? null : give / mfe * 100, olderThanCandles: openedSec < first);
}

/// Pine-style EMA: the seed is the SMA of the first n real values, then alpha = 2 / (n + 1). Leading nulls are allowed.
List<double?> emaAny(List<double?> x, int n) {
  final out = List<double?>.filled(x.length, null);
  final f = x.indexWhere((v) => v != null);
  if (f < 0 || x.length - f < n) return out;
  var e = 0.0;
  for (var i = f; i < f + n; i++) { e += x[i]!; }
  e /= n;
  out[f + n - 1] = e;
  final a = 2.0 / (n + 1);
  for (var i = f + n; i < x.length; i++) { e = a * x[i]! + (1 - a) * e; out[i] = e; }
  return out;
}

double? _last(List<double?> x) => x.isEmpty ? null : x.last;

/// The three Owl Sniper indicators (EMA cloud 30 / 50, TSI 25 / 5 with signal 14, Z-Score over 200) read on the newest candle.
List<HealthLine> indicatorHealth({required List<dynamic> candles, required bool isLong}) {
  final c = <double>[for (final x in candles) if (x is Map && _num(x['close']) != null) _num(x['close'])!];
  final side = isLong ? 'LONG' : 'SHORT';
  if (c.length < 60) return [HealthLine('Indicators', 'Only ${c.length} candles loaded, about 60 are needed.', 'unknown')];
  final lines = <HealthLine>[];
  final f = _last(emaAny(c, 30)), s = _last(emaAny(c, 50));
  if (f != null && s != null) {
    final up = f > s;
    lines.add(HealthLine('EMA cloud 30 / 50', up ? 'Fast above slow (bullish).' : 'Fast below slow (bearish).', up == isLong ? 'with' : 'against'));
  }
  final d = <double?>[for (var i = 1; i < c.length; i++) c[i] - c[i - 1]];
  final ad = <double?>[for (final v in d) v!.abs()];
  final top = emaAny(emaAny(d, 25), 5), den = emaAny(emaAny(ad, 25), 5);
  final tsi = <double?>[for (var i = 0; i < d.length; i++) (top[i] == null || den[i] == null || den[i] == 0) ? null : 100.0 * top[i]! / den[i]!];
  final tsi0 = _last(tsi), sig = _last(emaAny(tsi, 14));
  if (tsi0 != null && sig != null) {
    final up = tsi0 > sig;
    lines.add(HealthLine('TSI 25 / 5', up ? 'TSI above its signal (bullish).' : 'TSI below its signal (bearish).', up == isLong ? 'with' : 'against'));
  }
  if (c.length >= 200) {
    final w = c.sublist(c.length - 200);
    final m = w.reduce((a, b) => a + b) / 200;
    var v = 0.0;
    for (final x in w) { v += (x - m) * (x - m); }
    final sd = v / 200 > 0 ? _sqrt(v / 200) : 0.0;
    final z = sd > 0 ? (c.last - m) / sd : 0.0;
    final inside = isLong ? (z > -2.2 && z < 1.2) : (z > -1.2 && z < 2.2); // the Owl Sniper zone for this side
    lines.add(HealthLine('Z-Score 200', 'Z = ${z.toStringAsFixed(2)}; ${inside ? 'inside' : 'outside'} the $side zone.', inside ? 'with' : 'against'));
  } else {
    lines.add(HealthLine('Z-Score 200', 'Needs 200 candles, ${c.length} loaded.', 'unknown'));
  }
  return lines;
}

double _sqrt(double x) { // Newton steps, so this file needs no import
  var g = x > 1 ? x / 2 : 1.0;
  for (var i = 0; i < 40; i++) { g = (g + x / g) / 2; }
  return g;
}
