import 'package:flutter/material.dart';
import 'special_master.dart';

/// "Special Master new" settings sheet - same grouping as the TradingView Inputs / Style tabs, every tick and
/// value of the Pine script that the app can draw. Works on a COPY: Ok returns it, Cancel / close returns null.
Future<SmSettings?> showSmSettingsSheet(BuildContext context, SmSettings current) {
  return showModalBottomSheet<SmSettings>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (_) => _SmSettingsSheet(initial: current),
  );
}

const _ink = Color(0xFF10141C);
const _palette = <int>[
  0xFF808080, 0xFF000000, 0xFFFFFFFF, 0xFF4CAF50, 0xFFFF5252, 0xFF2962FF, 0xFF64B5F6,
  0xFFFFEB3B, 0xFFFF9800, 0xFF9C27B0, 0xFF00E676, 0xFFD32F2F,
];

class _SmSettingsSheet extends StatefulWidget {
  final SmSettings initial;
  const _SmSettingsSheet({required this.initial});

  @override
  State<_SmSettingsSheet> createState() => _SmSettingsSheetState();
}

class _SmSettingsSheetState extends State<_SmSettingsSheet> {
  late SmSettings s = widget.initial;
  int _tab = 0; // 0 Inputs, 1 Style
  int _rev = 0; // bumps on reset so number fields rebuild with the new text

  void _set(String k, dynamic v) => setState(() => s = s.set(k, v));

  Widget _head(String t) => Padding(
        padding: const EdgeInsets.only(top: 14, bottom: 2),
        child: Text(t.toUpperCase(), style: const TextStyle(color: Colors.grey, fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.4)),
      );

  Widget _tick(String label, String k) => InkWell(
        onTap: () => _set(k, !s.b(k)),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Checkbox(
              value: s.b(k),
              onChanged: (v) => _set(k, v == true),
              visualDensity: VisualDensity.compact,
              activeColor: _ink,
            ),
            Expanded(child: Text(label, style: const TextStyle(color: _ink, fontSize: 14.5))),
          ]),
        ),
      );

  Widget _num(String label, String k, {bool isInt = false, double min = -100000, double max = 100000}) {
    final v = s.n(k);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        Expanded(child: Text(label, style: const TextStyle(color: _ink, fontSize: 14.5))),
        SizedBox(
          width: 96,
          child: TextFormField(
            key: ValueKey('$k$_rev'),
            initialValue: isInt ? v.round().toString() : (v == v.roundToDouble() ? v.toStringAsFixed(0) : v.toString()),
            keyboardType: const TextInputType.numberWithOptions(decimal: true, signed: true),
            style: const TextStyle(color: _ink, fontSize: 14.5),
            decoration: InputDecoration(
              isDense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 9),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            ),
            onChanged: (t) {
              final p = double.tryParse(t.trim());
              if (p == null || p < min || p > max) return; // ignore half-typed / out-of-range values
              s = s.set(k, isInt ? p.roundToDouble() : p);
              setState(() {});
            },
          ),
        ),
      ]),
    );
  }

  Widget _color(String label, String k) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(color: _ink, fontSize: 14.5)),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 8, children: [
            for (final c in _palette)
              GestureDetector(
                onTap: () => _set(k, c),
                child: Container(
                  width: 28,
                  height: 28,
                  decoration: BoxDecoration(
                    color: Color(c),
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                      color: s.c(k).value == c ? const Color(0xFF2962FF) : const Color(0xFFD5DAE3),
                      width: s.c(k).value == c ? 3 : 1,
                    ),
                  ),
                ),
              ),
          ]),
        ]),
      );

  Widget _dropdown(String label, String k, List<String> options) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(color: _ink, fontSize: 14.5))),
          DropdownButton<String>(
            value: options.contains(s.s(k)) ? s.s(k) : options.first,
            style: const TextStyle(color: _ink, fontSize: 14.5),
            dropdownColor: Colors.white,
            underline: Container(height: 1, color: const Color(0xFFD5DAE3)),
            items: [for (final o in options) DropdownMenuItem(value: o, child: Text(o))],
            onChanged: (v) {
              if (v != null) _set(k, v);
            },
          ),
        ]),
      );

  List<Widget> _inputs() => [
        _head('Master controls'),
        _tick('Enable TSI engine (Bj candle & lines)', 'tsiOn'),
        _tick('Enable Z-score engine (area, SMAs & bands)', 'zOn'),
        const SizedBox.shrink(), // TSI speed row - replaced in build() (stored as a bool)
        _head('Overbought / oversold'),
        _num('Ob value', 'ob', min: -100, max: 100),
        _num('Os value', 'os', min: -100, max: 100),
        _tick('Show Ob/Os lines', 'obLines'),
        _tick('Show Ob/Os cross (background tint)', 'obCross'),
        _tick('Show zero line', 'zeroLine'),
        _tick('Ob/Os curl colour (bars on the main chart)', 'curlBars'),
        _head('Value labels'),
        _tick('Show labels', 'labels'),
        _num('Show label every N candles', 'labelEvery', isInt: true, min: 1, max: 100),
        _head('Trend reversal warning arrow'),
        _tick('Enable reversal warning arrow', 'arrows'),
        _num('Z-score extreme threshold (sigma)', 'arrowZ', min: 0.1, max: 5),
        _head('Z-score configuration'),
        _num('Z-score lookback length', 'zLen', isInt: true, min: 5, max: 1000),
        _dropdown('Z-score plot style', 'zStyle', const ['Area', 'K-Line', 'Candles', 'None']),
        _num('Z-score area transparency (0-100)', 'zTransp', isInt: true, min: 0, max: 100),
        _tick('Show Z-score SMAs', 'zSma'),
        _num('Z-SMA 1 length', 'sma1Len', isInt: true, min: 2, max: 1000),
        _num('Z-SMA 2 length', 'sma2Len', isInt: true, min: 2, max: 1000),
        _tick('Show probability bands (1s, 2s, 3s)', 'probBands'),
        _num('Probability bands transparency (0-100)', 'probTransp', isInt: true, min: 0, max: 100),
        _head('Z-score EMA 30 / 50 + cloud'),
        _tick('Show Z-score EMAs', 'zEma'),
        _dropdown('Display mode', 'zEmaMode', const ['EMA + Cloud', 'EMA Only', 'Cloud Only']),
        _num('Fast EMA length', 'zEmaFast', isInt: true, min: 1, max: 500),
        _num('Slow EMA length', 'zEmaSlow', isInt: true, min: 1, max: 500),
        _num('EMA line width', 'emaWidth', isInt: true, min: 1, max: 4),
        _num('Cloud transparency (0-100)', 'emaCloudTransp', isInt: true, min: 0, max: 100),
        _head('Z-score EMA cross signals (buy / sell)'),
        _dropdown('Signal rule', 'zSigRule',
            const ['Candle Close crosses Slow EMA', 'Candle Close crosses Fast EMA', 'Fast EMA crosses Slow EMA']),
        _tick('Enable cross signals (black candle + coloured border)', 'zSig'),
        _tick('Show tiny BUY / SELL labels', 'zSigLbl'),
      ];

  List<Widget> _style() => [
        _head('Top deck - TSI'),
        _tick('Bj candle bars', 'bjBars'),
        _tick('TSI value line', 'tsiValue'),
        _tick('TSI signal line', 'tsiSignal'),
        _tick('4-zone colour on signal line', 'sig4'),
        _tick('TSI fill (value vs signal)', 'tsiFill'),
        _color('TSI value line - curl up colour', 'cTsiBull'),
        _color('TSI value line - mid colour', 'cTsiMid'),
        _color('TSI value line - curl down colour', 'cTsiBear'),
        _head('Bottom deck - Z-score'),
        _tick('Z base (0 sigma) line', 'zBase'),
        _tick('Z-SMA 1', 'sma1'),
        _tick('Z-SMA 2', 'sma2'),
        _tick('Z-SMA UCL / LCL band', 'uclLcl'),
        _color('Bull area colour', 'cZBull'),
        _color('Bear area colour', 'cZBear'),
        _color('Z-SMA 1 colour', 'cSma1'),
        _color('Z-SMA 2 colour', 'cSma2'),
        _color('UCL band colour', 'cUcl'),
        _color('LCL band colour', 'cLcl'),
        _color('Fast EMA colour', 'cEmaFast'),
        _color('Slow EMA colour', 'cEmaSlow'),
        _color('Cloud colour: fast above slow', 'cEmaBull'),
        _color('Cloud colour: fast below slow', 'cEmaBear'),
        _color('BUY border colour', 'cZBuy'),
        _color('SELL border colour', 'cZSell'),
      ];

  @override
  Widget build(BuildContext context) {
    final mq = MediaQuery.of(context);
    final inputs = _inputs();
    // "TSI speed" is a Slow/Fast label but stored as a bool - swap the generic dropdown for a proper one.
    final speedIdx = 3;
    inputs[speedIdx] = Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(children: [
        const Expanded(child: Text('Select a speed (TSI)', style: TextStyle(color: _ink, fontSize: 14.5))),
        DropdownButton<String>(
          value: s.fast ? 'Fast' : 'Slow',
          style: const TextStyle(color: _ink, fontSize: 14.5),
          dropdownColor: Colors.white,
          underline: Container(height: 1, color: const Color(0xFFD5DAE3)),
          items: const [DropdownMenuItem(value: 'Slow', child: Text('Slow')), DropdownMenuItem(value: 'Fast', child: Text('Fast'))],
          onChanged: (v) => _set('fast', v == 'Fast'),
        ),
      ]),
    );
    return SizedBox(
      height: mq.size.height * 0.88,
      child: Padding(
        padding: EdgeInsets.only(left: 16, right: 16, top: 14, bottom: mq.viewPadding.bottom + 10),
        child: Column(children: [
          Row(children: [
            const Expanded(
              child: Text('Special Master new', style: TextStyle(color: _ink, fontSize: 19, fontWeight: FontWeight.w800)),
            ),
            IconButton(icon: const Icon(Icons.close, color: Colors.grey), onPressed: () => Navigator.pop(context)),
          ]),
          Row(children: [
            for (final e in const ['Inputs', 'Style'].asMap().entries)
              Padding(
                padding: const EdgeInsets.only(right: 22),
                child: GestureDetector(
                  onTap: () => setState(() => _tab = e.key),
                  child: Container(
                    padding: const EdgeInsets.only(bottom: 6),
                    decoration: BoxDecoration(
                      border: Border(bottom: BorderSide(color: _tab == e.key ? _ink : Colors.transparent, width: 3)),
                    ),
                    child: Text(e.value,
                        style: TextStyle(color: _tab == e.key ? _ink : Colors.grey, fontSize: 16, fontWeight: FontWeight.w700)),
                  ),
                ),
              ),
          ]),
          const Divider(height: 1),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.only(bottom: 12),
              children: _tab == 0 ? inputs : _style(),
            ),
          ),
          const Divider(height: 1),
          const SizedBox(height: 8),
          Row(children: [
            OutlinedButton(
              onPressed: () => setState(() {
                s = SmSettings.defaults();
                _rev++;
              }),
              style: OutlinedButton.styleFrom(foregroundColor: _ink, side: const BorderSide(color: Color(0xFFD5DAE3))),
              child: const Text('Reset'),
            ),
            const Spacer(),
            OutlinedButton(
              onPressed: () => Navigator.pop(context),
              style: OutlinedButton.styleFrom(foregroundColor: _ink, side: const BorderSide(color: _ink)),
              child: const Text('Cancel'),
            ),
            const SizedBox(width: 10),
            ElevatedButton(
              onPressed: () => Navigator.pop(context, s),
              style: ElevatedButton.styleFrom(backgroundColor: _ink, foregroundColor: Colors.white),
              child: const Text('Ok'),
            ),
          ]),
        ]),
      ),
    );
  }
}
