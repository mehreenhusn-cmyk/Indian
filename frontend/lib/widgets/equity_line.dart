import 'package:flutter/material.dart';

/// Shared (Part 91b / X2): the running-net line of closed trades. The zero line (dashed), the line itself and a dot on the last point. No package, no animation.
class EquityLine extends StatelessWidget {
  final List<double> values;
  final Color line;
  final Color grid;
  final double height;
  const EquityLine({super.key, required this.values, required this.line, required this.grid, this.height = 140});

  @override
  Widget build(BuildContext context) =>
      SizedBox(height: height, width: double.infinity, child: CustomPaint(painter: EquityPainter(values, line, grid)));
}

/// The equity line: the zero line (dashed), the line itself and a dot on the last point. No package, no animation.
class EquityPainter extends CustomPainter {
  final List<double> v;
  final Color line;
  final Color grid;
  EquityPainter(this.v, this.line, this.grid);

  @override
  void paint(Canvas c, Size s) {
    var lo = v.reduce((a, b) => a < b ? a : b);
    var hi = v.reduce((a, b) => a > b ? a : b);
    if (lo > 0) lo = 0;
    if (hi < 0) hi = 0;
    if (hi - lo < 0.01) hi = lo + 1;
    double y(double x) => s.height - (x - lo) / (hi - lo) * s.height;
    final z = y(0);
    final gp = Paint()..color = grid..strokeWidth = 1;
    for (double x = 0; x < s.width; x += 8) {
      c.drawLine(Offset(x, z), Offset(x + 4, z), gp);
    }
    final path = Path();
    for (var i = 0; i < v.length; i++) {
      final o = Offset(i / (v.length - 1) * s.width, y(v[i]));
      if (i == 0) {
        path.moveTo(o.dx, o.dy);
      } else {
        path.lineTo(o.dx, o.dy);
      }
    }
    c.drawPath(path, Paint()..color = line..style = PaintingStyle.stroke..strokeWidth = 2.2..strokeJoin = StrokeJoin.round);
    c.drawCircle(Offset(s.width, y(v.last)), 4, Paint()..color = line);
  }

  @override
  bool shouldRepaint(EquityPainter o) => o.v != v || o.line != line;
}
