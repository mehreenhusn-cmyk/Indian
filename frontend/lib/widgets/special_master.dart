import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';

/// "Special Master new" (the TradingView Pine script) as two sub-panes under the candle chart:
///   top    = TSI momentum: value line, signal line (4-zone colour), histogram ("Bj candle" = TSI - signal),
///            Ob / Os lines, zero line, Ob/Os cross tint and the TREND-REVERSAL WARNING arrows
///   bottom = Z-score (how many SD the close is away from its 200-candle average) with the 1/2/3 SD
///            probability bands, Z-SMA 1 / 2 and the UCL / LCL band
/// The maths is the SAME as the Pine script and as the backend (ai_ind_features.py). Z is shown in sigma
/// units (the Pine plot is Z x 10: +10 = 1 sigma). Every tick / value in the TradingView "Inputs" and
/// "Style" tabs has a matching switch in SmSettings (edited from special_master_settings.dart), and the
/// defaults below are the owner's own TradingView settings. Display only - nothing here touches any trade.

// ------------------------------------------------------------------ settings
class SmSpeed {
  final String name;
  final int shortLen;
  final int longLen;
  final int signalLen;
  const SmSpeed(this.name, this.shortLen, this.longLen, this.signalLen);

  /// Script input "Slow" - the speed the backend / AI uses.
  static const slow = SmSpeed('Slow', 13, 25, 13);

  /// Script input "Fast" (the Pine default).
  static const fast = SmSpeed('Fast', 5, 25, 14);
}

/// All Special Master switches in one small map-backed object (immutable: `set` returns a copy).
class SmSettings {
  static const prefsKey = 'special_master_settings_v1';

  // The owner's TradingView settings (screenshots of "Special Master new").
  static const Map<String, dynamic> _defaults = {
    // master
    'tsiOn': true, 'zOn': true, 'fast': false,
    // Ob / Os
    'ob': 30.0, 'os': -30.0, 'obLines': true, 'obCross': true, 'zeroLine': true, 'curlBars': true,
    // TSI drawing (Style tab)
    'bjBars': true, 'tsiValue': true, 'tsiSignal': true, 'sig4': true, 'tsiFill': true,
    'labels': false, 'labelEvery': 1.0,
    'arrows': false, 'arrowZ': 1.0,
    // TSI colours (value line: curl up / mid / curl down)
    'cTsiBull': 0xFF808080, 'cTsiMid': 0xFF808080, 'cTsiBear': 0xFF808080,
    // Z-score
    'zLen': 200.0, 'zStyle': 'Area', 'zTransp': 55.0,
    'cZBull': 0xFF4CAF50, 'cZBear': 0xFFFF5252,
    'zBase': true, 'probBands': true, 'probTransp': 75.0,
    'zSma': true, 'sma1': false, 'sma2': true, 'sma1Len': 100.0, 'sma2Len': 200.0,
    'cSma1': 0xFF2962FF, 'cSma2': 0xFF000000,
    'uclLcl': false, 'cUcl': 0xFF4CAF50, 'cLcl': 0xFFFF5252,
    // Special Master v6: Z-score EMA 30/50 + cloud, and the BUY / SELL cross signal (black candle + coloured border)
    'zEma': false, 'zEmaMode': 'EMA + Cloud', 'zEmaFast': 30.0, 'zEmaSlow': 50.0,
    'cEmaFast': 0xFF4CAF50, 'cEmaSlow': 0xFFF23645, 'emaWidth': 1.0,
    'cEmaBull': 0xFF4CAF50, 'cEmaBear': 0xFFFF5252, 'emaCloudTransp': 70.0,
    'zSig': false, 'zSigLbl': true, 'zSigRule': 'Candle Close crosses Slow EMA',
    'cZBuy': 0xFF4CAF50, 'cZSell': 0xFFFF5252,
    // Visibility tab: timeframes where Special Master is hidden (comma list like "1m,3m"), empty = show on all
    'hidTf': '',
  };

  final Map<String, dynamic> _m;
  const SmSettings._(this._m);

  factory SmSettings.defaults() => SmSettings._(Map<String, dynamic>.from(_defaults));

  /// Saved JSON merged over the defaults; any bad / unknown value falls back to the default.
  factory SmSettings.fromJson(String? raw) {
    final m = Map<String, dynamic>.from(_defaults);
    if (raw != null && raw.isNotEmpty) {
      try {
        final j = jsonDecode(raw);
        if (j is Map) {
          for (final k in _defaults.keys) {
            final v = j[k];
            final d = _defaults[k];
            if (v == null) continue;
            if (d is bool && v is bool) m[k] = v;
            if (d is double && v is num) m[k] = v.toDouble();
            if (d is int && v is num) m[k] = v.toInt();
            if (d is String && v is String) m[k] = v;
          }
        }
      } catch (_) {}
    }
    return SmSettings._(m);
  }

  String toJson() => jsonEncode(_m);

  SmSettings set(String k, dynamic v) => SmSettings._({..._m, k: v});

  bool b(String k) => _m[k] == true;
  double n(String k) => (_m[k] as num).toDouble();
  int i(String k) => (_m[k] as num).round();
  String s(String k) => _m[k] as String;
  Color c(String k) => Color((_m[k] as num).toInt());

  Set<String> get hiddenTfs => s('hidTf').split(',').where((x) => x.isNotEmpty).toSet();
  bool visibleOn(String tf) => !hiddenTfs.contains(tf);

  bool get tsiOn => b('tsiOn');
  bool get zOn => b('zOn');
  bool get fast => b('fast');
  SmSpeed get speed => fast ? SmSpeed.fast : SmSpeed.slow;

  /// Anything that changes the NUMBERS (not just the drawing) - data is recomputed only when this changes.
  String get computeKey =>
      '${fast}|${n('ob')}|${n('os')}|${n('arrowZ')}|${i('zLen')}|${i('sma1Len')}|${i('sma2Len')}|${s('zStyle') == 'Candles'}|${i('zEmaFast')}|${i('zEmaSlow')}|${s('zSigRule')}';
}

// ------------------------------------------------------------------ data
class SpecialMasterData {
  final List<double?> z; // sigma units
  final List<double?> zO; // Z-candle open / high / low (only filled when the Z style is "Candles")
  final List<double?> zH;
  final List<double?> zL;
  final List<double?> zSma1;
  final List<double?> zSma2;
  final List<double?> ucl;
  final List<double?> lcl;
  final List<double?> tsi;
  final List<double?> tsl;
  final List<double?> diff;

  /// +1 = "uptrend warning" (histogram weakening below zero + Z pulling back up from under -threshold),
  /// -1 = "downtrend warning" (mirror), 0 = none.
  final List<int> warn;

  /// Main-chart bar tint from "Ob/Os Curl Color": 1 = overbought curl (red bar), 2 = oversold curl (green bar).
  final List<int> barTint;

  /// "Show Ob/Os Cross" background tint: +1 = TSI crossed up at/below Os, -1 = crossed down at/above Ob.
  final List<int> cross;

  /// Z close EMA fast / slow (Special Master v6: 30 / 50), sigma units.
  final List<double?> zEmaF;
  final List<double?> zEmaS;

  /// Z cross signal per candle: +1 = BUY (black candle, green border), -1 = SELL (black candle, red border), 0 = none.
  final List<int> zSig;

  SpecialMasterData(this.z, this.zO, this.zH, this.zL, this.zSma1, this.zSma2, this.ucl, this.lcl, this.tsi, this.tsl,
      this.diff, this.warn, this.barTint, this.cross,
      {this.zEmaF = const <double?>[], this.zEmaS = const <double?>[], this.zSig = const <int>[]});

  int get n => z.length;

  /// Pine ta.ema: SMA-seeded (the first value is the average of the first `n` valid values, then alpha = 2/(n+1)),
  /// the same as india_indicators.ema in the backend (Part 21: it used to start from the first value). A null value
  /// after the seed is skipped and keeps the last value, as before; before the seed the result is null (Pine: na).
  static List<double?> _ema(List<double?> v, int n) {
    final out = List<double?>.filled(v.length, null);
    final k = 2.0 / (n + 1);
    double? prev;
    var cnt = 0;
    var sum = 0.0;
    for (var i = 0; i < v.length; i++) {
      final x = v[i];
      if (x == null) continue;
      if (prev == null) {
        sum += x;
        cnt++;
        if (cnt >= n) {
          prev = sum / n;
          out[i] = prev;
        }
      } else {
        prev = x * k + prev * (1.0 - k);
        out[i] = prev;
      }
    }
    return out;
  }

  static int _firstValid(List<double?> v) {
    for (var i = 0; i < v.length; i++) {
      if (v[i] != null) return i;
    }
    return v.length;
  }

  /// Rolling mean / population stdev (like Pine ta.sma / ta.stdev) over `len` values.
  static List<List<double?>> _roll(List<double?> v, int len) {
    final mean = List<double?>.filled(v.length, null);
    final sd = List<double?>.filled(v.length, null);
    final fv = _firstValid(v);
    for (var i = fv + len - 1; i < v.length; i++) {
      var s = 0.0;
      var ok = true;
      for (var j = i - len + 1; j <= i; j++) {
        final x = v[j];
        if (x == null) {
          ok = false;
          break;
        }
        s += x;
      }
      if (!ok) continue;
      final m = s / len;
      var q = 0.0;
      for (var j = i - len + 1; j <= i; j++) {
        final d = v[j]! - m;
        q += d * d;
      }
      mean[i] = m;
      sd[i] = math.sqrt(q / len);
    }
    return [mean, sd];
  }

  /// (value - rolling mean) / rolling stdev of `v` itself (Pine: (open - sma(open)) / stdev(open)).
  static List<double?> _zOf(List<double> v, int len) {
    final r = _roll(List<double?>.generate(v.length, (i) => v[i]), len);
    return List<double?>.generate(v.length, (i) {
      final m = r[0][i];
      final s = r[1][i];
      return (m != null && s != null && s > 0) ? (v[i] - m) / s : null;
    });
  }

  static SpecialMasterData compute(List<double> c,
      {SmSettings? st, List<double>? o, List<double>? h, List<double>? l}) {
    final cfg = st ?? SmSettings.defaults();
    final speed = cfg.speed;
    final zLen = math.max(5, cfg.i('zLen'));
    final len1 = math.max(2, cfg.i('sma1Len'));
    final len2 = math.max(2, cfg.i('sma2Len'));
    final n = c.length;
    // --- Z-score
    final z = _zOf(c, zLen);
    List<double?> zO = const [], zH = const [], zL = const [];
    if (cfg.s('zStyle') == 'Candles' && o != null && h != null && l != null && o.length == n && h.length == n && l.length == n) {
      zO = _zOf(o, zLen);
      zH = _zOf(h, zLen);
      zL = _zOf(l, zLen);
    } else {
      zO = List<double?>.filled(n, null);
      zH = List<double?>.filled(n, null);
      zL = List<double?>.filled(n, null);
    }
    // Z-SMAs / UCL / LCL work on Z x 10 in the script; divided by 10 here = sigma units
    final z10 = List<double?>.generate(n, (i) => z[i] == null ? null : z[i]! * 10.0);
    final s1 = _roll(z10, len1);
    final s2 = _roll(z10, len2);
    final sdS = _roll(s1[0], len1);
    final zSma1 = List<double?>.generate(n, (i) => s1[0][i] == null ? null : s1[0][i]! / 10.0);
    final zSma2 = List<double?>.generate(n, (i) => s2[0][i] == null ? null : s2[0][i]! / 10.0);
    final ucl = List<double?>.generate(
        n, (i) => (s1[0][i] == null || sdS[1][i] == null) ? null : (s1[0][i]! + sdS[1][i]!) / 10.0);
    final lcl = List<double?>.generate(
        n, (i) => (s1[0][i] == null || sdS[1][i] == null) ? null : (s1[0][i]! - sdS[1][i]!) / 10.0);
    // --- TSI (Pine ta.tsi: long smoothing first, then short)
    final pc = List<double?>.filled(n, null);
    final apc = List<double?>.filled(n, null);
    for (var i = 1; i < n; i++) {
      pc[i] = c[i] - c[i - 1];
      apc[i] = (c[i] - c[i - 1]).abs();
    }
    final numer = _ema(_ema(pc, speed.longLen), speed.shortLen);
    final den = _ema(_ema(apc, speed.longLen), speed.shortLen);
    final tsi = List<double?>.filled(n, null);
    for (var i = 0; i < n; i++) {
      final a = numer[i];
      final b = den[i];
      if (a != null && b != null && b != 0) tsi[i] = 100.0 * a / b;
    }
    final tsl = _ema(tsi, speed.signalLen);
    final diff = List<double?>.generate(n, (i) => (tsi[i] == null || tsl[i] == null) ? null : tsi[i]! - tsl[i]!);
    // --- reversal warning arrows (script section 2C)
    final thr = cfg.n('arrowZ');
    final warn = List<int>.filled(n, 0);
    for (var i = 2; i < n; i++) {
      final d0 = diff[i];
      final d1 = diff[i - 1];
      final d2 = diff[i - 2];
      final z0 = z[i];
      final z1 = z[i - 1];
      if (d0 == null || d1 == null || d2 == null || z0 == null || z1 == null) continue;
      final weakBull = d0 > 0 && d0 < d1 && d1 >= d2;
      final weakBear = d0 < 0 && d0 > d1 && d1 <= d2;
      if (weakBull && z0 < z1 && z1 > thr) warn[i] = -1;
      if (weakBear && z0 > z1 && z1 < -thr) warn[i] = 1;
    }
    // --- Ob / Os curl (main-chart bar colour) and Ob / Os cross (background tint)
    final ob = cfg.n('ob');
    final os = cfg.n('os');
    final barTint = List<int>.filled(n, 0);
    final cross = List<int>.filled(n, 0);
    for (var i = 1; i < n; i++) {
      final t0 = tsi[i], t1 = tsi[i - 1], s0 = tsl[i], s1v = tsl[i - 1];
      if (t0 == null || t1 == null || s0 == null || s1v == null) continue;
      if (t0 > ob && t0 < t1 && t1 > s1v) barTint[i] = 1; // overBought
      if (t0 < os && t0 > t1 && t1 < s1v) barTint[i] = 2; // overSold
      final crossUp = t0 > s0 && t1 <= s1v;
      final crossDn = t0 < s0 && t1 >= s1v;
      if (crossUp && t0 <= os) cross[i] = 1;
      if (crossDn && t0 >= ob) cross[i] = -1;
    }
    // --- Z-score EMA fast / slow and the cross signal (Special Master v6, section 3B / 3C)
    final zEmaF = _ema(z, math.max(1, cfg.i('zEmaFast')));
    final zEmaS = _ema(z, math.max(1, cfg.i('zEmaSlow')));
    final rule = cfg.s('zSigRule');
    final a = rule == 'Fast EMA crosses Slow EMA' ? zEmaF : z;
    final b = rule == 'Candle Close crosses Fast EMA' ? zEmaF : zEmaS;
    final zSig = List<int>.filled(n, 0);
    for (var i = 1; i < n; i++) {
      final a0 = a[i], a1 = a[i - 1], b0 = b[i], b1 = b[i - 1];
      if (a0 == null || a1 == null || b0 == null || b1 == null) continue;
      if (a0 > b0 && a1 <= b1) zSig[i] = 1; // ta.crossover
      if (a0 < b0 && a1 >= b1) zSig[i] = -1; // ta.crossunder
    }
    return SpecialMasterData(z, zO, zH, zL, zSma1, zSma2, ucl, lcl, tsi, tsl, diff, warn, barTint, cross,
        zEmaF: zEmaF, zEmaS: zEmaS, zSig: zSig);
  }
}

// ------------------------------------------------------------------ painter
/// Two stacked panes (TSI on top, Z-score below; a single pane if only one engine is on), drawn with the
/// SAME horizontal mapping as the main candle chart: candle i sits at x(i) = plotW - (rightBlank + (n-1-i) + 0.5) * slot.
class SpecialMasterPainter extends CustomPainter {
  final SpecialMasterData d;
  final SmSettings st;
  final double slot;
  final double rightBlank;
  final double plotW;
  final bool light;
  final int? markIdx; // candle under the crosshair, null = newest candle
  /// When true the Z-SMA 2 series is the underlying index overlay (option chart).
  final bool indexZsma;

  /// Per-pane price-axis scale (1 = auto-fit, >1 = zoomed in). Dragging the right axis of a pane changes only that pane.
  final double tsiScale;
  final double zScale;
  /// Per-pane up/down scroll (fraction of the pane's value range; + moves the window up so the line moves down).
  final double tsiShift;
  final double zShift;

  /// Crosshair: [crossX] draws a vertical line through every pane; [crossY] (this pane's own y) adds a horizontal
  /// line + value chip in the pane it falls in; [crossLabel] is the time chip under the last pane.
  final double? crossX;
  final double? crossY;
  final String? crossLabel;

  double _tsiLo = -1, _tsiHi = 1, _zLo = -1, _zHi = 1; // last painted value ranges (used by the crosshair)
  Rect _tsiR = Rect.zero, _zR = Rect.zero;

  SpecialMasterPainter(this.d,
      {required this.st,
      required this.slot,
      required this.rightBlank,
      required this.plotW,
      required this.light,
      this.markIdx,
      this.indexZsma = false,
      this.tsiScale = 1.0,
      this.zScale = 1.0,
      this.tsiShift = 0.0,
      this.zShift = 0.0,
      this.crossX,
      this.crossY,
      this.crossLabel});

  Color get _ink => light ? const Color(0xFF10141C) : Colors.white;
  Color get _grid => (light ? Colors.black : Colors.white).withOpacity(0.10);

  /// Pine transparency (0 = solid, 100 = invisible) -> opacity.
  double _op(double transp) => ((100.0 - transp) / 100.0).clamp(0.0, 1.0).toDouble();

  /// A black line is invisible on a dark canvas - show it white there.
  Color _vis(Color c) => (!light && (c.value & 0x00FFFFFF) == 0) ? Colors.white : c;

  double _x(int i) => plotW - (rightBlank + (d.n - 1 - i) + 0.5) * slot;

  @override
  void paint(Canvas canvas, Size size) {
    if (!st.tsiOn && !st.zOn) return;
    final both = st.tsiOn && st.zOn;
    final h = both ? size.height / 2 : size.height;
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, size.width, size.height));
    _paintCrossTint(canvas, size);
    if (st.tsiOn) _paintTsi(canvas, _tsiR = Rect.fromLTWH(0, 0, size.width, h));
    if (st.zOn) _paintZ(canvas, _zR = Rect.fromLTWH(0, both ? h : 0, size.width, h));
    _paintCross(canvas, size, both);
    canvas.restore();
    if (both) {
      canvas.drawLine(Offset(0, h), Offset(size.width, h), Paint()
        ..color = _grid
        ..strokeWidth = 1);
    }
  }

  /// [first, last] candle index whose x lies inside the plot (+1 candle of margin each side).
  List<int> _range() {
    final i0 = ((d.n - 1) + rightBlank + 0.5 - plotW / slot).floor() - 1;
    final i1 = ((d.n - 1) + rightBlank + 0.5).floor() + 1;
    return [math.max(0, i0), math.min(d.n - 1, i1)];
  }

  void _text(Canvas canvas, String t, Offset o, Color c, {double fs = 9.5, bool right = false, bool bold = false}) {
    final tp = TextPainter(
      text: TextSpan(text: t, style: TextStyle(color: c, fontSize: fs, fontWeight: bold ? FontWeight.w700 : FontWeight.w500)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, right ? Offset(o.dx - tp.width, o.dy) : o);
  }

  void _drawRuns(Canvas canvas, List<double?> v, double Function(double) y, Paint p, int i0, int i1) {
    Path? path;
    for (var i = i0; i <= i1; i++) {
      final val = v[i];
      if (val == null) {
        if (path != null) canvas.drawPath(path, p);
        path = null;
        continue;
      }
      final px = _x(i);
      final py = y(val);
      if (path == null) {
        path = Path()..moveTo(px, py);
      } else {
        path.lineTo(px, py);
      }
    }
    if (path != null) canvas.drawPath(path, p);
  }

  // ------------------------------------------------------------ Ob/Os cross background tint (bgcolor)
  void _paintCrossTint(Canvas canvas, Size size) {
    if (!st.tsiOn || !st.b('obCross')) return;
    final rg = _range();
    for (var i = rg[0]; i <= rg[1]; i++) {
      final cx = d.cross[i];
      if (cx == 0) continue;
      final x = _x(i);
      canvas.drawRect(Rect.fromLTRB(x - slot / 2, 0, x + slot / 2, size.height),
          Paint()..color = (cx > 0 ? const Color(0xFF4CAF50) : const Color(0xFFFF5252)).withOpacity(0.20));
    }
  }

  // ------------------------------------------------------------ TSI pane
  void _paintTsi(Canvas canvas, Rect r) {
    final rg = _range();
    final i0 = rg[0], i1 = rg[1];
    final ob = st.n('ob'), os = st.n('os');
    var lo = math.min(-45.0, os - 10), hi = math.max(45.0, ob + 10);
    for (var i = i0; i <= i1; i++) {
      for (final v in [d.tsi[i], d.tsl[i]]) {
        if (v == null) continue;
        lo = math.min(lo, v);
        hi = math.max(hi, v);
      }
    }
    final pad = (hi - lo) * 0.10;
    lo -= pad;
    hi += pad;
    if (tsiScale != 1.0) {
      final cm = (hi + lo) / 2, ch = (hi - lo) / 2 / tsiScale;
      lo = cm - ch;
      hi = cm + ch;
    }
    if (tsiShift != 0.0) {
      final sh = (hi - lo) * tsiShift;
      lo += sh;
      hi += sh;
    }
    _tsiLo = lo;
    _tsiHi = hi;
    double y(double v) => r.top + 14 + (hi - v) / (hi - lo) * (r.height - 18);

    // Ob / Os / zero lines (script colours: Ob red, Os light blue, zero grey - all 65% transparent)
    void hline(double lvl, Color c, String label) {
      canvas.drawLine(Offset(0, y(lvl)), Offset(plotW, y(lvl)), Paint()
        ..color = c.withOpacity(0.35)
        ..strokeWidth = 1);
      _text(canvas, label, Offset(r.right - 4, y(lvl) - 6), _ink.withOpacity(0.5), right: true);
    }

    if (st.b('obLines')) {
      hline(ob, const Color(0xFFFF0000), ob.toStringAsFixed(0));
      hline(os, const Color(0xFF64B5F6), os.toStringAsFixed(0));
    }
    if (st.b('zeroLine')) hline(0, const Color(0xFFB2B5BE), '0');

    // TSI classic fill between value and signal (bull = light blue, bear = red, 88% transparent)
    if (st.b('tsiFill')) {
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final a1 = d.tsi[i - 1], a2 = d.tsl[i - 1], b1 = d.tsi[i], b2 = d.tsl[i];
        if (a1 == null || a2 == null || b1 == null || b2 == null) continue;
        final p = Path()
          ..moveTo(_x(i - 1), y(a1))
          ..lineTo(_x(i), y(b1))
          ..lineTo(_x(i), y(b2))
          ..lineTo(_x(i - 1), y(a2))
          ..close();
        canvas.drawPath(p, Paint()..color = (b1 >= b2 ? const Color(0xFF64B5F6) : const Color(0xFFD32F2F)).withOpacity(0.12));
      }
    }

    // Bj candle bars = TSI - signal, body drawn from zero (classic: green / red, 50% transparent)
    if (st.b('bjBars')) {
      final bw = math.max(1.0, slot * 0.7);
      for (var i = i0; i <= i1; i++) {
        final df = d.diff[i];
        if (df == null) continue;
        final p = Paint()..color = (df >= 0 ? const Color(0xFF4CAF50) : const Color(0xFFFF0000)).withOpacity(0.5);
        final x = _x(i);
        canvas.drawRect(Rect.fromLTRB(x - bw / 2, math.min(y(0), y(df)), x + bw / 2, math.max(y(0), y(df))), p);
      }
    }

    // signal line: 4-zone colour per segment (Signal>0: light green = TSI under it, dark green = over it;
    // Signal<0: dark red = TSI under it, light red = over it). Off = classic blue / red by signal direction.
    if (st.b('tsiSignal')) {
      final sp = Paint()
        ..strokeWidth = 1.0
        ..style = PaintingStyle.stroke;
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final a = d.tsl[i - 1];
        final b = d.tsl[i];
        final t = d.tsi[i];
        if (a == null || b == null || t == null) continue;
        Color c;
        if (st.b('sig4')) {
          if (b > 0) {
            c = t < b ? const Color(0xFF90EE90) : const Color(0xFF006400);
          } else if (b < 0) {
            c = t < b ? const Color(0xFF8B0000) : const Color(0xFFFF8A80);
          } else {
            c = b >= a ? const Color(0xFF64B5F6) : const Color(0xFFD32F2F);
          }
        } else {
          c = b >= a ? const Color(0xFF64B5F6) : const Color(0xFFD32F2F);
        }
        sp.color = c;
        canvas.drawLine(Offset(_x(i - 1), y(a)), Offset(_x(i), y(b)), sp);
      }
    }

    // TSI value line: curl up / mid / curl down colours (script "TSI Value Line" inputs)
    if (st.b('tsiValue')) {
      final vp = Paint()
        ..strokeWidth = 1.0
        ..style = PaintingStyle.stroke;
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final a = d.tsi[i - 1];
        final b = d.tsi[i];
        final s = d.tsl[i];
        if (a == null || b == null || s == null) continue;
        final curlUp = b > a && b < s;
        final curlDn = b < a && b > s;
        vp.color = curlUp ? st.c('cTsiBull') : curlDn ? st.c('cTsiBear') : st.c('cTsiMid');
        canvas.drawLine(Offset(_x(i - 1), y(a)), Offset(_x(i), y(b)), vp);
      }
    }

    // reversal warning arrows (hidden in the owner's TradingView Style tab -> off by default)
    if (st.b('arrows')) {
      for (var i = i0; i <= i1; i++) {
        final w = d.warn[i];
        final t = d.tsi[i];
        if (w == 0 || t == null) continue;
        final x = _x(i);
        final down = w < 0;
        final cy = down ? y(t) - 14 : y(t) + 14;
        final path = Path();
        if (down) {
          path
            ..moveTo(x - 5, cy - 5)
            ..lineTo(x + 5, cy - 5)
            ..lineTo(x, cy + 5);
        } else {
          path
            ..moveTo(x - 5, cy + 5)
            ..lineTo(x + 5, cy + 5)
            ..lineTo(x, cy - 5);
        }
        path.close();
        canvas.drawPath(path, Paint()..color = down ? const Color(0xFFFF1744) : const Color(0xFF00E676));
      }
    }

    // value labels (|TSI - signal| rounded) every N candles
    if (st.b('labels')) {
      final every = math.max(1, st.i('labelEvery'));
      for (var i = i0; i <= i1; i++) {
        if (i % every != 0) continue;
        final df = d.diff[i];
        if (df == null) continue;
        _text(canvas, df.abs().round().toString(), Offset(_x(i) - 3, r.bottom - 12),
            df > 0 ? const Color(0xFF2E7D32) : const Color(0xFFC62828), fs: 8);
      }
    }

    // header
    final k = markIdx ?? (d.n - 1);
    final idx = k.clamp(0, d.n - 1).toInt();
    final tv = d.tsi[idx], sv = d.tsl[idx], dv = d.diff[idx];
    var recent = 0;
    for (var j = math.max(0, idx - 2); j <= idx; j++) {
      if (d.warn[j] != 0) recent = d.warn[j];
    }
    final head = (tv == null || sv == null || dv == null)
        ? 'Special Master - TSI'
        : 'TSI ${tv.toStringAsFixed(1)}  signal ${sv.toStringAsFixed(1)}  gap ${dv >= 0 ? '+' : ''}${dv.toStringAsFixed(1)}';
    _text(canvas, head, Offset(r.left + 4, r.top + 1), _ink.withOpacity(0.85), bold: true);
    if (recent != 0 && st.b('arrows')) {
      _text(canvas, recent < 0 ? 'DOWN warning' : 'UP warning', Offset(r.left + 4 + 190, r.top + 1),
          recent < 0 ? const Color(0xFFFF1744) : const Color(0xFF00C853), bold: true);
    }
  }

  // ------------------------------------------------------------ Z pane
  void _paintZ(Canvas canvas, Rect r) {
    final rg = _range();
    final i0 = rg[0], i1 = rg[1];
    final style = st.s('zStyle');
    final candles = style == 'Candles';
    var lo = -3.3, hi = 3.3;
    for (var i = i0; i <= i1; i++) {
      for (final v in candles ? [d.zH[i], d.zL[i]] : [d.z[i]]) {
        if (v == null) continue;
        lo = math.min(lo, v);
        hi = math.max(hi, v);
      }
    }
    final pad = (hi - lo) * 0.06;
    lo -= pad;
    hi += pad;
    if (zScale != 1.0) {
      final cm = (hi + lo) / 2, ch = (hi - lo) / 2 / zScale;
      lo = cm - ch;
      hi = cm + ch;
    }
    if (zShift != 0.0) {
      final sh = (hi - lo) * zShift;
      lo += sh;
      hi += sh;
    }
    _zLo = lo;
    _zHi = hi;
    double y(double v) => r.top + 14 + (hi - v) / (hi - lo) * (r.height - 18);
    // probability bands: 0..1 green, 1..2 yellow, 2..3 red (both sides)
    if (st.b('probBands')) {
      final o = _op(st.n('probTransp'));
      void band(double a, double b, Color c) {
        canvas.drawRect(Rect.fromLTRB(0, y(b), plotW, y(a)), Paint()..color = c.withOpacity(o));
        canvas.drawRect(Rect.fromLTRB(0, y(-a), plotW, y(-b)), Paint()..color = c.withOpacity(o));
      }

      band(0, 1, const Color(0xFF4CAF50));
      band(1, 2, const Color(0xFFFFEB3B));
      band(2, 3, const Color(0xFFFF5252));
      for (final lvl in [3.0, 2.0, 1.0, -1.0, -2.0, -3.0]) {
        canvas.drawLine(Offset(0, y(lvl)), Offset(plotW, y(lvl)), Paint()
          ..color = _grid
          ..strokeWidth = 1);
        _text(canvas, '${lvl > 0 ? '+' : ''}${lvl.toStringAsFixed(0)}s', Offset(r.right - 4, y(lvl) - 6),
            _ink.withOpacity(0.5), right: true);
      }
    }
    if (st.b('zBase')) {
      canvas.drawLine(Offset(0, y(0)), Offset(plotW, y(0)), Paint()
        ..color = _ink.withOpacity(0.28)
        ..strokeWidth = 1);
      _text(canvas, '0', Offset(r.right - 4, y(0) - 6), _ink.withOpacity(0.5), right: true);
    }
    final bull = st.c('cZBull'), bear = st.c('cZBear');
    final emaOn = st.b('zEma') && d.zEmaF.length == d.n && d.zEmaS.length == d.n;
    final emaMode = st.s('zEmaMode');
    // Z EMA cloud (fast vs slow), drawn first so the Z candles sit on top of it
    if (emaOn && emaMode != 'EMA Only') {
      final o = _op(st.n('emaCloudTransp'));
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final f0 = d.zEmaF[i - 1], f1 = d.zEmaF[i], s0 = d.zEmaS[i - 1], s1 = d.zEmaS[i];
        if (f0 == null || f1 == null || s0 == null || s1 == null) continue;
        final p = Path()
          ..moveTo(_x(i - 1), y(f0))
          ..lineTo(_x(i), y(f1))
          ..lineTo(_x(i), y(s1))
          ..lineTo(_x(i - 1), y(s0))
          ..close();
        canvas.drawPath(p, Paint()..color = (f1 >= s1 ? st.c('cEmaBull') : st.c('cEmaBear')).withOpacity(o));
      }
    }
    if (style == 'Area') {
      final o = _op(st.n('zTransp'));
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final a = d.z[i - 1];
        final b = d.z[i];
        if (a == null || b == null) continue;
        final p = Path()
          ..moveTo(_x(i - 1), y(0))
          ..lineTo(_x(i - 1), y(a))
          ..lineTo(_x(i), y(b))
          ..lineTo(_x(i), y(0))
          ..close();
        canvas.drawPath(p, Paint()..color = (b >= 0 ? bull : bear).withOpacity(o));
      }
    }
    if (style == 'Area' || style == 'K-Line') {
      for (var i = math.max(i0, 1); i <= i1; i++) {
        final a = d.z[i - 1];
        final b = d.z[i];
        if (a == null || b == null) continue;
        final col = style == 'K-Line' ? (b > 0 ? const Color(0xFF2962FF) : const Color(0xFFFF5252)) : (b > 0 ? bull : bear);
        canvas.drawLine(
            Offset(_x(i - 1), y(a)),
            Offset(_x(i), y(b)),
            Paint()
              ..color = col
              ..strokeWidth = 1.0);
      }
    }
    if (candles) {
      final bw = math.max(1.0, slot * 0.7);
      for (var i = i0; i <= i1; i++) {
        final zo = d.zO[i], zh = d.zH[i], zl = d.zL[i], zc = d.z[i];
        if (zo == null || zh == null || zl == null || zc == null) continue;
        final col = zo > zc ? bear : bull;
        final x = _x(i);
        canvas.drawLine(Offset(x, y(zh)), Offset(x, y(zl)), Paint()
          ..color = col
          ..strokeWidth = 1);
        canvas.drawRect(Rect.fromLTRB(x - bw / 2, math.min(y(zo), y(zc)), x + bw / 2, math.max(y(zo), y(zc)) + 0.5),
            Paint()..color = col);
      }
    }
    Paint line(Color c, double w) => Paint()
      ..color = c
      ..strokeWidth = w
      ..style = PaintingStyle.stroke;
    if (emaOn && emaMode != 'Cloud Only') {
      final ew = st.n('emaWidth').clamp(1.0, 4.0).toDouble();
      _drawRuns(canvas, d.zEmaS, y, line(st.c('cEmaSlow'), ew), i0, i1);
      _drawRuns(canvas, d.zEmaF, y, line(st.c('cEmaFast'), ew), i0, i1);
    }
    // cross signal: the candle turns BLACK with a green (BUY) or red (SELL) border, plus a tiny label
    if (st.b('zSig') && d.zSig.length == d.n) {
      final bw = math.max(2.0, slot * 0.7);
      for (var i = i0; i <= i1; i++) {
        final sg = d.zSig[i];
        final zc = d.z[i];
        if (sg == 0 || zc == null) continue;
        final col = sg > 0 ? st.c('cZBuy') : st.c('cZSell');
        final x = _x(i);
        final zo = candles ? d.zO[i] : null, zh = candles ? d.zH[i] : null, zl = candles ? d.zL[i] : null;
        final border = Paint()
          ..color = col
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.3;
        double top, bottom;
        if (zo != null && zh != null && zl != null) {
          canvas.drawLine(Offset(x, y(zh)), Offset(x, y(zl)), border);
          final body = Rect.fromLTRB(x - bw / 2, math.min(y(zo), y(zc)), x + bw / 2, math.max(y(zo), y(zc)) + 1.0);
          canvas.drawRect(body, Paint()..color = const Color(0xFF000000));
          canvas.drawRect(body, border);
          top = y(zh);
          bottom = y(zl);
        } else {
          canvas.drawCircle(Offset(x, y(zc)), math.max(3.0, slot * 0.4), Paint()..color = const Color(0xFF000000));
          canvas.drawCircle(Offset(x, y(zc)), math.max(3.0, slot * 0.4), border);
          top = bottom = y(zc);
        }
        if (st.b('zSigLbl')) {
          const lw = 24.0, lh = 11.0;
          final cy = sg > 0 ? math.min(bottom + 3 + lh / 2, r.bottom - lh / 2 - 1) : math.max(top - 3 - lh / 2, r.top + 14 + lh / 2);
          final rr = RRect.fromRectAndRadius(Rect.fromCenter(center: Offset(x, cy), width: lw, height: lh), const Radius.circular(3));
          canvas.drawRRect(rr, Paint()..color = col);
          final tp = TextPainter(
            text: TextSpan(text: sg > 0 ? 'BUY' : 'SELL', style: const TextStyle(color: Colors.white, fontSize: 7, fontWeight: FontWeight.w800)),
            textDirection: TextDirection.ltr,
          )..layout();
          tp.paint(canvas, Offset(x - tp.width / 2, cy - tp.height / 2));
        }
      }
    }
    if (st.b('zSma')) {
      if (st.b('sma1')) _drawRuns(canvas, d.zSma1, y, line(_vis(st.c('cSma1')), 1.0), i0, i1);
      if (st.b('sma2')) {
        // Thicker than Z so the average is easy to see; _vis makes black -> white in dark mode.
        _drawRuns(canvas, d.zSma2, y, line(_vis(st.c('cSma2')), 2.0), i0, i1);
        if (indexZsma) {
          _text(canvas, 'Z-SMA 200 (index)', Offset(r.left + 4, r.top + 14), _ink.withOpacity(0.85));
        } else {
          int ok = 0, tot = 0;
          for (int i = i0; i <= i1 && i < d.zSma2.length; i++) {
            tot++;
            if (d.zSma2[i] != null) ok++;
          }
          if (tot > 0 && ok < tot) {
            _text(canvas, 'Z-SMA 200 starts after ~400 candles ($ok/$tot in view)',
                Offset(r.left + 4, r.top + 14), _ink.withOpacity(0.7));
          }
        }
      }
    }
    if (st.b('uclLcl')) {
      _drawRuns(canvas, d.ucl, y, line(st.c('cUcl'), 1.0), i0, i1);
      _drawRuns(canvas, d.lcl, y, line(st.c('cLcl'), 1.0), i0, i1);
    }
    final k = markIdx ?? (d.n - 1);
    final idx = k.clamp(0, d.n - 1).toInt();
    final zv = d.z[idx];
    String zone = '';
    if (zv != null) {
      final a = zv.abs();
      zone = a >= 3 ? '  (3s+)' : a >= 2 ? '  (2s-3s)' : a >= 1 ? '  (1s-2s)' : '  (inside 1s)';
    }
    var extra = '';
    if (zv != null && d.zEmaS.length == d.n && d.zEmaS[idx] != null) {
      extra = zv > d.zEmaS[idx]! ? '  | above EMA${st.i('zEmaSlow')}' : '  | below EMA${st.i('zEmaSlow')}';
    }
    if (d.zSig.length == d.n) {
      for (var j = math.max(0, idx - 2); j <= idx; j++) {
        if (d.zSig[j] != 0) extra += d.zSig[j] > 0 ? '  | BUY signal' : '  | SELL signal';
      }
    }
    _text(canvas, zv == null ? 'Z-score (${st.i('zLen')})' : 'Z ${zv >= 0 ? '+' : ''}${zv.toStringAsFixed(2)}s$zone$extra',
        Offset(r.left + 4, r.top + 1), _ink.withOpacity(0.85), bold: true);
  }

  void _dashLine(Canvas canvas, Offset a, Offset b, Paint p) {
    final len = (b - a).distance;
    if (len <= 0) return;
    final dir = (b - a) / len;
    for (double t = 0; t < len; t += 7) {
      canvas.drawLine(a + dir * t, a + dir * math.min(t + 4, len), p);
    }
  }

  void _edgeChip(Canvas canvas, String text, double x, double yCenter, {bool centerX = false}) {
    final tp = TextPainter(
      text: TextSpan(text: text, style: TextStyle(color: light ? Colors.white : Colors.black, fontSize: 9, fontWeight: FontWeight.w700)),
      textDirection: TextDirection.ltr,
    )..layout();
    final w = tp.width + 6;
    final left = centerX ? x - w / 2 : x;
    final rect = Rect.fromLTWH(left, yCenter - tp.height / 2 - 1, w, tp.height + 2);
    canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(3)), Paint()..color = light ? const Color(0xFF10141C) : Colors.white);
    tp.paint(canvas, Offset(left + 3, yCenter - tp.height / 2));
  }

  /// Crosshair shared with the main chart: vertical line through both panes, horizontal line + value chip in the touched pane.
  void _paintCross(Canvas canvas, Size size, bool both) {
    final cx = crossX;
    if (cx == null) return;
    final p = Paint()
      ..color = _ink.withOpacity(0.55)
      ..strokeWidth = 1;
    final x = cx.clamp(0.0, plotW).toDouble();
    _dashLine(canvas, Offset(x, 0), Offset(x, size.height), p);
    final cy = crossY;
    if (cy != null) {
      final inTsi = st.tsiOn && (!both || cy < size.height / 2);
      final r = inTsi ? _tsiR : _zR;
      final lo = inTsi ? _tsiLo : _zLo;
      final hi = inTsi ? _tsiHi : _zHi;
      final yy = cy.clamp(r.top + 2, r.bottom - 2).toDouble();
      final v = hi - (yy - r.top - 14) / (r.height - 18) * (hi - lo);
      _dashLine(canvas, Offset(0, yy), Offset(plotW, yy), p);
      _edgeChip(canvas, inTsi ? v.toStringAsFixed(1) : v.toStringAsFixed(2), plotW + 2, yy);
    }
    if (crossLabel != null) _edgeChip(canvas, crossLabel!, x, size.height - 8, centerX: true);
  }

  @override
  bool shouldRepaint(covariant SpecialMasterPainter old) =>
      old.d != d ||
      old.st != st ||
      old.slot != slot ||
      old.rightBlank != rightBlank ||
      old.plotW != plotW ||
      old.light != light ||
      old.markIdx != markIdx ||
      old.tsiScale != tsiScale ||
      old.zScale != zScale ||
      old.tsiShift != tsiShift ||
      old.zShift != zShift ||
      old.crossX != crossX ||
      old.crossY != crossY ||
      old.crossLabel != crossLabel ||
      old.indexZsma != indexZsma;
}
