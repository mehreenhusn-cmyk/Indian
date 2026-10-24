import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'special_master.dart';
import 'special_master_settings.dart';

const _accent = AppColors.accent;
const _green = AppColors.profit;
const _red = AppColors.loss;

/// EMA line colours. These lines are DISPLAY ONLY - they are computed here in
/// the app purely to draw on the chart. The trading strategy (EMA cross ->
/// BUY/SELL) runs in the backend's strategy.py and is not touched by this.
const _ema30Color = Color(0xFF16C784); // green
const _ema50Color = Color(0xFFFF4D5E); // red

/// Charts are drawn on a WHITE canvas (TradingView-light style) in BOTH app
/// themes. Set to false to make charts follow the app theme again.
const bool kChartForceWhite = true;

bool _chartLight(BuildContext context) =>
    kChartForceWhite || Theme.of(context).brightness == Brightness.light;

/// Chart surface colours for the white canvas (and their dark twins).
const _chartWhiteBg = Color(0xFFFFFFFF);
const _chartInk = Color(0xFF10141C);
const _ema30Light = Color(0xFF16A34A); // green, readable on white
const _ema50Light = Color(0xFFDC2626); // red, readable on white

/// Standard EMA, seeded with the first close and alpha = 2/(len+1) - exactly
/// the same formula strategy.py uses, so the EMA 50 drawn here matches the
/// bot's own EMA when its length is 50.
List<double> computeEma(List<double> closes, int length) {
  if (closes.isEmpty) return <double>[];
  final alpha = 2 / (length + 1);
  final out = <double>[closes[0]];
  for (int i = 1; i < closes.length; i++) {
    out.add(alpha * closes[i] + (1 - alpha) * out[i - 1]);
  }
  return out;
}

/// SD colour family for the SD Bands overlay - one hue, opacity tiered by
/// distance from the mean (mean/zero boldest, ±3 faintest) so the ladder
/// reads as one cohesive element rather than seven competing colours.
const _sdColor = Color(0xFF29B6F6);

/// SD ladder colours: +/-3 red, +/-2 green, +/-1 grey, SD 0 white.
Color _sdLevelColor(String label, [bool light = false]) {
  if (label.contains('3')) return const Color(0xFFEF5350);
  if (label.contains('2')) return const Color(0xFF43A047);
  if (label.contains('1')) return const Color(0xFF9E9E9E);
  return light ? const Color(0xFF1F2937) : Colors.white;
}

/// Rolling mean + population std-dev SD ladder, computed EXACTLY the way
/// backend/recovered_bot/strategy.py's `_rolling_mean_std()` does (same
/// lookback window, same population-variance formula) so the lines drawn
/// here always match the SD levels the strategy itself uses to pick
/// TP1-4 - this is a display-only mirror, it does not feed back into any
/// trading decision.
class SdLevels {
  final double mean, p1, p2, p3, n1, n2, n3;
  const SdLevels(this.mean, this.p1, this.p2, this.p3, this.n1, this.n2, this.n3);
}

SdLevels? computeSdLevels(List<double> closes, {int lookback = 200}) {
  if (closes.isEmpty) return null;
  final start = math.max(0, closes.length - lookback);
  final window = closes.sublist(start);
  final wn = window.length;
  final mean = window.reduce((a, b) => a + b) / wn;
  var variance = 0.0;
  for (final x in window) {
    variance += (x - mean) * (x - mean);
  }
  variance /= wn;
  final std = math.sqrt(variance);
  return SdLevels(mean, mean + std, mean + 2 * std, mean + 3 * std, mean - std, mean - 2 * std, mean - 3 * std);
}

/// Per-candle SD ladder (one SdLevels per candle, null until a full
/// [lookback] window exists - same as TradingView's ta.sma/ta.stdev which
/// are na before that). The LAST entry equals computeSdLevels(closes), so
/// the curve's right end always matches the strategy's TP levels.
List<SdLevels?> computeSdSeries(List<double> closes, {int lookback = 200}) {
  final n = closes.length;
  final out = List<SdLevels?>.filled(n, null);
  for (int i = lookback - 1; i < n; i++) {
    var sum = 0.0;
    for (int j = i - lookback + 1; j <= i; j++) {
      sum += closes[j];
    }
    final mean = sum / lookback;
    var v = 0.0;
    for (int j = i - lookback + 1; j <= i; j++) {
      final d = closes[j] - mean;
      v += d * d;
    }
    final std = math.sqrt(v / lookback);
    out[i] = SdLevels(mean, mean + std, mean + 2 * std, mean + 3 * std, mean - std, mean - 2 * std, mean - 3 * std);
  }
  return out;
}

String _fmtPrice(double p) {
  final a = p.abs();
  if (a >= 1000) return p.toStringAsFixed(2);
  if (a >= 10) return p.toStringAsFixed(3);
  if (a >= 1) return p.toStringAsFixed(4);
  if (a >= 0.01) return p.toStringAsFixed(5);
  return p.toStringAsFixed(7);
}

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/// Candle timestamps are UTC epoch ms; the whole app runs on IST (UTC+5:30).
String _istLabel(int ms, {bool dateAtMidnight = true}) {
  final d = DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true).add(const Duration(hours: 5, minutes: 30));
  if (dateAtMidnight && d.hour == 0 && d.minute == 0) {
    return '${d.day} ${_months[d.month - 1]}';
  }
  final hh = d.hour.toString().padLeft(2, '0');
  final mm = d.minute.toString().padLeft(2, '0');
  return '$hh:$mm';
}

String _istFull(int ms) {
  final d = DateTime.fromMillisecondsSinceEpoch(ms, isUtc: true).add(const Duration(hours: 5, minutes: 30));
  final hh = d.hour.toString().padLeft(2, '0');
  final mm = d.minute.toString().padLeft(2, '0');
  return '${d.day} ${_months[d.month - 1]} $hh:$mm';
}

/// Parsed candle arrays + both EMAs, computed once per data change.
class _Series {
  final List<int> ts;
  final List<double> o;
  final List<double> h;
  final List<double> l;
  final List<double> c;
  final List<double> e30;
  final List<double> e50;
  final SdLevels? sd;
  final List<SdLevels?> sdSeries;

  _Series(this.ts, this.o, this.h, this.l, this.c, this.e30, this.e50, this.sd, this.sdSeries);

  int get n => c.length;

  factory _Series.from(List<dynamic> raw) {
    final ts = <int>[];
    final o = <double>[];
    final h = <double>[];
    final l = <double>[];
    final c = <double>[];
    for (final r in raw) {
      final m = r as Map;
      ts.add((m['timestamp'] as num).toInt());
      o.add((m['open'] as num).toDouble());
      h.add((m['high'] as num).toDouble());
      l.add((m['low'] as num).toDouble());
      c.add((m['close'] as num).toDouble());
    }
    return _Series(ts, o, h, l, c, computeEma(c, 30), computeEma(c, 50), computeSdLevels(c), computeSdSeries(c));
  }
}

/// A flag drawn on the chart at a time + price: "B" = where the BOT exited, "A" = where the AI exited.
/// [note] is a short text next to it (e.g. "-12.4 USDT"). Used by showCandleChartSheet(exits: ...).
class ChartExitMark {
  final int tsMs;
  final double price;
  final String label;
  final Color color;
  final String? note;
  const ChartExitMark({required this.tsMs, required this.price, required this.label, required this.color, this.note});
}

/// "Where did the trade START": a triangle on the entry candle (points up for LONG, down for SHORT) with a short note.
/// label: "B" = bot, "A" = AI, "IN" = both entered at the same place.
class ChartEntryMark {
  final int tsMs;
  final double price;
  final String label;
  final Color color;
  final bool isLong;
  final String? note;
  const ChartEntryMark({required this.tsMs, required this.price, required this.label, required this.color, required this.isLong, this.note});
}

/// A dashed line from the entry point to the exit point of one side (bot or AI), so the whole trade reads as one path.
class ChartTradeLink {
  final int fromTsMs;
  final double fromPrice;
  final int toTsMs;
  final double toPrice;
  final Color color;
  const ChartTradeLink({required this.fromTsMs, required this.fromPrice, required this.toTsMs, required this.toPrice, required this.color});
}

class _RefLine {
  final double price;
  String label;
  final Color color;

  /// true = full dashed line across the plot; false = only a short tick at
  /// the right edge (used for the TPs price is NOT heading to next, so the
  /// chart doesn't fill up with four long green lines).
  final bool full;
  _RefLine(this.price, this.label, this.color, {this.full = true});
}

/// Draws OHLC candles with a plain CustomPainter (no third-party chart
/// package - a new pub dependency has broken builds on this project before).
///
/// Small inline version used inside position cards. Optionally draws
/// Entry/SL/TP1-4 reference lines and the EMA 30 / EMA 50 lines. For the
/// full pan/zoom chart see [showCandleChartSheet].
class CandleChart extends StatelessWidget {
  final List<dynamic> candles;
  final double? entry;
  final double? sl;
  final Map<int, double?>? tpLevels;

  /// Trade open time (ms). Entry/SL/TP lines start at the SIGNAL candle
  /// (like TradingView's trade box) instead of spanning the whole chart.
  final int? entryTsMs;

  /// Draw EMA 30 + EMA 50 (computed over ALL [candles], so pass a few more
  /// candles than [visibleCount] for the EMAs to have warmed up).
  final bool showEma;

  /// Show only the most recent N candles (null = all).
  final int? visibleCount;

  /// Real backend reason there's no candle data (see AppProvider.lastCandleError)
  /// - shown under "No candle data" instead of leaving it unexplained.
  final String? errorText;

  const CandleChart({
    super.key,
    required this.candles,
    this.entry,
    this.sl,
    this.tpLevels,
    this.entryTsMs,
    this.showEma = false,
    this.visibleCount,
    this.errorText,
  });

  @override
  Widget build(BuildContext context) {
    final light = _chartLight(context);
    Widget boxed(Widget c) => light
        ? ClipRRect(
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
            child: ColoredBox(color: _chartWhiteBg, child: c),
          )
        : c;
    if (candles.isEmpty) {
      return boxed(Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('No candle data', style: TextStyle(color: Colors.grey)),
            if (errorText != null) ...[
              const SizedBox(height: 4),
              Text(errorText!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.grey, fontSize: 10)),
            ],
          ],
        ),
      ));
    }
    final series = _Series.from(candles);
    return boxed(CustomPaint(
      painter: _ChartPainter(
        series,
        light: light,
        ema30: showEma,
        ema50: showEma,
        entry: entry,
        sl: sl,
        tp: tpLevels,
        entryTsMs: entryTsMs,
        visibleCount: visibleCount ?? series.n,
        rightBlank: 2,
        compact: true,
      ),
      size: Size.infinite,
    ));
  }
}

/// One painter for both the compact card chart and the full interactive
/// chart.
///
/// Layout model (right-anchored): candle i sits at
///   x(i) = plotW - (rightBlank + (n-1-i) + 0.5) * slot
/// `rightBlank` = number of EMPTY slots between the newest candle and the
/// right edge. Positive = empty "future" space on the right (the chart draws
/// future time labels there); negative = scrolled back into history.
class _ChartPainter extends CustomPainter {
  final _Series s;
  final bool ema30;
  final bool ema50;
  final double? entry;
  final double? sl;
  final Map<int, double?>? tp;
  final int? entryTsMs;
  final List<ChartExitMark>? exits;
  final List<ChartEntryMark>? entries;
  final List<ChartTradeLink>? links;
  final double? slot;
  final int? visibleCount;
  final double rightBlank;
  final bool compact;
  final Offset? cross;

  /// White-canvas colour set (see kChartForceWhite).
  final bool light;

  /// Y-axis (price) zoom/pan - see the paint()-time comment where these are
  /// applied. Null (the compact card chart's default) behaves exactly like
  /// the old always-auto-fit vertical range.
  final double? priceZoom;
  final double? priceShiftFrac;

  /// Special Master "Ob/Os Curl Color": per-candle bar tint (0 none, 1 overbought = red, 2 oversold = green).
  /// Null (compact card chart / Special Master off) = normal green/red candles.
  final List<int>? barTint;

  /// Draws the strategy's Standard Deviation ladder (mean/zero, ±1/2/3 SD)
  /// as faint reference levels - see computeSdLevels() below, which mirrors
  /// backend/recovered_bot/strategy.py's _rolling_mean_std() exactly so
  /// these lines match the actual TP1-4 levels the strategy computes.
  final bool sdBands;

  /// Wall-clock now + configured strategy timeframe, in ms - only used to
  /// draw the candle countdown chip under the current price tag (see
  /// paint() below). Left null (compact-card usage) skips the countdown
  /// entirely, same as every other !compact-only element.
  final int? nowMs;
  final int? timeframeMs;

  /// Live tick price for the newest (still-forming) candle - see
  /// _CandleChartSheetContentState's live-tick animation. When set, the
  /// LAST candle's close is drawn at this price (animated smoothly toward
  /// it frame-by-frame by the caller) and its high/low are widened to
  /// include it, instead of waiting for the next REST poll to move the
  /// forming candle at all. Every OTHER candle is untouched.
  final double? liveClose;

  _ChartPainter(
    this.s, {
    this.ema30 = false,
    this.ema50 = false,
    this.entry,
    this.sl,
    this.tp,
    this.entryTsMs,
    this.exits,
    this.entries,
    this.links,
    this.slot,
    this.visibleCount,
    this.rightBlank = 2,
    this.compact = false,
    this.cross,
    this.liveClose,
    this.nowMs,
    this.timeframeMs,
    this.priceZoom,
    this.priceShiftFrac,
    this.barTint,
    this.sdBands = false,
    this.light = false,
  });

  Color get _ink => light ? _chartInk : Colors.white;
  Color get _e30 => light ? _ema30Light : _ema30Color;
  Color get _e50 => light ? _ema50Light : _ema50Color;

  @override
  void paint(Canvas canvas, Size size) {
    final n = s.n;
    if (n == 0) return;
    final liveIdx = n - 1;
    final hasLive = liveClose != null;
    final _lastC = hasLive ? liveClose! : s.c[liveIdx];
    final _lastH = hasLive ? math.max(s.h[liveIdx], liveClose!) : s.h[liveIdx];
    final _lastL = hasLive ? math.min(s.l[liveIdx], liveClose!) : s.l[liveIdx];
    double cAt(int i) => (hasLive && i == liveIdx) ? _lastC : s.c[i];
    double hAt(int i) => (hasLive && i == liveIdx) ? _lastH : s.h[i];
    double lAt(int i) => (hasLive && i == liveIdx) ? _lastL : s.l[i];
    final axisW = compact ? 0.0 : 64.0;
    final bottomH = compact ? 0.0 : 20.0;
    final plotW = size.width - axisW;
    final plotH = size.height - bottomH;
    if (plotW <= 20 || plotH <= 20) return;

    final slotW = slot ?? plotW / ((visibleCount ?? n) + rightBlank);
    double xOf(num i) => plotW - (rightBlank + (n - 1 - i) + 0.5) * slotW;

    final leftIdxF = (n - 1) + rightBlank + 0.5 - plotW / slotW;
    final rightIdxF = (n - 1) + rightBlank + 0.5;
    final first = math.max(0, leftIdxF.floor() - 1);
    final last = math.min(n - 1, rightIdxF.ceil() + 1);
    var rf = first;
    var rl = last;
    if (first > last) {
      rf = math.max(0, n - 30);
      rl = n - 1;
    }

    // ---- price range from what is on screen (candles + visible EMAs) ----
    var lo = double.infinity;
    var hi = -double.infinity;
    for (int i = rf; i <= rl; i++) {
      lo = math.min(lo, lAt(i));
      hi = math.max(hi, hAt(i));
      if (ema30) {
        lo = math.min(lo, s.e30[i]);
        hi = math.max(hi, s.e30[i]);
      }
      if (ema50) {
        lo = math.min(lo, s.e50[i]);
        hi = math.max(hi, s.e50[i]);
      }
    }
    // Fold the nearer SD bands (zero/±1) into the auto-fit price range so
    // they're normally on-screen without it - the ±2/±3 extremes are left
    // out of this so a quiet, low-volatility symbol doesn't force the whole
    // chart to zoom way out; those two just won't draw if they're outside
    // whatever range is already on screen (same as any other off-screen
    // level here - no special-case needed).
    if (sdBands) {
      for (int i = rf; i <= rl; i++) {
        final sd = s.sdSeries[i];
        if (sd == null) continue;
        for (final p in [sd.mean, sd.p1, sd.n1]) {
          lo = math.min(lo, p);
          hi = math.max(hi, p);
        }
      }
    }
    if (!lo.isFinite || !hi.isFinite) return;
    var natSpan = hi - lo;
    if (natSpan <= 0) natSpan = lo.abs() * 0.002 + 1e-9;

    // ---- Y-axis (price) zoom/pan - mirrors the X-axis slotW/rightBlank
    // model above but for price instead of time. `priceZoom` > 1 = zoomed
    // IN (smaller visible span, candles look taller); `priceShiftFrac` is a
    // pan offset measured as a fraction of the natural (auto-fit) span, so
    // panning feels proportionally consistent at any zoom level. Both
    // default to "off" (1.0 / 0.0) for the compact card chart, which never
    // sets them.
    final zoom = (priceZoom ?? 1.0).clamp(0.15, 8.0);
    final shiftFrac = (priceShiftFrac ?? 0.0).clamp(-4.0, 4.0);
    final mid = (hi + lo) / 2 + natSpan * shiftFrac;
    final span = natSpan / zoom;
    final pad = span * 0.08;
    final top = mid + span / 2 + pad;
    final bottom = mid - span / 2 - pad;
    double yOf(double p) => plotH - (p - bottom) / (top - bottom) * plotH;
    double priceAt(double y) => bottom + (plotH - y) / plotH * (top - bottom);

    // ---- everything inside the plot area is clipped to it ----
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, plotW, plotH));

    // Right of the newest candle stays plain white (the old grey 'future' shading was removed).

    // Grid lines intentionally NOT drawn - clean ultra-dark obsidian
    // background per the OWL Terminal chart restyle (a flat black canvas
    // reads cleaner than TradingView-style grid squares on a phone-sized
    // screen). Time labels are still computed below, just without the
    // vertical ruler line that used to accompany each one.
    final timeLabels = <MapEntry<double, String>>[];
    if (!compact) {
      final step = n >= 2 && s.ts[n - 1] > s.ts[n - 2] ? s.ts[n - 1] - s.ts[n - 2] : 300000;
      final every = math.max(1, (76 / slotW).ceil());
      final jStart = leftIdxF.floor();
      final jEnd = rightIdxF.ceil();
      for (int j = jStart; j <= jEnd; j++) {
        if (j % every != 0) continue;
        final x = xOf(j);
        if (x < 18 || x > plotW - 18) continue;
        final t = s.ts[n - 1] + (j - (n - 1)) * step;
        timeLabels.add(MapEntry(x, _istLabel(t)));
      }
    }

    // ---- Cloud fills (drawn BEHIND candles/lines, TradingView style) ----
    // SD clouds: +-1..+-2 light green, +-2..+-3 light yellow. They follow the
    // SD Bands toggle, so no separate switch is needed.
    if (sdBands) {
      void sdBand(double Function(SdLevels) a, double Function(SdLevels) b, Color color) {
        final upper = <Offset>[];
        final lower = <Offset>[];
        for (int i = first; i <= last; i++) {
          if (i < 0 || i >= n) continue;
          final sdv = s.sdSeries[i];
          if (sdv == null) continue;
          final x = xOf(i);
          upper.add(Offset(x, yOf(a(sdv))));
          lower.add(Offset(x, yOf(b(sdv))));
        }
        if (upper.length < 2) return;
        final path = Path()..moveTo(upper.first.dx, upper.first.dy);
        for (int k = 1; k < upper.length; k++) {
          path.lineTo(upper[k].dx, upper[k].dy);
        }
        for (int k = lower.length - 1; k >= 0; k--) {
          path.lineTo(lower[k].dx, lower[k].dy);
        }
        path.close();
        canvas.drawPath(path, Paint()..color = color..style = PaintingStyle.fill);
      }

      const sdGreen = Color(0x1F43A047); // ~12% green
      const sdYellow = Color(0x1AFFD54F); // ~10% yellow
      sdBand((d) => d.p3, (d) => d.p2, sdYellow);
      sdBand((d) => d.p2, (d) => d.p1, sdGreen);
      sdBand((d) => d.n1, (d) => d.n2, sdGreen);
      sdBand((d) => d.n2, (d) => d.n3, sdYellow);
    }

    // EMA30/EMA50 cloud: green while EMA30 is above EMA50, red while below.
    // Shown only when BOTH EMA chips are on. Crossings are split at the exact
    // intersection so colours flip cleanly. Each colour is ONE path, so there
    // are no seams between neighbouring segments.
    if (!compact && ema30 && ema50) {
      final upPath = Path();
      final dnPath = Path();
      void quad(Path p, double x0, double a0, double b0, double x1, double a1, double b1) {
        p.moveTo(x0, a0);
        p.lineTo(x1, a1);
        p.lineTo(x1, b1);
        p.lineTo(x0, b0);
        p.close();
      }

      for (int i = first; i < last; i++) {
        if (i < 0 || i + 1 >= n) continue;
        final x0 = xOf(i);
        final x1 = xOf(i + 1);
        final a0 = s.e30[i], b0 = s.e50[i];
        final a1 = s.e30[i + 1], b1 = s.e50[i + 1];
        final d0 = a0 - b0;
        final d1 = a1 - b1;
        if (d0 >= 0 && d1 >= 0) {
          quad(upPath, x0, yOf(a0), yOf(b0), x1, yOf(a1), yOf(b1));
        } else if (d0 <= 0 && d1 <= 0) {
          quad(dnPath, x0, yOf(a0), yOf(b0), x1, yOf(a1), yOf(b1));
        } else {
          final t = d0 / (d0 - d1);
          final xc = x0 + (x1 - x0) * t;
          final yc = yOf(a0 + (a1 - a0) * t);
          final first0 = d0 > 0 ? upPath : dnPath;
          final second = d0 > 0 ? dnPath : upPath;
          first0
            ..moveTo(x0, yOf(a0))
            ..lineTo(xc, yc)
            ..lineTo(x0, yOf(b0))
            ..close();
          second
            ..moveTo(xc, yc)
            ..lineTo(x1, yOf(a1))
            ..lineTo(x1, yOf(b1))
            ..close();
        }
      }
      canvas.drawPath(upPath, Paint()..color = _green.withOpacity(0.20)..style = PaintingStyle.fill);
      canvas.drawPath(dnPath, Paint()..color = _red.withOpacity(0.20)..style = PaintingStyle.fill);
    }

    // Candles.
    final bodyW = (slotW * 0.7).clamp(1.0, 18.0).toDouble();
    final wickW = 1.0;
    for (int i = first; i <= last; i++) {
      if (i < 0 || i >= n) continue;
      final up = cAt(i) >= s.o[i];
      final tint = (barTint != null && i < barTint!.length) ? barTint![i] : 0;
      final color = tint == 1 ? const Color(0xFFFF0000) : tint == 2 ? const Color(0xFF17FF00) : (up ? _green : _red);
      final cx = xOf(i);
      canvas.drawLine(
        Offset(cx, yOf(hAt(i))),
        Offset(cx, yOf(lAt(i))),
        Paint()
          ..color = color
          ..strokeWidth = wickW,
      );
      final bTop = yOf(up ? cAt(i) : s.o[i]);
      var bBot = yOf(up ? s.o[i] : cAt(i));
      if ((bBot - bTop).abs() < 1) bBot = bTop + 1;
      canvas.drawRect(Rect.fromLTRB(cx - bodyW / 2, bTop, cx + bodyW / 2, bBot), Paint()..color = color);
    }

    // EMA lines (display only).
    void drawEma(List<double> v, Color color) {
      final path = Path();
      var started = false;
      for (int i = first; i <= last; i++) {
        if (i < 0 || i >= n) continue;
        final x = xOf(i);
        final y = yOf(v[i]);
        if (!started) {
          path.moveTo(x, y);
          started = true;
        } else {
          path.lineTo(x, y);
        }
      }
      if (started) {
        canvas.drawPath(
          path,
          Paint()
            ..color = color
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.0
            ..strokeJoin = StrokeJoin.round,
        );
      }
    }

    if (ema30) drawEma(s.e30, _e30);
    if (ema50) drawEma(s.e50, _e50);

    // Standard Deviation Bands overlay - mean/zero + ±1/2/3 SD, exactly the
    // levels strategy.py's ABCDStrategy picks TP1-4 from. Drawn faint and
    // left-labelled (small, no background chip) so this reads as ambient
    // structure rather than competing with the bold right-side Entry/SL/TP
    // chips for the position that's actually open right now.
    final sdRefsDrawn = <MapEntry<double, String>>[];
    if (sdBands) {
      // One curve per SD level: each candle has its own mean/SD (rolling
      // 200-candle window), joined into a line exactly like TradingView.
      void sdCurve(double? Function(SdLevels) pick, String label, double opacity) {
        final path = Path();
        var started = false;
        double? labelY;
        for (int i = first; i <= last; i++) {
          if (i < 0 || i >= n) continue;
          final sdv = s.sdSeries[i];
          if (sdv == null) continue;
          final v = pick(sdv);
          if (v == null) continue;
          final x = xOf(i);
          final y = yOf(v);
          labelY ??= y;
          if (!started) {
            path.moveTo(x, y);
            started = true;
          } else {
            path.lineTo(x, y);
          }
        }
        if (!started) return;
        canvas.drawPath(
          path,
          Paint()
            ..color = _sdLevelColor(label, light).withOpacity((opacity + 0.25).clamp(0.0, 1.0))
            ..style = PaintingStyle.stroke
            ..strokeWidth = compact ? 0.8 : 1.0
            ..strokeJoin = StrokeJoin.round,
        );
        final ly = labelY;
        if (ly != null && ly > -1 && ly < plotH + 1) {
          sdRefsDrawn.add(MapEntry(ly.clamp(6.0, plotH - 6.0).toDouble(), label));
        }
      }

      sdCurve((d) => d.p3, '+3SD', 0.28);
      sdCurve((d) => d.p2, '+2SD', 0.42);
      sdCurve((d) => d.p1, '+1SD', 0.62);
      sdCurve((d) => d.mean, 'SD 0', 0.85);
      sdCurve((d) => d.n1, '-1SD', 0.62);
      sdCurve((d) => d.n2, '-2SD', 0.42);
      sdCurve((d) => d.n3, '-3SD', 0.28);
    }

    // Lines START at the signal candle (the candle whose close produced the
    // entry) and run to the right edge - exactly how TradingView's trade box
    // looks - instead of spanning the whole chart. The signal candle is the
    // one containing (open time - half a candle): the bot opens within ~1s
    // AFTER the signal candle closes, i.e. already inside the NEXT candle.
    double refStartX = 0.0;
    int tradeIdx = -1;
    if (entryTsMs != null && n >= 2) {
      final stepMs = s.ts[n - 1] > s.ts[n - 2] ? s.ts[n - 1] - s.ts[n - 2] : 300000;
      final target = entryTsMs! - stepMs / 2;
      var idx = -1;
      for (int i = n - 1; i >= 0; i--) {
        if (s.ts[i] <= target) {
          idx = i;
          break;
        }
      }
      if (idx >= 0) {
        refStartX = xOf(idx).clamp(0.0, plotW).toDouble();
        tradeIdx = idx;
      }
    }

    // Reference lines (Entry / SL / TP). TPs are kept readable: TPs price has
    // ALREADY reached are removed, only the NEXT TP gets a full dashed line,
    // the rest are a short tick + right-side chip, and TPs with the exact
    // same price are merged into one label (e.g. "TP2/3/4").
    final refs = <_RefLine>[
      if (sl != null) _RefLine(sl!, 'SL', _red),
      if (entry != null) _RefLine(entry!, 'ENTRY', light ? const Color(0xFF374151) : Colors.white70),
    ];
    if (tp != null) {
      final keys = tp!.keys.where((k) => tp![k] != null).toList()..sort();
      bool? isLongTrade;
      if (entry != null && keys.isNotEmpty) {
        final dd = tp![keys.first]! - entry!;
        if (dd != 0) isLongTrade = dd > 0;
      }
      // Highest high / lowest low since the trade opened (incl. live tick).
      var hiSince = -double.infinity;
      var loSince = double.infinity;
      for (int i = (tradeIdx >= 0 ? math.min(tradeIdx + 1, n - 1) : n - 1); i < n; i++) {
        hiSince = math.max(hiSince, hAt(i));
        loSince = math.min(loSince, lAt(i));
      }
      final tpRefs = <_RefLine>[];
      var nextTaken = false;
      for (final k in keys) {
        final v = tp![k]!;
        final hit = isLongTrade == null ? false : (isLongTrade ? hiSince >= v : loSince <= v);
        if (hit) continue;
        final dup = tpRefs.indexWhere((g) => (g.price - v).abs() <= v.abs() * 1e-9);
        if (dup >= 0) {
          tpRefs[dup].label = '${tpRefs[dup].label}/$k';
          continue;
        }
        tpRefs.add(_RefLine(v, 'TP$k', _green, full: !nextTaken));
        nextTaken = true;
      }
      refs.addAll(tpRefs);
    }
    for (final r in refs) {
      final y = yOf(r.price);
      if (y >= 0 && y <= plotH) {
        final x0 = r.full ? refStartX : math.max(refStartX, plotW - 30.0);
        _dashed(canvas, Offset(x0, y), Offset(plotW, y),
            Paint()..color = r.color.withOpacity(r.full ? 0.8 : 0.55)..strokeWidth = 1);
      }
    }

    final placedNotes = <Rect>[]; // note boxes already drawn (entry + exit) so two notes never sit on top of each other
    // Trade path + ENTRY markers: dashed line entry -> exit per side, and a triangle ("B IN" / "A IN" / "IN") on the entry candle.
    if (!compact && n >= 2 && ((links != null && links!.isNotEmpty) || (entries != null && entries!.isNotEmpty))) {
      final stepMs2 = s.ts[n - 1] > s.ts[n - 2] ? s.ts[n - 1] - s.ts[n - 2] : 300000;
      int idxAt(int ms) {
        if (ms > s.ts[n - 1] + stepMs2) return -1;
        for (int i = n - 1; i >= 0; i--) {
          if (s.ts[i] <= ms) return i;
        }
        return -1;
      }

      for (final l in (links ?? const <ChartTradeLink>[])) {
        final i0 = idxAt(l.fromTsMs);
        final i1 = idxAt(l.toTsMs);
        if (i0 < 0 || i1 < 0) continue;
        _dashed(canvas, Offset(xOf(i0), yOf(l.fromPrice)), Offset(xOf(i1), yOf(l.toPrice)),
            Paint()..color = l.color.withOpacity(0.75)..strokeWidth = 1.0);
      }
      var erow = 0;
      for (final en in (entries ?? const <ChartEntryMark>[])) {
        final idx = idxAt(en.tsMs);
        if (idx < 0) continue;
        final x = xOf(idx);
        if (x < -10 || x > plotW + 10) continue;
        final y = yOf(en.price).clamp(12.0, plotH - 12.0).toDouble();
        final up = en.isLong;
        final baseY = up ? y + 15 : y - 15;
        final tri = Path()
          ..moveTo(x, y)
          ..lineTo(x - 9, baseY)
          ..lineTo(x + 9, baseY)
          ..close();
        canvas.drawPath(tri, Paint()..color = en.color);
        canvas.drawPath(tri, Paint()..color = Colors.white..style = PaintingStyle.stroke..strokeWidth = 1.0);
        final lt = _text(en.label, const TextStyle(color: Colors.white, fontSize: 8.5, fontWeight: FontWeight.w900));
        lt.paint(canvas, Offset(x - lt.width / 2, (up ? y + 5.5 : y - 13.5)));
        if (en.note != null && en.note!.isNotEmpty) {
          final nt = _text(en.note!, TextStyle(color: en.color, fontSize: 10, fontWeight: FontWeight.w800));
          final nx = (x + 13 + nt.width > plotW) ? x - 13 - nt.width : x + 13;
          final ny = _freeSlot(placedNotes, nx, (up ? y + 6 : y - 18) + erow * 13.0, nt.width, nt.height, plotH);
          _noteBox(canvas, nt, nx, ny, light);
          placedNotes.add(Rect.fromLTWH(nx - 2, ny - 1, nt.width + 4, nt.height + 2));
        }
        erow++;
      }
    }

    // Exit flags (B = bot, A = AI): a small dot at the exit candle, a thin guide down to the time axis and a short note.
    // Two exits on the same candle are kept apart: the second dot slides sideways and notes never overlap.
    if (exits != null && !compact && n >= 2) {
      final stepMs = s.ts[n - 1] > s.ts[n - 2] ? s.ts[n - 1] - s.ts[n - 2] : 300000;
      final dots = <Offset>[];
      for (final m in exits!) {
        var idx = -1;
        for (int i = n - 1; i >= 0; i--) {
          if (s.ts[i] <= m.tsMs) {
            idx = i;
            break;
          }
        }
        if (idx < 0 || m.tsMs > s.ts[n - 1] + stepMs) continue;
        final x = xOf(idx);
        final y = yOf(m.price).clamp(10.0, plotH - 10.0).toDouble();
        if (x < -10 || x > plotW + 10) continue;
        canvas.drawLine(Offset(x, y), Offset(x, plotH), Paint()..color = m.color.withOpacity(0.35)..strokeWidth = 1);
        var dx = x;
        for (final o in dots) {
          if ((o.dx - dx).abs() < 14 && (o.dy - y).abs() < 14) dx = o.dx + 14;
        }
        dots.add(Offset(dx, y));
        canvas.drawCircle(Offset(dx, y), 6.5, Paint()..color = m.color);
        canvas.drawCircle(Offset(dx, y), 6.5, Paint()..color = Colors.white..style = PaintingStyle.stroke..strokeWidth = 1.0);
        final lt = _text(m.label, const TextStyle(color: Colors.white, fontSize: 8.5, fontWeight: FontWeight.w800));
        lt.paint(canvas, Offset(dx - lt.width / 2, y - lt.height / 2));
        if (m.note != null && m.note!.isNotEmpty) {
          final nt = _text(m.note!, TextStyle(color: m.color, fontSize: 10, fontWeight: FontWeight.w700));
          final nx = (dx + 11 + nt.width > plotW) ? dx - 11 - nt.width : dx + 11;
          final ny = _freeSlot(placedNotes, nx, y - nt.height / 2, nt.width, nt.height, plotH);
          _noteBox(canvas, nt, nx, ny, light);
          placedNotes.add(Rect.fromLTWH(nx - 2, ny - 1, nt.width + 4, nt.height + 2));
        }
      }
    }

    // Current price line.
    final lastClose = cAt(n - 1);
    final lastUp = cAt(n - 1) >= s.o[n - 1];
    final yLast = yOf(lastClose);
    if (!compact && yLast >= 0 && yLast <= plotH) {
      _dashed(
        canvas,
        Offset(0, yLast),
        Offset(plotW, yLast),
        Paint()
          ..color = (lastUp ? _green : _red).withOpacity(0.55)
          ..strokeWidth = 1,
      );
    }
    canvas.restore();

    // ---- outside the clip: labels, axis, crosshair, legend ----
    // SD Bands left-edge labels - small, unobtrusive, no background chip
    // (kept visually secondary to the Entry/SL/TP chips on the right).
    if (!compact) {
      for (final e in sdRefsDrawn) {
        final tp = _text(e.value, AppTypography.metadata.copyWith(color: _sdLevelColor(e.value, light).withOpacity(0.95), fontSize: 8, fontWeight: FontWeight.w600));
        tp.paint(canvas, Offset(6, e.key - tp.height / 2));
      }
    }
    // Reference-line labels. Off-screen lines are pinned to the top/bottom
    // edge with an arrow so you always know they exist and which way.
    for (final r in refs) {
      final y = yOf(r.price);
      final clamped = y.clamp(6.0, plotH - 6.0).toDouble();
      final arrow = y < 0 ? '▲ ' : (y > plotH ? '▼ ' : '');
      final refFg = (light && r.label == 'ENTRY') ? Colors.white : Colors.black;
      if (compact) {
        _chip(canvas, ' ${r.label}${_rSuffix(r.price)} ${_fmtPrice(r.price)} ', plotW - 2, clamped, r.color, refFg,
            fontSize: 9, alignRightTo: plotW - 2);
      } else {
        _chip(canvas, '$arrow${r.label}${_rSuffix(r.price)}', plotW - 4, clamped, r.color.withOpacity(0.9), refFg,
            fontSize: 9, alignRightTo: plotW - 4);
        _chip(canvas, _fmtPrice(r.price), plotW + 2, clamped, r.color, refFg, fontSize: 9);
      }
    }

    if (!compact) {
      // Price axis labels.
      for (int k = 0; k <= 4; k++) {
        final y = plotH * k / 4;
        final p = priceAt(y);
        final axisTp = _text(_fmtPrice(p), TextStyle(color: _ink.withOpacity(0.6), fontSize: 9));
        axisTp.paint(canvas, Offset(plotW + 4, (y - axisTp.height / 2).clamp(0.0, plotH - axisTp.height).toDouble()));
      }
      // Current price tag.
      _chip(canvas, _fmtPrice(lastClose), plotW + 2, yLast.clamp(6.0, plotH - 6.0).toDouble(),
          lastUp ? _green : _red, Colors.black, fontSize: 9);
      // Candle countdown - time left until the forming candle closes,
      // bang below the price tag (Binance-style). Synced to wall-clock
      // interval boundaries (nowMs % timeframeMs), not to this candle's own
      // timestamp, so it stays correct even a moment before/after a REST
      // refresh actually lands the new candle.
      if (nowMs != null && timeframeMs != null && timeframeMs! > 0) {
        final remainMs = timeframeMs! - (nowMs! % timeframeMs!);
        final totalSec = (remainMs / 1000).ceil().clamp(0, timeframeMs! ~/ 1000);
        final mm = (totalSec ~/ 60).toString().padLeft(2, '0');
        final ss = (totalSec % 60).toString().padLeft(2, '0');
        final tagY = (yLast.clamp(6.0, plotH - 6.0) + 15).clamp(6.0, plotH - 6.0).toDouble();
        _chip(canvas, '$mm:$ss', plotW + 2, tagY, light ? const Color(0xFFE8EEFF) : Colors.black.withOpacity(0.88), light ? const Color(0xFF1D4ED8) : _accent, fontSize: 9);
      }
      // Time axis.
      for (final e in timeLabels) {
        final t = _text(e.value, TextStyle(color: _ink.withOpacity(0.6), fontSize: 9));
        t.paint(canvas, Offset(e.key - t.width / 2, plotH + 4));
      }
    }

    // Crosshair (dashed lines + price/time edge chips). The OHLC/%Change
    // readout itself is drawn by the caller as a floating pill widget near
    // the touch point (see _crosshairPillWidget in
    // _CandleChartSheetContentState) - not here - so it can float and
    // animate independent of the canvas.
    int? crossIdx;
    if (!compact && cross != null) {
      final idxF = (n - 1) + rightBlank - (plotW - cross!.dx) / slotW;
      final idx = idxF.round();
      crossIdx = idx;
      final cx = xOf(idx).clamp(0.0, plotW).toDouble();
      final cy = cross!.dy.clamp(0.0, plotH).toDouble();
      final cp = Paint()
        ..color = _ink.withOpacity(0.55)
        ..strokeWidth = 1;
      _dashed(canvas, Offset(cx, 0), Offset(cx, plotH), cp);
      _dashed(canvas, Offset(0, cy), Offset(plotW, cy), cp);
      _chip(canvas, _fmtPrice(priceAt(cy)), plotW + 2, cy.clamp(6.0, plotH - 6.0).toDouble(), light ? _chartInk : Colors.white, light ? Colors.white : Colors.black,
          fontSize: 9);
      final t = s.ts[n - 1] + (idx - (n - 1)) * (n >= 2 && s.ts[n - 1] > s.ts[n - 2] ? s.ts[n - 1] - s.ts[n - 2] : 300000);
      _chip(canvas, _istFull(t), cx, plotH + 10, light ? _chartInk : Colors.white, light ? Colors.white : Colors.black, fontSize: 9, centerX: true);
    }

    // EMA legend (top-left) - current EMA30/EMA50 values, tracking the
    // crosshair position when one is active, else the latest candle.
    if (!compact && (ema30 || ema50)) {
      final idx = (crossIdx ?? (n - 1)).clamp(0, n - 1).toInt();
      final spans = <TextSpan>[];
      if (ema30) {
        spans.add(TextSpan(
          text: 'EMA30 ${_fmtPrice(s.e30[idx])}   ',
          style: TextStyle(color: _e30, fontSize: 10, fontWeight: FontWeight.w600),
        ));
      }
      if (ema50) {
        spans.add(TextSpan(
          text: 'EMA50 ${_fmtPrice(s.e50[idx])}',
          style: TextStyle(color: _e50, fontSize: 10, fontWeight: FontWeight.w600),
        ));
      }
      final tpn = TextPainter(text: TextSpan(children: spans), textDirection: TextDirection.ltr)..layout(maxWidth: plotW - 12);
      canvas.drawRRect(
        RRect.fromRectAndRadius(Rect.fromLTWH(4, 4, tpn.width + 10, tpn.height + 6), const Radius.circular(4)),
        Paint()..color = (light ? Colors.white.withOpacity(0.92) : Colors.black.withOpacity(0.45)),
      );
      tpn.paint(canvas, const Offset(9, 7));
    }
  }

  /// First y at/after [y] where a note of this size does not overlap an already drawn note box.
  double _freeSlot(List<Rect> placed, double x, double y, double w, double h, double plotH) {
    var yy = y.clamp(2.0, plotH - h - 2).toDouble();
    for (var guard = 0; guard < 12; guard++) {
      final r = Rect.fromLTWH(x - 2, yy - 1, w + 4, h + 2);
      final hit = placed.where((p) => p.overlaps(r)).toList();
      if (hit.isEmpty) break;
      yy = hit.map((p) => p.bottom).reduce((a, b) => a > b ? a : b) + 1;
      if (yy > plotH - h - 2) {
        yy = (y - (h + 3) * (guard + 1)).clamp(2.0, plotH - h - 2).toDouble();
      }
    }
    return yy;
  }

  /// A note with a soft chart-coloured backing so candles and lines do not cut through the text.
  void _noteBox(Canvas canvas, TextPainter t, double x, double y, bool light) {
    canvas.drawRRect(
      RRect.fromRectAndRadius(Rect.fromLTWH(x - 3, y - 1, t.width + 6, t.height + 2), const Radius.circular(3)),
      Paint()..color = (light ? Colors.white : Colors.black).withOpacity(0.72),
    );
    t.paint(canvas, Offset(x, y));
  }

  TextPainter _text(String text, TextStyle style) {
    return TextPainter(text: TextSpan(text: text, style: style), textDirection: TextDirection.ltr)..layout();
  }

  /// Small coloured label. [alignRightTo] right-aligns the chip's right edge
  /// at that x instead of starting at [x]; [centerX] centres it on x.
  void _chip(
    Canvas canvas,
    String text,
    double x,
    double yCenter,
    Color bg,
    Color fg, {
    double fontSize = 9,
    double? alignRightTo,
    bool centerX = false,
  }) {
    final tp = _text(text, TextStyle(color: fg, fontSize: fontSize, fontWeight: FontWeight.w700));
    final w = tp.width + 6;
    var left = x;
    if (alignRightTo != null) left = alignRightTo - w;
    if (centerX) left = x - w / 2;
    final rect = Rect.fromLTWH(left, yCenter - tp.height / 2 - 1, w, tp.height + 2);
    canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(3)), Paint()..color = bg);
    tp.paint(canvas, Offset(left + 3, yCenter - tp.height / 2));
  }

  // RISK TICKS: each Entry / SL / TP label also shows its R multiple (1R = entry to the ORIGINAL stop). Only drawn when the
  // stop still sits on the loss side of entry; once a stop has moved to entry or into profit there is no honest 1R left.
  bool? _isLongTrade() {
    if (entry == null || tp == null) return null;
    final keys = tp!.keys.where((k) => tp![k] != null).toList()..sort();
    if (keys.isEmpty) return null;
    final d = tp![keys.first]! - entry!;
    return d == 0 ? null : d > 0;
  }

  String _rSuffix(double price) {
    final long = _isLongTrade();
    if (long == null || entry == null || sl == null) return '';
    final ru = long ? entry! - sl! : sl! - entry!;
    if (ru <= entry!.abs() * 1e-6) return '';
    final r = (long ? price - entry! : entry! - price) / ru;
    if (r.abs() < 0.005) return ' 0R';
    return ' ${r > 0 ? '+' : '-'}${r.abs().toStringAsFixed(1)}R';
  }

  void _dashed(Canvas canvas, Offset start, Offset end, Paint paint) {
    const dash = 5.0;
    const gap = 4.0;
    final dist = (end - start).distance;
    if (dist <= 0) return;
    final dx = (end.dx - start.dx) / dist;
    final dy = (end.dy - start.dy) / dist;
    double d = 0;
    while (d < dist) {
      final e = math.min(d + dash, dist);
      canvas.drawLine(
        Offset(start.dx + dx * d, start.dy + dy * d),
        Offset(start.dx + dx * e, start.dy + dy * e),
        paint,
      );
      d += dash + gap;
    }
  }

  @override
  bool shouldRepaint(covariant _ChartPainter old) {
    // Repaint only when something drawn actually changed. _Series is
    // immutable and rebuilt whenever candle data changes, so an identity
    // check is safe. The countdown only shows whole seconds, so nowMs is
    // compared per second (not per frame).
    return !identical(old.s, s) ||
        old.ema30 != ema30 ||
        old.ema50 != ema50 ||
        old.entry != entry ||
        old.sl != sl ||
        '${old.tp}' != '$tp' ||
        old.entryTsMs != entryTsMs ||
        !identical(old.exits, exits) ||
        !identical(old.entries, entries) ||
        !identical(old.links, links) ||
        old.slot != slot ||
        old.visibleCount != visibleCount ||
        old.rightBlank != rightBlank ||
        old.compact != compact ||
        old.cross != cross ||
        old.priceZoom != priceZoom ||
        old.priceShiftFrac != priceShiftFrac ||
        old.sdBands != sdBands ||
        !identical(old.barTint, barTint) ||
        old.liveClose != liveClose ||
        old.timeframeMs != timeframeMs ||
        ((old.nowMs ?? 0) ~/ 1000) != ((nowMs ?? 0) ~/ 1000);
  }
}

/// Opens a bottom sheet with the full interactive candle chart for one
/// symbol - call this from anywhere a row/card shows a symbol (Market Watch,
/// Positions, Alerts). Pass entry/sl/tpLevels when calling from a position
/// so the chart also draws where entry/SL/TP actually sit.
///
/// Gestures: drag = scroll through PAST and into the empty FUTURE area,
/// pinch = zoom, long-press = crosshair with OHLC + EMA readout,
/// double-tap = reset view. Older history is loaded automatically while
/// you scroll back.
void showCandleChartSheet(
  BuildContext context,
  String symbol, {
  double? entry,
  double? sl,
  Map<int, double?>? tpLevels,
  bool? isLong,
  int? entryTsMs,
  List<ChartExitMark>? exits,
  List<ChartEntryMark>? entries,
  List<ChartTradeLink>? links,
  Widget? summary,
  String? title,
  String? initialTf,
  int? focusTsMs,
  bool dualStyle = false, // Dual Bot charts: Z candles + Z-EMA 30/50 + cloud + BUY/SELL on (normal charts keep the saved settings)
}) {
  showModalBottomSheet(
    context: context,
    // Ultra-dark obsidian sheet background - pulled from the shared
    // AppColors palette (app_theme.dart) instead of a one-off hex value, so
    // the chart sheet always matches whatever the rest of the app is using.
    backgroundColor: _chartLight(context) ? _chartWhiteBg : AppColors.obsidian,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(AppSpacing.radiusLarge + 4)),
    ),
    builder: (context) => _CandleChartSheetContent(
      symbol: symbol,
      entry: entry,
      sl: sl,
      tpLevels: tpLevels,
      isLong: isLong,
      entryTsMs: entryTsMs,
      exits: exits,
      entries: entries,
      links: links,
      summary: summary,
      title: title,
      initialTf: initialTf,
      focusTsMs: focusTsMs,
      dualStyle: dualStyle,
    ),
  );
}

class _CandleChartSheetContent extends StatefulWidget {
  final String symbol;
  final double? entry;
  final double? sl;
  final Map<int, double?>? tpLevels;
  final bool? isLong;
  final int? entryTsMs;
  final List<ChartExitMark>? exits;
  final List<ChartEntryMark>? entries;
  final List<ChartTradeLink>? links;
  final Widget? summary;
  final String? title;
  final String? initialTf;
  final int? focusTsMs;
  final bool dualStyle;

  const _CandleChartSheetContent({
    required this.symbol,
    this.entry,
    this.sl,
    this.tpLevels,
    this.isLong,
    this.entryTsMs,
    this.exits,
    this.entries,
    this.links,
    this.summary,
    this.title,
    this.initialTf,
    this.focusTsMs,
    this.dualStyle = false,
  });

  @override
  State<_CandleChartSheetContent> createState() => _CandleChartSheetContentState();
}

class _CandleChartSheetContentState extends State<_CandleChartSheetContent>
    with SingleTickerProviderStateMixin {
  static const _defaultSlot = 8.0;
  static const _defaultBlank = 6.0;
  static const _axisW = 64.0;
  static const _maxCandles = 1500;

  late AppProvider _provider;
  Timer? _refreshTimer;

  // ---- live-tick forming-candle animation --------------------------------
  // AppProvider already receives a fresh open-position `ltp` / market-mover
  // `price` roughly once a second over the existing status WebSocket (see
  // api_server.py's _status_broadcaster) - no new WS channel needed. When
  // this symbol has a live tick, the newest (still-forming) candle's close
  // is animated smoothly toward it between ticks instead of jumping, so the
  // chart updates every frame like Binance's own rather than only every
  // REST poll.
  late final AnimationController _tickAnim = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 800),
  )..addListener(() {
      if (mounted) setState(() {});
    });
  double? _tickFrom;
  double? _tickTo;

  List<dynamic> _raw = [];
  _Series? _series;
  bool _loading = true;
  bool _loadingMore = false;
  // Real backend reason the last fetch came back empty (set from
  // AppProvider.lastCandleError in _loadInitial) - shown instead of a
  // generic "Could not load candles" so a thin/invalid/delisted symbol
  // like 2U2USDTM is diagnosable from the app itself, not just guessed at.
  String? _loadError;
  bool _hasMore = true;
  int _requested = 600;

  bool _focused = false;
  double _slot = _defaultSlot;
  double _baseSlot = _defaultSlot;
  double _rightBlank = _defaultBlank;
  double _plotW = 300;
  double _plotH = 300;
  bool _ema30 = true;
  bool _ema50 = true;
  bool _sdBands = true;

  // Special Master panes (TSI on top, Z-score below) under the candles - same x-axis as the chart.
  bool _sm = true;
  SmSettings _smSet = SmSettings.defaults(); // the owner's TradingView settings, edited via the gear chip
  _Series? _smFor;
  String? _smForKey;
  SpecialMasterData? _smData;
  static const _smPaneH = 150.0;

  // ---- Y-axis (price) zoom/pan - dual-axis gesture support alongside the
  // existing X-axis (time) slot/rightBlank pair above. A two-finger pinch
  // scales both axes independently (Flutter's ScaleGestureDetector reports
  // horizontalScale/verticalScale separately - see onScaleUpdate below), and
  // dragging with the price axis visible pans price the same way dragging
  // already pans time.
  double _priceZoom = 1.0;
  double _basePriceZoom = 1.0;
  // TradingView-style gesture state: the candle under the fingers stays
  // under the fingers while pinching/panning, and dragging the right-hand
  // price axis scales price (see onScaleStart/onScaleUpdate below).
  bool _axisDrag = false;
  double _anchorIdx = 0.0;
  int _lastPointerCount = 0;
  double _priceShiftFrac = 0.0;
  Offset? _cross;
  // Last non-null crosshair point, kept around (unlike _cross, which goes
  // straight to null on release) purely so the floating readout pill has a
  // position to animate its fade-out FROM instead of snapping away - see
  // _crosshairPillWidget().
  Offset? _crossDisplay;

  // ---- candle countdown ---------------------------------------------
  // Ticks the UI once a second purely so the countdown chip drawn in
  // _ChartPainter (under the price tag) stays live - candle data itself
  // still only refreshes via _refreshTimer/_onProviderTick above.
  Timer? _countdownTimer;

  // Chart-only timeframe picked with the chips below. null = follow the
  // strategy timeframe from Settings. Picking a chip never changes the
  // bot's real scanning timeframe - it only changes what this sheet draws.
  static const List<String> _tfChoices = ['1m', '3m', '5m', '15m', '1h'];
  String? _tfOverride;
  String get _tf =>
      _tfOverride ?? ((_provider.settings['timeframe'] as String?) ?? '5m');

  void _pickTf(String tf) {
    if (tf == _tf) return;
    AppHaptics.light();
    setState(() {
      _tfOverride = tf;
      _raw = [];
      _series = null;
      _requested = 600;
      _focused = false;
      _hasMore = true;
      _rightBlank = _defaultBlank;
      _slot = _defaultSlot;
      _priceZoom = 1.0;
      _priceShiftFrac = 0.0;
      _cross = null;
      _tickFrom = null;
      _tickTo = null;
    });
    _tickAnim.stop();
    _loadInitial();
  }

  int _timeframeMinutes() {
    final tf = _tf.trim();
    final m = RegExp(r'^(\d+)\s*([mh])$', caseSensitive: false).firstMatch(tf);
    if (m == null) return 5;
    final val = int.tryParse(m.group(1)!) ?? 5;
    return (m.group(2)!.toLowerCase() == 'h') ? val * 60 : val;
  }

  int _timeframeMs() => _timeframeMinutes() * 60 * 1000;

  @override
  void initState() {
    super.initState();
    _provider = Provider.of<AppProvider>(context, listen: false);
    _provider.addListener(_onProviderTick);
    if (widget.initialTf != null && _tfChoices.contains(widget.initialTf)) _tfOverride = widget.initialTf;
    _loadSmSettings();
    _loadInitial();
    _countdownTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
    // Only the newest few candles are re-fetched and merged in - cheap, and
    // it never disturbs where the person has scrolled to. Was 20s (why the
    // chart used to trail 2-3 candles behind the real exchange) - the
    // forming candle itself now updates every tick via _onProviderTick
    // above, this interval just needs to be short enough to pick up a
    // fresh candle rollover and correct any drift promptly.
    _refreshTimer = Timer.periodic(const Duration(seconds: 5), (_) => _refreshLatest());
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    _countdownTimer?.cancel();
    _provider.removeListener(_onProviderTick);
    _tickAnim.dispose();
    super.dispose();
  }

  /// This symbol's latest live price, if it has one right now - from an
  /// open position's `ltp` first (updates every monitor-loop tick), else a
  /// Market Watch mover's `price`. Neither is a dedicated per-symbol feed
  /// (see the honest caveat below), but both already refresh ~once/sec
  /// over the existing status WebSocket whenever this symbol happens to be
  /// one of those two things - which covers the symbols someone is actually
  /// watching a live chart for.
  double? _liveTickPrice() {
    for (final p in _provider.positions) {
      if (p is Map && p['symbol'] == widget.symbol) {
        final v = (p['ltp'] as num?)?.toDouble();
        if (v != null) return v;
      }
    }
    for (final m in _provider.movers) {
      if (m is Map && m['symbol'] == widget.symbol) {
        final v = (m['price'] as num?)?.toDouble();
        if (v != null) return v;
      }
    }
    return null;
  }

  /// Called on every AppProvider.notifyListeners() - i.e. every status
  /// WebSocket "update" (~1/s). Kicks off a smooth animation of the
  /// forming candle's close toward the new tick (if this symbol has one),
  /// and refreshes the dynamic timeframe subtitle either way.
  void _onProviderTick() {
    final sr = _series;
    if (sr != null && sr.n > 0) {
      final price = _liveTickPrice();
      if (price != null) {
        final from = _displayLiveClose ?? sr.c[sr.n - 1];
        if ((price - from).abs() > 1e-12) {
          _tickFrom = from;
          _tickTo = price;
          _tickAnim
            ..stop()
            ..value = 0
            ..forward();
        }
      }
    }
    if (mounted) setState(() {});
  }

  /// Current animated forming-candle close, or null if there's no live
  /// tick for this symbol right now (falls back to the REST-fetched close
  /// in that case - see _ChartPainter.liveClose).
  double? get _displayLiveClose {
    if (_tickTo == null) return null;
    if (_tickFrom == null) return _tickTo;
    final t = Curves.easeOut.transform(_tickAnim.value);
    return _tickFrom! + (_tickTo! - _tickFrom!) * t;
  }

  void _setRaw(List<dynamic> raw) {
    _raw = raw;
    _series = raw.isEmpty ? null : _Series.from(raw);
    // A fresh REST fetch's last candle is already authoritative (real
    // exchange data, not an interpolated guess) - drop any in-flight tick
    // animation so it doesn't fight the newly-merged close, including
    // across a candle rollover (the "forming" candle just became a new
    // one; the old tick target no longer applies to it).
    _tickFrom = null;
    _tickTo = null;
    _tickAnim.stop();
    _tickAnim.value = 0;
  }

  Future<void> _loadInitial() async {
    setState(() => _loading = true);
    final askedTf = _tf;
    final data = await _provider.fetchCandles(widget.symbol, limit: _requested, tf: askedTf);
    if (!mounted || askedTf != _tf) return;
    setState(() {
      _setRaw(data);
      _hasMore = data.length >= _requested;
      _loading = false;
      _loadError = data.isEmpty ? _provider.lastCandleError : null;
      _focusOnTrade();
    });
  }

  /// Trade view: start the chart a few candles BEFORE the entry (like opening a trade in TradingView),
  /// not at the newest candle. Pan right to see how it ended; "Latest" jumps back to now.
  void _focusOnTrade() {
    final ft = widget.focusTsMs;
    final sr = _series;
    if (ft == null || sr == null || sr.n < 3 || _focused) return;
    _focused = true;
    var idx = -1;
    for (int i = sr.n - 1; i >= 0; i--) {
      if (sr.ts[i] <= ft) {
        idx = i;
        break;
      }
    }
    if (idx < 0) return;
    // put the entry candle about 1/4 from the left edge
    final visible = _plotW / _slot;
    _rightBlank = -((sr.n - 1 - idx) - visible * 0.72);
    _clampView();
  }

  Future<void> _refreshLatest() async {
    if (_raw.isEmpty) return;
    final askedTf = _tf;
    final incoming = await _provider.fetchCandles(widget.symbol, limit: 40, tf: askedTf);
    if (!mounted || incoming.isEmpty || askedTf != _tf) return;
    final firstTs = (incoming.first as Map)['timestamp'] as num;
    final merged = <dynamic>[
      ..._raw.where((c) => ((c as Map)['timestamp'] as num) < firstTs),
      ...incoming,
    ];
    final delta = merged.length - _raw.length;
    setState(() {
      _setRaw(merged);
      // If scrolled back into history, keep the same candles under the
      // finger when a new candle arrives.
      if (_rightBlank < 0 && delta != 0) _rightBlank -= delta;
    });
  }

  Future<void> _maybeLoadMore() async {
    final sr = _series;
    if (sr == null || _loadingMore || !_hasMore) return;
    final leftIdx = (sr.n - 1) + _rightBlank + 0.5 - _plotW / _slot;
    if (leftIdx > 15) return;
    if (_requested >= _maxCandles) {
      _hasMore = false;
      return;
    }
    _loadingMore = true;
    if (mounted) setState(() {});
    final want = math.min(_maxCandles, _raw.length + 300);
    final data = await _provider.fetchCandles(widget.symbol, limit: want, tf: _tf);
    if (!mounted) return;
    setState(() {
      if (data.length > _raw.length) {
        _requested = want;
        _setRaw(data); // right-anchored layout: older candles just appear on the left
      } else {
        _hasMore = false;
      }
      _loadingMore = false;
    });
  }

  void _clampView() {
    final n = _series?.n ?? 0;
    final minBlank = -(n - 3).toDouble();
    final maxBlank = math.max(2.0, _plotW / _slot - 3);
    _rightBlank = _rightBlank.clamp(minBlank, maxBlank).toDouble();
  }

  void _resetView() {
    AppHaptics.light();
    setState(() {
      _slot = _defaultSlot;
      _rightBlank = _defaultBlank;
      _priceZoom = 1.0;
      _priceShiftFrac = 0.0;
      _cross = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final navInset = MediaQuery.of(context).viewPadding.bottom; // Android nav bar / gesture area
    final h = MediaQuery.of(context).size.height * 0.92 + navInset;
    final away = _rightBlank < 0 ||
        _rightBlank > _defaultBlank + 1 ||
        (_priceZoom - 1.0).abs() > 0.05 ||
        _priceShiftFrac.abs() > 0.02;
    return SizedBox(
      height: h,
      child: Padding(
        padding: EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.l - 2, AppSpacing.m, AppSpacing.m + navInset),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    widget.title ?? widget.symbol,
                    style: TextStyle(color: _chartLight(context) ? _chartInk : Colors.white, fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                ),
                if (away)
                  TextButton.icon(
                    onPressed: _resetView,
                    icon: const Icon(Icons.last_page, size: 16, color: _accent),
                    label: const Text('Latest', style: TextStyle(color: _accent, fontSize: 12)),
                  ),
                IconButton(
                  icon: const Icon(Icons.close, color: Colors.grey),
                  onPressed: () => Navigator.pop(context),
                ),
              ],
            ),
            if (widget.summary != null) ...[widget.summary!, const SizedBox(height: 6)],
            SizedBox(
              height: 34,
              child: ListView(
                scrollDirection: Axis.horizontal,
                children: [
                  for (final tf in _tfChoices) _tfChip(tf, tf == _tf),
                ],
              ),
            ),
            const SizedBox(height: 6),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
              children: [
                _emaChip('EMA 30', _chartLight(context) ? _ema30Light : _ema30Color, _ema30, (v) => setState(() => _ema30 = v)),
                const SizedBox(width: 8),
                _emaChip('EMA 50', _chartLight(context) ? _ema50Light : _ema50Color, _ema50, (v) => setState(() => _ema50 = v)),
                const SizedBox(width: 8),
                _emaChip('SD Bands', _sdColor, _sdBands, (v) => setState(() => _sdBands = v)),
                const SizedBox(width: 8),
                _emaChip('Special Master', const Color(0xFFB388FF), _sm, (v) => setState(() => _sm = v)),
                if (_sm) ...[
                  const SizedBox(width: 8),
                  _emaChip('TSI ${_smSet.speed.name}', const Color(0xFF80CBC4), true, (_) {
                    setState(() => _smSet = _smSet.set('fast', !_smSet.fast));
                    _saveSmSettings();
                  }),
                  const SizedBox(width: 8),
                  ActionChip(
                    avatar: const Icon(Icons.tune, size: 16),
                    label: const Text('SM settings'),
                    onPressed: _openSmSettings,
                  ),
                ],
              ],
            ),
            ),
            const SizedBox(height: 3),
            Text(
              '$_tf  ·  drag pan  ·  pinch zoom  ·  hold crosshair  ·  double-tap reset',
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(color: Colors.grey, fontSize: 10),
            ),
            const SizedBox(height: 4),
            Expanded(child: _chartArea()),
            if (_sm && !_loading && _series != null && _series!.n > 60) _smPanes(),
          ],
        ),
      ),
    );
  }

  Future<void> _loadSmSettings() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      var loaded = SmSettings.fromJson(prefs.getString(SmSettings.prefsKey));
      if (widget.dualStyle) loaded = loaded.set('zStyle', 'Candles').set('zEma', true).set('zSig', true).set('zOn', true);
      if (mounted) setState(() => _smSet = loaded);
    } catch (_) {/* defaults stay */}
  }

  Future<void> _saveSmSettings() async {
    if (widget.dualStyle) return; // the Dual Bot look is temporary, it must not change the normal charts
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(SmSettings.prefsKey, _smSet.toJson());
    } catch (_) {}
  }

  Future<void> _openSmSettings() async {
    final res = await showSmSettingsSheet(context, _smSet);
    if (res != null && mounted) {
      setState(() => _smSet = res);
      _saveSmSettings();
    }
  }

  /// (Re)compute the indicator numbers only when the candles or a number-changing setting changed.
  SpecialMasterData? _ensureSm(_Series sr) {
    if (!_sm || sr.n < 60) return null;
    final key = _smSet.computeKey;
    if (!identical(_smFor, sr) || _smForKey != key || _smData == null) {
      _smData = SpecialMasterData.compute(sr.c, st: _smSet, o: sr.o, h: sr.h, l: sr.l);
      _smFor = sr;
      _smForKey = key;
    }
    return _smData;
  }

  /// TSI + Z-score panes (Special Master). Shares _slot / _rightBlank / _plotW with the candle chart so
  /// candles and both indicators line up; a horizontal drag here pans the same view.
  Widget _smPanes() {
    final sr = _series!;
    final data = _ensureSm(sr);
    if (data == null || (!_smSet.tsiOn && !_smSet.zOn)) return const SizedBox.shrink();
    int? mark;
    final pos = _cross;
    if (pos != null && sr.n > 0) {
      mark = ((sr.n - 1) + _rightBlank - (_plotW - pos.dx) / _slot).round().clamp(0, sr.n - 1).toInt();
    }
    return Padding(
      padding: const EdgeInsets.only(top: 4),
      child: SizedBox(
        height: _smPaneH,
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onHorizontalDragUpdate: (d) {
            setState(() {
              _rightBlank -= d.delta.dx / _slot;
              _clampView();
            });
            _maybeLoadMore();
          },
          onDoubleTap: _resetView,
          child: ClipRect(
            child: Stack(
              children: [
                CustomPaint(
                  size: Size.infinite,
                  painter: SpecialMasterPainter(
                    data,
                    st: _smSet,
                    slot: _slot,
                    rightBlank: _rightBlank,
                    plotW: _plotW,
                    light: _chartLight(context),
                    markIdx: mark,
                  ),
                ),
                if (!_smSet.b('zSma') || !_smSet.b('sma2'))
                  Positioned(
                    left: 8,
                    top: 8,
                    child: Text(
                      'Z-SMA line is off. Turn it on in the chart settings.',
                      style: TextStyle(fontSize: 11, color: Colors.grey.shade600),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _tfChip(String tf, bool selected) {
    return Padding(
      padding: const EdgeInsets.only(right: 6),
      child: GestureDetector(
        onTap: () => _pickTf(tf),
        child: AnimatedContainer(
          duration: AppMotion.base,
          alignment: Alignment.center,
          padding: const EdgeInsets.symmetric(horizontal: 14),
          decoration: BoxDecoration(
            color: selected ? _accent.withOpacity(0.18) : _chartLight(context) ? Colors.white : Colors.white.withOpacity(0.05),
            borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
            border: Border.all(color: selected ? _accent : (_chartLight(context) ? const Color(0xFFD5DAE3) : Colors.white12)),
          ),
          child: Text(
            tf,
            style: TextStyle(
              color: selected ? _accent : Colors.grey,
              fontSize: 12.5,
              fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
            ),
          ),
        ),
      ),
    );
  }

  Widget _emaChip(String label, Color color, bool selected, ValueChanged<bool> onChanged) {
    return FilterChip(
      label: Text(label),
      selected: selected,
      onSelected: onChanged,
      showCheckmark: false,
      backgroundColor: _chartLight(context) ? Colors.white : Colors.white.withOpacity(0.05),
      selectedColor: color.withOpacity(0.22),
      side: BorderSide(color: selected ? color : (_chartLight(context) ? const Color(0xFFD5DAE3) : Colors.white12)),
      labelStyle: TextStyle(color: selected ? color : Colors.grey, fontSize: 12, fontWeight: FontWeight.w600),
      visualDensity: VisualDensity.compact,
      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
    );
  }

  Widget _chartArea() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator(color: _accent));
    }
    final sr = _series;
    if (sr == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('Could not load candles', style: TextStyle(color: _red, fontSize: 13)),
              if (_loadError != null) ...[
                const SizedBox(height: 6),
                Text(
                  _loadError!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.grey, fontSize: 11),
                ),
              ],
              const SizedBox(height: 8),
              OutlinedButton(onPressed: _loadInitial, child: const Text('Retry')),
            ],
          ),
        ),
      );
    }
    return LayoutBuilder(
      builder: (context, cons) {
        _plotW = math.max(50.0, cons.maxWidth - _axisW);
        _plotH = math.max(50.0, cons.maxHeight - 20.0);
        final pillWidget = _crosshairPillWidget();
        return Stack(
          children: [
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onScaleStart: (d) {
                _baseSlot = _slot;
                _basePriceZoom = _priceZoom;
                _lastPointerCount = d.pointerCount;
                // Touch started on the right price-axis strip -> price scale drag.
                _axisDrag = d.localFocalPoint.dx > _plotW;
                final n0 = _series?.n ?? 0;
                _anchorIdx = (n0 - 1) + _rightBlank + 0.5 - (_plotW - d.localFocalPoint.dx) / _slot;
                if (_cross != null) setState(() => _cross = null);
              },
              onScaleUpdate: (d) {
                setState(() {
                  if (_axisDrag) {
                    // Right price scale (TradingView): drag up = zoom in,
                    // drag down = zoom out. Exponential so it feels even
                    // at every zoom level.
                    _priceZoom = (_priceZoom * math.exp(-d.focalPointDelta.dy * 0.006)).clamp(0.15, 8.0).toDouble();
                    return;
                  }
                  final n = _series?.n ?? 0;
                  // A finger was added/removed: Flutter restarts `scale` at 1.0,
                  // so re-base instead of jumping.
                  if (d.pointerCount != _lastPointerCount) {
                    _lastPointerCount = d.pointerCount;
                    _baseSlot = _slot;
                    _anchorIdx = (n - 1) + _rightBlank + 0.5 - (_plotW - d.localFocalPoint.dx) / _slot;
                  }
                  if (d.pointerCount >= 2) {
                    // Time zoom from the OVERALL pinch ratio (stable). The old
                    // per-axis horizontalScale blew up whenever the two
                    // fingers were nearly vertical - that was the "zooms
                    // very fast" jump. Slightly damped so it tracks the
                    // fingers 1:1 like TradingView.
                    final damped = math.pow(d.scale, 0.85).toDouble();
                    _slot = (_baseSlot * damped).clamp(3.0, 36.0).toDouble();
                  }
                  // Keep the candle that was under the fingers under the
                  // fingers: pan + zoom in one rule (anchor-based).
                  _rightBlank = _anchorIdx - (n - 1) - 0.5 + (_plotW - d.localFocalPoint.dx) / _slot;
                  // Vertical drag pans price. Divided by zoom because the
                  // visible span shrinks by that factor - otherwise a zoomed
                  // chart scrolls zoom-times faster than the finger.
                  if (_plotH > 0) {
                    _priceShiftFrac += d.focalPointDelta.dy / _plotH / _priceZoom;
                  }
                  _priceShiftFrac = _priceShiftFrac.clamp(-4.0, 4.0).toDouble();
                  _clampView();
                });
                _maybeLoadMore();
              },
              onDoubleTap: _resetView,
              // Touch + hold = crosshair on; drag while held = crosshair
              // follows the finger (onLongPressMoveUpdate below); lift off
              // = smoothly fades out (see _crosshairPillWidget - _cross
              // goes null here but _crossDisplay is kept for the fade).
              onLongPressStart: (d) => setState(() {
                _cross = d.localPosition;
                _crossDisplay = d.localPosition;
              }),
              onLongPressMoveUpdate: (d) => setState(() {
                _cross = d.localPosition;
                _crossDisplay = d.localPosition;
              }),
              onLongPressEnd: (_) => setState(() => _cross = null),
              child: ClipRect(
                child: CustomPaint(
                  size: Size(cons.maxWidth, cons.maxHeight),
                  painter: _ChartPainter(
                    sr,
                    ema30: _ema30,
                    ema50: _ema50,
                    entry: widget.entry,
                    sl: widget.sl,
                    tp: widget.tpLevels,
                    entryTsMs: widget.entryTsMs,
                    exits: widget.exits,
                    entries: widget.entries,
                    links: widget.links,
                    slot: _slot,
                    rightBlank: _rightBlank,
                    compact: false,
                    cross: _cross,
                    liveClose: _displayLiveClose,
                    nowMs: DateTime.now().millisecondsSinceEpoch,
                    timeframeMs: _timeframeMs(),
                    priceZoom: _priceZoom,
                    priceShiftFrac: _priceShiftFrac,
                    sdBands: _sdBands,
                    barTint: (_sm && _smSet.tsiOn && _smSet.b('curlBars')) ? _ensureSm(sr)?.barTint : null,
                    light: _chartLight(context),
                  ),
                ),
              ),
            ),
            if (_loadingMore)
              Positioned(
                left: 8,
                bottom: 24,
                child: Text('loading older candles…', style: TextStyle(color: _chartLight(context) ? Colors.black54 : Colors.white54, fontSize: 10)),
              ),
            if (pillWidget != null) pillWidget,
          ],
        );
      },
    );
  }

  /// Floating touch-point tooltip: Time/Open/High/Low/Close/%Change for
  /// whichever candle is under the crosshair. Positioned near the finger
  /// (above it, flipping below if too close to the top) and fades/scales
  /// smoothly in on touch and out on release via AnimatedOpacity/
  /// AnimatedScale keyed off _cross (null on release) while _crossDisplay
  /// keeps the last real position so the fade has somewhere to animate
  /// from instead of snapping.
  Widget? _crosshairPillWidget() {
    final lightPill = _chartLight(context);
    final pillInk = lightPill ? _chartInk : Colors.white;
    final sr = _series;
    final pos = _crossDisplay;
    if (sr == null || pos == null || sr.n == 0) return null;
    final n = sr.n;
    final idxF = (n - 1) + _rightBlank - (_plotW - pos.dx) / _slot;
    final idx = idxF.round();
    final inData = idx >= 0 && idx <= n - 1;
    final lastTs = sr.ts[n - 1];
    final step = (n >= 2 && lastTs > sr.ts[n - 2]) ? lastTs - sr.ts[n - 2] : _timeframeMs();
    final t = lastTs + (idx - (n - 1)) * step;

    Widget body;
    double approxH;
    if (inData) {
      final hasLive = _displayLiveClose != null && idx == n - 1;
      final o = sr.o[idx];
      final h = hasLive ? math.max(sr.h[idx], _displayLiveClose!) : sr.h[idx];
      final l = hasLive ? math.min(sr.l[idx], _displayLiveClose!) : sr.l[idx];
      final c = hasLive ? _displayLiveClose! : sr.c[idx];
      final chg = o == 0 ? 0.0 : (c - o) / o * 100;
      final chgColor = chg >= 0 ? _green : _red;
      body = Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(_istFull(t), style: TextStyle(color: pillInk.withOpacity(0.7), fontSize: 10, fontWeight: FontWeight.w600)),
          const SizedBox(height: 3),
          Text('O ${_fmtPrice(o)}   H ${_fmtPrice(h)}', style: TextStyle(color: pillInk, fontSize: 11)),
          Text('L ${_fmtPrice(l)}   C ${_fmtPrice(c)}', style: TextStyle(color: pillInk, fontSize: 11)),
          const SizedBox(height: 3),
          Text('${chg >= 0 ? '+' : ''}${chg.toStringAsFixed(2)}%',
              style: AppTypography.secondaryData.copyWith(color: chgColor, fontSize: 12, fontWeight: FontWeight.w700)),
        ],
      );
      approxH = 94;
    } else {
      body = Text('Future - no data yet', style: TextStyle(color: pillInk.withOpacity(0.55), fontSize: 11));
      approxH = 32;
    }

    const pillW = 172.0;
    final left = (pos.dx - pillW / 2).clamp(4.0, math.max(4.0, _plotW - pillW - 4)).toDouble();
    double top = pos.dy - approxH - 22; // float above the finger
    if (top < 4) top = math.min(pos.dy + 22, math.max(4.0, _plotH - approxH - 4)); // too close to top -> flip below

    return Positioned(
      left: left,
      top: top,
      child: IgnorePointer(
        child: AnimatedOpacity(
          opacity: _cross != null ? 1.0 : 0.0,
          duration: AppMotion.base,
          curve: AppMotion.standard,
          child: AnimatedScale(
            scale: _cross != null ? 1.0 : 0.92,
            duration: AppMotion.base,
            curve: AppMotion.standard,
            child: Container(
              width: pillW,
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m - 2, vertical: AppSpacing.s),
              decoration: BoxDecoration(
                color: (lightPill ? Colors.white : AppColors.surfaceDark).withOpacity(0.96),
                borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                border: Border.all(color: _accent.withOpacity(0.35)),
                boxShadow: [BoxShadow(color: Colors.black.withOpacity(lightPill ? 0.18 : 0.35), blurRadius: 8, offset: const Offset(0, 3))],
              ),
              child: body,
            ),
          ),
        ),
      ),
    );
  }
}
