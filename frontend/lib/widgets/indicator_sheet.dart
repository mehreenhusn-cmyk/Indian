import 'dart:math' as math;
import 'package:flutter/material.dart';

/// TradingView-style indicator settings sheet (full height, scrollable, Inputs / Style / Visibility tabs).
/// Generic: the caller owns an immutable settings object T and describes each tab with a builder.
/// DISPLAY ONLY - nothing here touches the bot, signals or backend.

const kShInk = Color(0xFF10141C);
const kShGrey = Color(0xFF8A93A3);
const kShLine = Color(0xFFD5DAE3);

/// One tab ("Inputs", "Style", "Visibility"). [build] returns the rows; call [set] with a changed copy of T.
class IndicatorTab<T> {
  final String title;
  final List<Widget> Function(T s, ValueChanged<T> set) build;
  const IndicatorTab(this.title, this.build);
}

/// Opens the sheet. Returns the new settings when the user taps Ok, null on Cancel / close.
Future<T?> showIndicatorSheet<T>(
  BuildContext context, {
  required String title,
  required T initial,
  required T defaults,
  required List<IndicatorTab<T>> tabs,
}) {
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
    builder: (_) => _IndicatorSheet<T>(title: title, initial: initial, defaults: defaults, tabs: tabs),
  );
}

class _SheetScope extends InheritedWidget {
  final int rev; // bumps on Reset so number fields rebuild with the new text
  const _SheetScope({required this.rev, required super.child});
  static int of(BuildContext c) => c.dependOnInheritedWidgetOfExactType<_SheetScope>()?.rev ?? 0;
  @override
  bool updateShouldNotify(_SheetScope old) => old.rev != rev;
}

class _IndicatorSheet<T> extends StatefulWidget {
  final String title;
  final T initial;
  final T defaults;
  final List<IndicatorTab<T>> tabs;
  const _IndicatorSheet({required this.title, required this.initial, required this.defaults, required this.tabs});

  @override
  State<_IndicatorSheet<T>> createState() => _IndicatorSheetState<T>();
}

class _IndicatorSheetState<T> extends State<_IndicatorSheet<T>> {
  late T s = widget.initial;
  int tab = 0;
  int rev = 0;

  @override
  Widget build(BuildContext context) {
    final rows = widget.tabs[tab].build(s, (n) => setState(() => s = n));
    return _SheetScope(
      rev: rev,
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.94,
        child: Padding(
          padding: EdgeInsets.fromLTRB(16, 12, 16, 10 + MediaQuery.of(context).viewInsets.bottom),
          child: Column(children: [
            Row(children: [
              Expanded(
                child: Text(widget.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: kShInk, fontSize: 21, fontWeight: FontWeight.w800)),
              ),
              IconButton(icon: const Icon(Icons.close, color: kShInk), onPressed: () => Navigator.pop(context)),
            ]),
            Row(children: [
              for (int i = 0; i < widget.tabs.length; i++)
                Padding(
                  padding: const EdgeInsets.only(right: 22),
                  child: GestureDetector(
                    behavior: HitTestBehavior.opaque,
                    onTap: () => setState(() => tab = i),
                    child: Column(children: [
                      Text(widget.tabs[i].title,
                          style: TextStyle(
                              color: tab == i ? kShInk : kShGrey, fontSize: 17, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 5),
                      Container(
                          height: 3,
                          width: 56,
                          decoration: BoxDecoration(
                              color: tab == i ? kShInk : Colors.transparent, borderRadius: BorderRadius.circular(2))),
                    ]),
                  ),
                ),
            ]),
            const Divider(height: 1, color: kShLine),
            Expanded(
              child: ListView(
                key: ValueKey('tab$tab'),
                padding: const EdgeInsets.only(bottom: 24),
                children: rows,
              ),
            ),
            const Divider(height: 1, color: kShLine),
            const SizedBox(height: 8),
            Row(children: [
              // "..." = defaults menu, like TradingView
              PopupMenuButton<String>(
                tooltip: 'Defaults',
                onSelected: (_) => setState(() {
                  s = widget.defaults;
                  rev++;
                }),
                itemBuilder: (_) => const [PopupMenuItem(value: 'reset', child: Text('Reset settings'))],
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
                  decoration: BoxDecoration(
                      border: Border.all(color: kShLine, width: 1.5), borderRadius: BorderRadius.circular(14)),
                  child: const Icon(Icons.more_horiz, color: kShInk),
                ),
              ),
              const Spacer(),
              OutlinedButton(
                style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: kShInk, width: 1.5),
                    padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                onPressed: () => Navigator.pop(context),
                child: const Text('Cancel', style: TextStyle(color: kShInk, fontSize: 16, fontWeight: FontWeight.w700)),
              ),
              const SizedBox(width: 10),
              FilledButton(
                style: FilledButton.styleFrom(
                    backgroundColor: kShInk,
                    padding: const EdgeInsets.symmetric(horizontal: 30, vertical: 14),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                onPressed: () => Navigator.pop(context, s),
                child: const Text('Ok', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
              ),
            ]),
          ]),
        ),
      ),
    );
  }
}

// ------------------------------------------------------------------------------------------------ rows

/// Grey section title, e.g. "SD BANDS".
class ShHeader extends StatelessWidget {
  final String text;
  const ShHeader(this.text, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(top: 18, bottom: 4),
        child: Text(text.toUpperCase(),
            style: const TextStyle(color: kShGrey, fontSize: 12, fontWeight: FontWeight.w700, letterSpacing: 0.5)),
      );
}

/// Checkbox row.
class ShCheck extends StatelessWidget {
  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;
  const ShCheck(this.label, this.value, this.onChanged, {super.key});
  @override
  Widget build(BuildContext context) => InkWell(
        onTap: () => onChanged(!value),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(children: [
            Checkbox(
                value: value,
                onChanged: (x) => onChanged(x == true),
                activeColor: kShInk,
                visualDensity: VisualDensity.compact),
            Expanded(child: Text(label, style: const TextStyle(color: kShInk, fontSize: 16))),
          ]),
        ),
      );
}

/// Number box row (int or decimal). Ignores half-typed or out-of-range text.
class ShNumber extends StatelessWidget {
  final String label;
  final String id; // unique within the tab
  final num value;
  final num min;
  final num max;
  final ValueChanged<num> onChanged;
  final bool isInt;
  const ShNumber(this.label, this.id, this.value, this.min, this.max, this.onChanged, {this.isInt = true, super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(color: kShInk, fontSize: 16))),
          SizedBox(
            width: 104,
            child: TextFormField(
              key: ValueKey('$id|${_SheetScope.of(context)}'),
              initialValue: (isInt || value == value.roundToDouble()) ? value.round().toString() : value.toString(),
              keyboardType: TextInputType.numberWithOptions(decimal: true, signed: min < 0),
              style: const TextStyle(color: kShInk, fontSize: 16),
              decoration: InputDecoration(
                isDense: true,
                contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: kShLine)),
              ),
              onChanged: (t) {
                final p = double.tryParse(t.trim());
                if (p == null || p < min || p > max) return;
                onChanged(isInt ? p.round() : p);
              },
            ),
          ),
        ]),
      );
}

/// Drop-down row (e.g. "Fast / Slow").
class ShDrop<V> extends StatelessWidget {
  final String label;
  final V value;
  final Map<V, String> items;
  final ValueChanged<V> onChanged;
  const ShDrop(this.label, this.value, this.items, this.onChanged, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(color: kShInk, fontSize: 16))),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            decoration: BoxDecoration(border: Border.all(color: kShLine), borderRadius: BorderRadius.circular(12)),
            child: DropdownButton<V>(
              value: value,
              underline: const SizedBox.shrink(),
              style: const TextStyle(color: kShInk, fontSize: 16),
              items: [for (final e in items.entries) DropdownMenuItem<V>(value: e.key, child: Text(e.value))],
              onChanged: (v) {
                if (v != null) onChanged(v);
              },
            ),
          ),
        ]),
      );
}

/// Colour row (Inputs-tab style): label + one swatch that opens the colour + opacity picker.
class ShColor extends StatelessWidget {
  final String label;
  final int argb;
  final ValueChanged<int> onChanged;
  const ShColor(this.label, this.argb, this.onChanged, {super.key});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(children: [
          Expanded(child: Text(label, style: const TextStyle(color: kShInk, fontSize: 16))),
          ShSwatch(argb, onChanged),
        ]),
      );
}

/// Style-tab row: checkbox + colour / thickness / line-style buttons (dash: 0 solid, 1 dashed, 2 dotted).
class ShStyleRow extends StatelessWidget {
  final String label;
  final bool on;
  final ValueChanged<bool> onToggle;
  final int argb;
  final ValueChanged<int> onColor;
  final int width;
  final ValueChanged<int> onWidth;
  final int dash;
  final ValueChanged<int> onDash;
  const ShStyleRow({
    required this.label,
    required this.on,
    required this.onToggle,
    required this.argb,
    required this.onColor,
    required this.width,
    required this.onWidth,
    required this.dash,
    required this.onDash,
    super.key,
  });
  @override
  Widget build(BuildContext context) => Opacity(
        opacity: on ? 1 : 0.55,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Row(children: [
            Expanded(
              child: InkWell(
                onTap: () => onToggle(!on),
                child: Row(children: [
                  Checkbox(
                      value: on,
                      onChanged: (x) => onToggle(x == true),
                      activeColor: kShInk,
                      visualDensity: VisualDensity.compact),
                  Expanded(child: Text(label, style: const TextStyle(color: kShInk, fontSize: 16))),
                ]),
              ),
            ),
            ShSwatch(argb, onColor),
            const SizedBox(width: 8),
            PopupMenuButton<int>(
              onSelected: onWidth,
              itemBuilder: (_) => [
                for (final w in [1, 2, 3, 4])
                  PopupMenuItem(value: w, child: Row(children: [Text('$w px  '), Expanded(child: _LinePreview(dash: 0, width: w.toDouble(), color: kShInk))])),
              ],
              child: _Btn(child: _LinePreview(dash: 0, width: width.toDouble(), color: kShInk)),
            ),
            const SizedBox(width: 8),
            PopupMenuButton<int>(
              onSelected: onDash,
              itemBuilder: (_) => [
                for (final d in [0, 1, 2])
                  PopupMenuItem(value: d, child: SizedBox(width: 110, child: _LinePreview(dash: d, width: 2, color: kShInk))),
              ],
              child: _Btn(child: _LinePreview(dash: dash, width: 2, color: kShInk)),
            ),
          ]),
        ),
      );
}

class _Btn extends StatelessWidget {
  final Widget child;
  const _Btn({required this.child});
  @override
  Widget build(BuildContext context) => Container(
        width: 52,
        height: 40,
        padding: const EdgeInsets.symmetric(horizontal: 9),
        decoration: BoxDecoration(border: Border.all(color: kShLine, width: 1.5), borderRadius: BorderRadius.circular(12)),
        child: child,
      );
}

class _LinePreview extends StatelessWidget {
  final int dash;
  final double width;
  final Color color;
  const _LinePreview({required this.dash, required this.width, required this.color});
  @override
  Widget build(BuildContext context) => SizedBox(height: 24, child: CustomPaint(painter: _LinePainter(dash, width, color)));
}

class _LinePainter extends CustomPainter {
  final int dash;
  final double width;
  final Color color;
  _LinePainter(this.dash, this.width, this.color);
  @override
  void paint(Canvas c, Size s) {
    final p = Paint()
      ..color = color
      ..strokeWidth = width
      ..strokeCap = StrokeCap.round;
    final y = s.height / 2;
    if (dash == 0) {
      c.drawLine(Offset(0, y), Offset(s.width, y), p);
      return;
    }
    final seg = dash == 1 ? 7.0 : 1.5;
    const gap = 5.0;
    for (double x = 0; x < s.width; x += seg + gap) {
      c.drawLine(Offset(x, y), Offset(math.min(x + seg, s.width), y), p);
    }
  }

  @override
  bool shouldRepaint(_LinePainter o) => o.dash != dash || o.width != width || o.color != color;
}

// ------------------------------------------------------------------------------- colour + opacity picker

/// Small colour square (checkerboard behind it so transparency is visible). Tap = open the picker.
class ShSwatch extends StatelessWidget {
  final int argb;
  final ValueChanged<int> onChanged;
  const ShSwatch(this.argb, this.onChanged, {super.key});
  @override
  Widget build(BuildContext context) => GestureDetector(
        onTap: () async {
          final r = await showColorOpacityPicker(context, argb);
          if (r != null) onChanged(r);
        },
        child: Container(
          width: 52,
          height: 40,
          padding: const EdgeInsets.all(7),
          decoration: BoxDecoration(border: Border.all(color: kShLine, width: 1.5), borderRadius: BorderRadius.circular(12)),
          child: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: CustomPaint(painter: _CheckerPainter(Color(argb))),
          ),
        ),
      );
}

class _CheckerPainter extends CustomPainter {
  final Color color;
  _CheckerPainter(this.color);
  @override
  void paint(Canvas c, Size s) {
    const n = 5.0;
    final a = Paint()..color = const Color(0xFFFFFFFF);
    final b = Paint()..color = const Color(0xFFB8BDC7);
    for (int i = 0; i * n < s.width; i++) {
      for (int j = 0; j * n < s.height; j++) {
        c.drawRect(Rect.fromLTWH(i * n, j * n, n, n), (i + j).isEven ? a : b);
      }
    }
    c.drawRect(Offset.zero & s, Paint()..color = color);
  }

  @override
  bool shouldRepaint(_CheckerPainter o) => o.color != color;
}

int _mix(int rgb, int other, double t) {
  int ch(int sh) => (((rgb >> sh) & 0xFF) * (1 - t) + ((other >> sh) & 0xFF) * t).round();
  return (ch(16) << 16) | (ch(8) << 8) | ch(0);
}

List<int> _buildPalette() {
  const grays = [0xFFFFFF, 0xD9D9D9, 0xB3B3B3, 0x999999, 0x808080, 0x666666, 0x454545, 0x222222, 0x0A0A0A, 0x000000];
  const bright = [0xF23645, 0xFF9800, 0xFFEB3B, 0x4CAF50, 0x089981, 0x00BCD4, 0x2962FF, 0x673AB7, 0x9C27B0, 0xE91E63];
  return [
    ...grays,
    ...bright,
    for (final c in bright) _mix(c, 0xFFFFFF, 0.78),
    for (final c in bright) _mix(c, 0xFFFFFF, 0.50),
    for (final c in bright) _mix(c, 0x000000, 0.35),
  ];
}

final List<int> _kPalette = _buildPalette();

/// TradingView-like picker: colour grid + opacity slider. Returns ARGB (alpha = opacity) or null on cancel.
Future<int?> showColorOpacityPicker(BuildContext context, int argb) {
  int rgb = argb & 0xFFFFFF;
  double op = ((argb >> 24) & 0xFF) / 255.0 * 100.0;
  return showDialog<int>(
    context: context,
    builder: (ctx) => StatefulBuilder(builder: (ctx, setS) {
      final cur = ((op / 100.0 * 255).round() << 24) | rgb;
      return AlertDialog(
        backgroundColor: Colors.white,
        insetPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 24),
        contentPadding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
        content: SizedBox(
          width: 340,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              Wrap(spacing: 6, runSpacing: 6, children: [
                for (final c in _kPalette)
                  GestureDetector(
                    onTap: () => setS(() => rgb = c),
                    child: Container(
                      width: 26,
                      height: 26,
                      decoration: BoxDecoration(
                        color: Color(0xFF000000 | c),
                        borderRadius: BorderRadius.circular(6),
                        border: Border.all(color: rgb == c ? const Color(0xFF2962FF) : kShLine, width: rgb == c ? 3 : 1),
                      ),
                    ),
                  ),
              ]),
              const SizedBox(height: 14),
              const Text('Opacity', style: TextStyle(color: kShGrey, fontSize: 14)),
              Row(children: [
                Expanded(
                  child: Slider(
                    value: op.clamp(0.0, 100.0),
                    min: 0,
                    max: 100,
                    divisions: 100,
                    activeColor: Color(0xFF000000 | rgb),
                    onChanged: (v) => setS(() => op = v),
                  ),
                ),
                SizedBox(width: 48, child: Text('${op.round()}%', style: const TextStyle(color: kShInk, fontSize: 15))),
              ]),
              Container(height: 22, decoration: BoxDecoration(borderRadius: BorderRadius.circular(6)), child: ClipRRect(borderRadius: BorderRadius.circular(6), child: CustomPaint(painter: _CheckerPainter(Color(cur)), size: const Size(double.infinity, 22)))),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel', style: TextStyle(color: kShInk))),
          FilledButton(
              style: FilledButton.styleFrom(backgroundColor: kShInk),
              onPressed: () => Navigator.pop(ctx, cur),
              child: const Text('Ok')),
        ],
      );
    }),
  );
}

// ------------------------------------------------------------------------------------ Visibility tab

/// Timeframes the app offers; the user can hide an indicator on any of them (TradingView "Visibility" tab).
const kShTimeframes = ['1m', '3m', '5m', '15m', '1h'];

/// Visibility rows: one checkbox per timeframe. [hidden] holds the timeframes where the indicator is OFF.
List<Widget> shVisibilityRows(Set<String> hidden, ValueChanged<Set<String>> onChanged) => [
      const ShHeader('Show on timeframes'),
      for (final tf in kShTimeframes)
        ShCheck(tf, !hidden.contains(tf), (v) {
          final n = {...hidden};
          if (v) {
            n.remove(tf);
          } else {
            n.add(tf);
          }
          onChanged(n);
        }),
    ];
