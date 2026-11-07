import 'package:flutter/material.dart';
import 'indicator_sheet.dart';
import 'special_master.dart';

/// "Special Master new" settings - same grouping as the TradingView Inputs / Style tabs, every tick and value of the
/// Pine script that the app can draw. Built on the shared TradingView-style sheet (indicator_sheet.dart).
/// Works on a COPY: Ok returns it, Cancel / close returns null.
Future<SmSettings?> showSmSettingsSheet(BuildContext context, SmSettings current) {
  return showIndicatorSheet<SmSettings>(
    context,
    title: 'Special Master new',
    initial: current,
    defaults: SmSettings.defaults(),
    tabs: [
      IndicatorTab<SmSettings>('Inputs', _inputs),
      IndicatorTab<SmSettings>('Style', _style),
      IndicatorTab<SmSettings>('Visibility', (s, set) => shVisibilityRows(s.hiddenTfs, (h) => set(s.set('hidTf', h.join(','))))),
    ],
  );
}

// ---- tiny row helpers: every row reads from the settings copy [s] and hands a changed copy to [set] ----

Widget _tick(SmSettings s, ValueChanged<SmSettings> set, String label, String k) =>
    ShCheck(label, s.b(k), (v) => set(s.set(k, v)));

Widget _num(SmSettings s, ValueChanged<SmSettings> set, String label, String k,
        {bool isInt = false, double min = -100000, double max = 100000}) =>
    ShNumber(label, k, s.n(k), min, max, (v) => set(s.set(k, v.toDouble())), isInt: isInt);

Widget _color(SmSettings s, ValueChanged<SmSettings> set, String label, String k) =>
    ShColor(label, s.c(k).value, (v) => set(s.set(k, v)));

Widget _drop(SmSettings s, ValueChanged<SmSettings> set, String label, String k, List<String> options) {
  final cur = options.contains(s.s(k)) ? s.s(k) : options.first;
  return ShDrop<String>(label, cur, {for (final o in options) o: o}, (v) => set(s.set(k, v)));
}

List<Widget> _inputs(SmSettings s, ValueChanged<SmSettings> set) => [
      const ShHeader('Master controls'),
      _tick(s, set, 'Enable TSI engine (Bj candle & lines)', 'tsiOn'),
      _tick(s, set, 'Enable Z-score engine (area, SMAs & bands)', 'zOn'),
      // "TSI speed" is a Slow / Fast label but stored as a bool
      ShDrop<String>('Select a speed (TSI)', s.fast ? 'Fast' : 'Slow', const {'Slow': 'Slow', 'Fast': 'Fast'},
          (v) => set(s.set('fast', v == 'Fast'))),
      const ShHeader('Overbought / oversold'),
      _num(s, set, 'Ob value', 'ob', min: -100, max: 100),
      _num(s, set, 'Os value', 'os', min: -100, max: 100),
      _tick(s, set, 'Show Ob/Os lines', 'obLines'),
      _tick(s, set, 'Show Ob/Os cross (background tint)', 'obCross'),
      _tick(s, set, 'Show zero line', 'zeroLine'),
      _tick(s, set, 'Ob/Os curl colour (bars on the main chart)', 'curlBars'),
      const ShHeader('Value labels'),
      _tick(s, set, 'Show labels', 'labels'),
      _num(s, set, 'Show label every N candles', 'labelEvery', isInt: true, min: 1, max: 100),
      const ShHeader('Trend reversal warning arrow'),
      _tick(s, set, 'Enable reversal warning arrow', 'arrows'),
      _num(s, set, 'Z-score extreme threshold (sigma)', 'arrowZ', min: 0.1, max: 5),
      const ShHeader('Z-score configuration'),
      _num(s, set, 'Z-score lookback length', 'zLen', isInt: true, min: 5, max: 1000),
      _drop(s, set, 'Z-score plot style', 'zStyle', const ['Area', 'K-Line', 'Candles', 'None']),
      _num(s, set, 'Z-score area transparency (0-100)', 'zTransp', isInt: true, min: 0, max: 100),
      _tick(s, set, 'Show Z-score SMAs', 'zSma'),
      _num(s, set, 'Z-SMA 1 length', 'sma1Len', isInt: true, min: 2, max: 1000),
      _num(s, set, 'Z-SMA 2 length', 'sma2Len', isInt: true, min: 2, max: 1000),
      _tick(s, set, 'Show probability bands (1s, 2s, 3s)', 'probBands'),
      _num(s, set, 'Probability bands transparency (0-100)', 'probTransp', isInt: true, min: 0, max: 100),
      const ShHeader('Z-score EMA 30 / 50 + cloud'),
      _tick(s, set, 'Show Z-score EMAs', 'zEma'),
      _drop(s, set, 'Display mode', 'zEmaMode', const ['EMA + Cloud', 'EMA Only', 'Cloud Only']),
      _num(s, set, 'Fast EMA length', 'zEmaFast', isInt: true, min: 1, max: 500),
      _num(s, set, 'Slow EMA length', 'zEmaSlow', isInt: true, min: 1, max: 500),
      _num(s, set, 'EMA line width', 'emaWidth', isInt: true, min: 1, max: 4),
      _num(s, set, 'Cloud transparency (0-100)', 'emaCloudTransp', isInt: true, min: 0, max: 100),
      const ShHeader('Z-score EMA cross signals (buy / sell)'),
      _drop(s, set, 'Signal rule', 'zSigRule',
          const ['Candle Close crosses Slow EMA', 'Candle Close crosses Fast EMA', 'Fast EMA crosses Slow EMA']),
      _tick(s, set, 'Enable cross signals (black candle + coloured border)', 'zSig'),
      _tick(s, set, 'Show tiny BUY / SELL labels', 'zSigLbl'),
    ];

List<Widget> _style(SmSettings s, ValueChanged<SmSettings> set) => [
      const ShHeader('Top deck - TSI'),
      _tick(s, set, 'Bj candle bars', 'bjBars'),
      _tick(s, set, 'TSI value line', 'tsiValue'),
      _tick(s, set, 'TSI signal line', 'tsiSignal'),
      _tick(s, set, '4-zone colour on signal line', 'sig4'),
      _tick(s, set, 'TSI fill (value vs signal)', 'tsiFill'),
      _color(s, set, 'TSI value line - curl up colour', 'cTsiBull'),
      _color(s, set, 'TSI value line - mid colour', 'cTsiMid'),
      _color(s, set, 'TSI value line - curl down colour', 'cTsiBear'),
      const ShHeader('Bottom deck - Z-score'),
      _tick(s, set, 'Z base (0 sigma) line', 'zBase'),
      _tick(s, set, 'Z-SMA 1', 'sma1'),
      _tick(s, set, 'Z-SMA 2', 'sma2'),
      _tick(s, set, 'Z-SMA UCL / LCL band', 'uclLcl'),
      _color(s, set, 'Bull area colour', 'cZBull'),
      _color(s, set, 'Bear area colour', 'cZBear'),
      _color(s, set, 'Z-SMA 1 colour', 'cSma1'),
      _color(s, set, 'Z-SMA 2 colour', 'cSma2'),
      _color(s, set, 'UCL band colour', 'cUcl'),
      _color(s, set, 'LCL band colour', 'cLcl'),
      _color(s, set, 'Fast EMA colour', 'cEmaFast'),
      _color(s, set, 'Slow EMA colour', 'cEmaSlow'),
      _color(s, set, 'Cloud colour: fast above slow', 'cEmaBull'),
      _color(s, set, 'Cloud colour: fast below slow', 'cEmaBear'),
      _color(s, set, 'BUY border colour', 'cZBuy'),
      _color(s, set, 'SELL border colour', 'cZSell'),
    ];
