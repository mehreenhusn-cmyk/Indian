import 'package:flutter/material.dart';

/// Part 87: a small read-only chart for the Brain Trader screens. It draws exactly what the backend sends (candles, EMA50, SD middle, 2 SD bands, and optional ENTRY / STOP / TARGET lines).
/// It does no indicator maths. Own painter on purpose: the big candle_chart.dart is tied to the live chart screens. Dart NOT compiled (the owner's APK build is the proof).
class BtLine {
  final double price;
  final String label;
  final Color color;
  const BtLine(this.price, this.label, this.color);
}

class BtMiniChart extends StatelessWidget {
  final Map<String, dynamic> chart;
  final List<BtLine> lines;
  final double height;
  final Color up;
  final Color down;
  final Color ema;
  final Color band;
  final Color text;

  const BtMiniChart({super.key, required this.chart, this.lines = const [], this.height = 230, required this.up, required this.down, required this.ema, required this.band, required this.text});

  @override
  Widget build(BuildContext context) {
    final candles = chart['candles'] is List ? (chart['candles'] as List) : const [];
    if (candles.isEmpty) return SizedBox(height: height, child: Center(child: Text('No candles', style: TextStyle(color: text))));
    return SizedBox(height: height, width: double.infinity, child: CustomPaint(painter: _P(chart, lines, up, down, ema, band, text)));
  }
}

class _P extends CustomPainter {
  final Map<String, dynamic> chart;
  final List<BtLine> lines;
  final Color up, down, ema, band, text;
  _P(this.chart, this.lines, this.up, this.down, this.ema, this.band, this.text);

  List<double?> _arr(String k) => chart[k] is List ? [for (final e in (chart[k] as List)) e is num ? e.toDouble() : null] : <double?>[];

  @override
  void paint(Canvas canvas, Size size) {
    final cs = [for (final c in (chart['candles'] as List)) [for (final v in (c as List)) (v as num).toDouble()]];
    final n = cs.length;
    var lo = double.infinity, hi = -double.infinity;
    for (final c in cs) {
      if (c[3] < lo) lo = c[3];
      if (c[2] > hi) hi = c[2];
    }
    for (final l in lines) {
      if (l.price < lo) lo = l.price;
      if (l.price > hi) hi = l.price;
    }
    final pad = (hi - lo) * 0.06 + 1e-12;
    lo -= pad;
    hi += pad;
    const rightPad = 46.0;
    final w = size.width - rightPad, h = size.height;
    double x(int i) => (i + 0.5) / n * w;
    double y(double v) => h - (v - lo) / (hi - lo) * h;
    void series(String k, Color c, double sw) {
      final a = _arr(k);
      final path = Path();
      var started = false;
      for (var i = 0; i < a.length && i < n; i++) {
        final v = a[i];
        if (v == null || v < lo || v > hi) {
          started = false;
          continue;
        }
        if (!started) {
          path.moveTo(x(i), y(v));
          started = true;
        } else {
          path.lineTo(x(i), y(v));
        }
      }
      canvas.drawPath(path, Paint()..color = c..style = PaintingStyle.stroke..strokeWidth = sw);
    }

    series('up2', band, 1);
    series('lo2', band, 1);
    series('mid', band.withOpacity(0.7), 1);
    series('ema50', ema, 1.6);
    final bw = (w / n * 0.62).clamp(1.0, 9.0);
    for (var i = 0; i < n; i++) {
      final c = cs[i];
      final col = c[4] >= c[1] ? up : down;
      final p = Paint()..color = col..strokeWidth = 1;
      canvas.drawLine(Offset(x(i), y(c[2])), Offset(x(i), y(c[3])), p);
      final top = y(c[4] >= c[1] ? c[4] : c[1]), bot = y(c[4] >= c[1] ? c[1] : c[4]);
      canvas.drawRect(Rect.fromLTRB(x(i) - bw / 2, top, x(i) + bw / 2, bot < top + 1 ? top + 1 : bot), Paint()..color = col);
    }
    for (final l in lines) {
      final yy = y(l.price);
      canvas.drawLine(Offset(0, yy), Offset(w, yy), Paint()..color = l.color..strokeWidth = 1.2);
      final tp = TextPainter(text: TextSpan(text: l.label, style: TextStyle(fontSize: 9.5, fontWeight: FontWeight.w700, color: l.color)), textDirection: TextDirection.ltr)..layout();
      tp.paint(canvas, Offset(w + 3, (yy - tp.height / 2).clamp(0.0, h - tp.height)));
    }
  }

  @override
  bool shouldRepaint(covariant _P old) => old.chart != chart || old.lines != lines;
}
