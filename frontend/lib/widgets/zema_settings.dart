import 'dart:convert';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'indicator_sheet.dart';

/// ZEMA = the bottom Z-Score EMA 30 / 50 (the ones Special Master draws in its own pane), MIRRORED on the main chart.
///   z       = (close - SMA(close, zLen)) / STDEV(close, zLen)
///   zEma    = EMA(z, len)                        <- exactly the bottom EMA
///   price   = SMA + zEma * slowSD                <- slowSD = EMA(STDEV, 50)
/// The SD is smoothed on purpose, so the line keeps the same smooth shape as the bottom EMA (price may cross it
/// anywhere - it is a mirror, not a price EMA). DISPLAY ONLY - nothing here touches the bot's own signals.
class ZemaSettings {
  static const prefsKey = 'zema_settings_v1';

  final bool on; // eye: show / hide the whole indicator
  final bool showFast;
  final bool showSlow;
  final bool cloud;
  final int fastLen;
  final int slowLen;
  final int zLen; // Z-Score lookback (same as Special Master "Z-score lookback length")
  final double width; // fast line (px)
  final int dash; // fast line: 0 solid, 1 dashed, 2 dotted
  final double slowWidth;
  final int slowDash;
  final int fastColor; // ARGB
  final int slowColor;
  final int cloudBullColor;
  final int cloudBearColor;
  final int cloudTransp; // 0-100, like TradingView
  final Set<String> hiddenTfs; // timeframes where the indicator is hidden (Visibility tab)

  const ZemaSettings({
    this.on = true,
    this.showFast = true,
    this.showSlow = true,
    this.cloud = true,
    this.fastLen = 30,
    this.slowLen = 50,
    this.zLen = 200,
    this.width = 1.0,
    this.dash = 0,
    this.slowWidth = 1.0,
    this.slowDash = 0,
    this.fastColor = 0xFF4CAF50,
    this.slowColor = 0xFFF23645,
    this.cloudBullColor = 0xFF4CAF50,
    this.cloudBearColor = 0xFFFF5252,
    this.cloudTransp = 70,
    this.hiddenTfs = const <String>{},
  });

  factory ZemaSettings.defaults() => const ZemaSettings();

  ZemaSettings copyWith({
    bool? on,
    bool? showFast,
    bool? showSlow,
    bool? cloud,
    int? fastLen,
    int? slowLen,
    int? zLen,
    double? width,
    int? dash,
    double? slowWidth,
    int? slowDash,
    int? fastColor,
    int? slowColor,
    int? cloudBullColor,
    int? cloudBearColor,
    int? cloudTransp,
    Set<String>? hiddenTfs,
  }) =>
      ZemaSettings(
        on: on ?? this.on,
        showFast: showFast ?? this.showFast,
        showSlow: showSlow ?? this.showSlow,
        cloud: cloud ?? this.cloud,
        fastLen: fastLen ?? this.fastLen,
        slowLen: slowLen ?? this.slowLen,
        zLen: zLen ?? this.zLen,
        width: width ?? this.width,
        dash: dash ?? this.dash,
        slowWidth: slowWidth ?? this.slowWidth,
        slowDash: slowDash ?? this.slowDash,
        fastColor: fastColor ?? this.fastColor,
        slowColor: slowColor ?? this.slowColor,
        cloudBullColor: cloudBullColor ?? this.cloudBullColor,
        cloudBearColor: cloudBearColor ?? this.cloudBearColor,
        cloudTransp: cloudTransp ?? this.cloudTransp,
        hiddenTfs: hiddenTfs ?? this.hiddenTfs,
      );

  /// Only these change the numbers (a colour / width / eye change must not recompute).
  String get computeKey => '$fastLen|$slowLen|$zLen';

  /// True when the indicator should be drawn on this timeframe label ("5m", "15m" ...).
  bool visibleOn(String tf) => on && !hiddenTfs.contains(tf);

  String toJson() => jsonEncode({
        'on': on,
        'showFast': showFast,
        'showSlow': showSlow,
        'cloud': cloud,
        'fastLen': fastLen,
        'slowLen': slowLen,
        'zLen': zLen,
        'width': width,
        'dash': dash,
        'slowWidth': slowWidth,
        'slowDash': slowDash,
        'fastColor': fastColor,
        'slowColor': slowColor,
        'cloudBullColor': cloudBullColor,
        'cloudBearColor': cloudBearColor,
        'cloudTransp': cloudTransp,
        'hiddenTfs': hiddenTfs.toList(),
      });

  factory ZemaSettings.fromJson(String? raw) {
    if (raw == null || raw.isEmpty) return ZemaSettings.defaults();
    try {
      final m = jsonDecode(raw);
      if (m is! Map) return ZemaSettings.defaults();
      const d = ZemaSettings();
      bool b(String k, bool def) => m[k] is bool ? m[k] as bool : def;
      double w(String k, double def) => m[k] is num ? (m[k] as num).toDouble().clamp(0.5, 6.0).toDouble() : def;
      int i(String k, int def, int lo, int hi) => m[k] is num ? (m[k] as num).toInt().clamp(lo, hi).toInt() : def;
      return ZemaSettings(
        on: b('on', d.on),
        showFast: b('showFast', d.showFast),
        showSlow: b('showSlow', d.showSlow),
        cloud: b('cloud', d.cloud),
        fastLen: i('fastLen', d.fastLen, 1, 500),
        slowLen: i('slowLen', d.slowLen, 1, 500),
        zLen: i('zLen', d.zLen, 5, 1000),
        width: w('width', d.width),
        dash: i('dash', d.dash, 0, 2),
        slowWidth: w('slowWidth', d.slowWidth),
        slowDash: i('slowDash', d.slowDash, 0, 2),
        fastColor: i('fastColor', d.fastColor, 0, 0xFFFFFFFF),
        slowColor: i('slowColor', d.slowColor, 0, 0xFFFFFFFF),
        cloudBullColor: i('cloudBullColor', d.cloudBullColor, 0, 0xFFFFFFFF),
        cloudBearColor: i('cloudBearColor', d.cloudBearColor, 0, 0xFFFFFFFF),
        cloudTransp: i('cloudTransp', d.cloudTransp, 0, 100),
        hiddenTfs: m['hiddenTfs'] is List
            ? {for (final x in (m['hiddenTfs'] as List)) if (x is String) x}
            : d.hiddenTfs,
      );
    } catch (_) {
      return ZemaSettings.defaults();
    }
  }
}

/// The two price-unit lines. NaN = not enough candles yet (the painter skips NaN).
class ZemaLines {
  final List<double> fast;
  final List<double> slow;
  const ZemaLines(this.fast, this.slow);

  static ZemaLines compute(List<double> close, ZemaSettings st) {
    final n = close.length;
    final nan = double.nan;
    final fast = List<double>.filled(n, nan);
    final slow = List<double>.filled(n, nan);
    final zLen = st.zLen;
    if (n < zLen + 2) return ZemaLines(fast, slow);

    // Rolling SMA + population STDEV over zLen (same as Pine ta.sma / ta.stdev), O(n) with running sums.
    final sma = List<double>.filled(n, nan);
    final sd = List<double>.filled(n, nan);
    final z = List<double>.filled(n, nan);
    double s1 = 0, s2 = 0;
    for (int i = 0; i < n; i++) {
      s1 += close[i];
      s2 += close[i] * close[i];
      if (i >= zLen) {
        s1 -= close[i - zLen];
        s2 -= close[i - zLen] * close[i - zLen];
      }
      if (i >= zLen - 1) {
        final mean = s1 / zLen;
        final varc = math.max(0.0, s2 / zLen - mean * mean);
        sma[i] = mean;
        sd[i] = math.sqrt(varc);
        z[i] = sd[i] > 0 ? (close[i] - mean) / sd[i] : 0.0;
      }
    }

    final zf = _emaNaN(z, st.fastLen); // the bottom Z-EMAs, in z units
    final zs = _emaNaN(z, st.slowLen);
    final sdSlow = _emaNaN(sd, 50); // slow SD -> smooth mirror
    for (int i = 0; i < n; i++) {
      if (sma[i].isNaN || sdSlow[i].isNaN) continue;
      if (!zf[i].isNaN) fast[i] = sma[i] + zf[i] * sdSlow[i];
      if (!zs[i].isNaN) slow[i] = sma[i] + zs[i] * sdSlow[i];
    }
    return ZemaLines(fast, slow);
  }

  /// EMA that ignores leading NaNs and seeds with the SMA of the first [len] valid values (Pine ta.ema).
  static List<double> _emaNaN(List<double> v, int len) {
    final n = v.length;
    final out = List<double>.filled(n, double.nan);
    final alpha = 2.0 / (len + 1);
    int count = 0;
    double sum = 0;
    double? prev;
    for (int i = 0; i < n; i++) {
      final x = v[i];
      if (x.isNaN) {
        if (prev != null) out[i] = prev; // keep the line continuous over a stray NaN
        continue;
      }
      if (prev == null) {
        count++;
        sum += x;
        if (count == len) {
          prev = sum / len;
          out[i] = prev;
        }
      } else {
        prev = x * alpha + prev * (1 - alpha);
        out[i] = prev;
      }
    }
    return out;
  }
}

// ------------------------------------------------------------------ settings sheet (Inputs / Style / Visibility)

/// Opens the TradingView-style sheet. Returns the new settings on Ok, null on Cancel.
Future<ZemaSettings?> showZemaSettingsSheet(BuildContext context, ZemaSettings current) {
  return showIndicatorSheet<ZemaSettings>(
    context,
    title: 'ZEMA',
    initial: current,
    defaults: ZemaSettings.defaults(),
    tabs: [
      IndicatorTab<ZemaSettings>('Inputs', (s, set) => [
            const ShHeader('Z-Score EMA mirrored on the main chart'),
            ShCheck('Show ZEMA on main chart', s.on, (v) => set(s.copyWith(on: v))),
            ShCheck('Show Fast EMA', s.showFast, (v) => set(s.copyWith(showFast: v))),
            ShCheck('Show Slow EMA', s.showSlow, (v) => set(s.copyWith(showSlow: v))),
            ShCheck('Show cloud (Fast vs Slow)', s.cloud, (v) => set(s.copyWith(cloud: v))),
            const ShHeader('Lengths'),
            ShNumber('Fast EMA length', 'fl', s.fastLen, 1, 500, (v) => set(s.copyWith(fastLen: v.toInt()))),
            ShNumber('Slow EMA length', 'sl', s.slowLen, 1, 500, (v) => set(s.copyWith(slowLen: v.toInt()))),
            ShNumber('Z-Score lookback length', 'zl', s.zLen, 5, 1000, (v) => set(s.copyWith(zLen: v.toInt()))),
            const ShHeader('Cloud'),
            ShNumber('Cloud transparency (0-100)', 'ct', s.cloudTransp, 0, 100, (v) => set(s.copyWith(cloudTransp: v.toInt()))),
          ]),
      IndicatorTab<ZemaSettings>('Style', (s, set) => [
            const ShHeader('Lines'),
            ShStyleRow(
              label: 'Z-EMA Fast',
              on: s.showFast,
              onToggle: (v) => set(s.copyWith(showFast: v)),
              argb: s.fastColor,
              onColor: (c) => set(s.copyWith(fastColor: c)),
              width: s.width.round(),
              onWidth: (w) => set(s.copyWith(width: w.toDouble())),
              dash: s.dash,
              onDash: (d) => set(s.copyWith(dash: d)),
            ),
            ShStyleRow(
              label: 'Z-EMA Slow',
              on: s.showSlow,
              onToggle: (v) => set(s.copyWith(showSlow: v)),
              argb: s.slowColor,
              onColor: (c) => set(s.copyWith(slowColor: c)),
              width: s.slowWidth.round(),
              onWidth: (w) => set(s.copyWith(slowWidth: w.toDouble())),
              dash: s.slowDash,
              onDash: (d) => set(s.copyWith(slowDash: d)),
            ),
            const ShHeader('Cloud (opacity is shared by both colours)'),
            ShColor('Cloud: Fast above Slow', _cloudArgb(s, s.cloudBullColor), (c) => set(s.copyWith(cloudBullColor: _rgbOnly(c), cloudTransp: _transpOf(c)))),
            ShColor('Cloud: Fast below Slow', _cloudArgb(s, s.cloudBearColor), (c) => set(s.copyWith(cloudBearColor: _rgbOnly(c), cloudTransp: _transpOf(c)))),
          ]),
      IndicatorTab<ZemaSettings>('Visibility', (s, set) => shVisibilityRows(s.hiddenTfs, (h) => set(s.copyWith(hiddenTfs: h)))),
    ],
  );
}

// Cloud colour + opacity in ONE picker: the picker's alpha is the cloud opacity, stored as the 0-100 transparency.
int _cloudArgb(ZemaSettings s, int rgb) => ((((100 - s.cloudTransp) * 255) / 100).round() << 24) | (rgb & 0xFFFFFF);
int _rgbOnly(int argb) => 0xFF000000 | (argb & 0xFFFFFF);
int _transpOf(int argb) => (100 - ((((argb >> 24) & 0xFF) * 100) / 255).round()).clamp(0, 100).toInt();
