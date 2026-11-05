import 'package:flutter/material.dart';

/// Part P-B: ONE own icon per bottom-bar tab, so the owner knows the tab from the picture alone.
///   0 Home = house, 1 Positions = candles, 2 Sniper = target rings, 3 Study Lab = flask, 4 More = four dots (drawn here: a 2 x 2 grid of dots).
/// Idle = outline, lit = filled. Material icons only (no new package, no SVG file), so nothing can fail to load. Dart NOT compiled.
class OwlNavIcon extends StatelessWidget {
  final int index;
  final bool lit;
  final Color color;
  final double size;

  const OwlNavIcon({super.key, required this.index, required this.lit, required this.color, this.size = 24});

  static const List<IconData> _off = [
    Icons.home_outlined,
    Icons.candlestick_chart_outlined,
    Icons.track_changes_outlined,
    Icons.science_outlined,
  ];

  static const List<IconData> _on = [
    Icons.home_rounded,
    Icons.candlestick_chart_rounded,
    Icons.track_changes_rounded,
    Icons.science_rounded,
  ];

  @override
  Widget build(BuildContext context) {
    if (index >= _off.length) {
      return CustomPaint(size: Size.square(size), painter: _DotsPainter(color: color, filled: lit));
    }
    return Icon(lit ? _on[index] : _off[index], size: size, color: color);
  }
}

/// The More icon: four round dots in a 2 x 2 grid. Outline when idle, solid when lit.
class _DotsPainter extends CustomPainter {
  final Color color;
  final bool filled;

  const _DotsPainter({required this.color, required this.filled});

  @override
  void paint(Canvas canvas, Size s) {
    final paint = Paint()
      ..color = color
      ..style = filled ? PaintingStyle.fill : PaintingStyle.stroke
      ..strokeWidth = 1.8
      ..isAntiAlias = true;
    final r = s.width * (filled ? 0.14 : 0.12);
    for (final dx in const [0.3, 0.7]) {
      for (final dy in const [0.3, 0.7]) {
        canvas.drawCircle(Offset(s.width * dx, s.height * dy), r, paint);
      }
    }
  }

  @override
  bool shouldRepaint(_DotsPainter old) => old.color != color || old.filled != filled;
}
