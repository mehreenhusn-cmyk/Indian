import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';

/// Ultra-Premium Geometric Owl Emblem with financial indicator geometry.
///
/// Can be used directly as a responsive UI widget:
/// ```dart
/// const OwlTerminalLogo(size: 80, glowing: true);
/// ```
/// Or exported as a high-resolution 512x512 PNG for app launcher icons:
/// ```dart
/// final pngBytes = await OwlTerminalLogo.toPngBytes(size: 512);
/// // file saving lives in owl_logo_export.dart (uses dart:io, so it stays out of this widget file)
/// ```
class OwlTerminalLogo extends StatelessWidget {
  final double size;
  final bool showBackground;
  final bool glowing;
  final Color? backgroundColor;

  const OwlTerminalLogo({
    super.key,
    this.size = 120.0,
    this.showBackground = true,
    this.glowing = true,
    this.backgroundColor,
  });

  /// Exports the custom canvas drawing directly into 32-bit PNG bytes.
  static Future<Uint8List> toPngBytes({
    int size = 512,
    bool withBackground = true,
    bool glowing = true,
  }) async {
    final recorder = ui.PictureRecorder();
    final canvas = Canvas(
      recorder,
      Rect.fromLTWH(0, 0, size.toDouble(), size.toDouble()),
    );

    final painter = OwlTerminalLogoPainter(
      showBackground: withBackground,
      glowing: glowing,
    );
    painter.paint(canvas, Size(size.toDouble(), size.toDouble()));

    final picture = recorder.endRecording();
    final image = await picture.toImage(size, size);
    final byteData = await image.toByteData(format: ui.ImageByteFormat.png);

    return byteData!.buffer.asUint8List();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        size: Size(size, size),
        painter: OwlTerminalLogoPainter(
          showBackground: showBackground,
          glowing: glowing,
          customBgColor: backgroundColor,
        ),
      ),
    );
  }
}

/// Canvas painter rendering the razor-sharp geometric Owl and trading indicators.
class OwlTerminalLogoPainter extends CustomPainter {
  final bool showBackground;
  final bool glowing;
  final Color? customBgColor;

  // Design Token Colors
  static const Color obsidianBase = Color(0xFF0B0E11);
  static const Color surfaceElevated = Color(0xFF161B22);
  static const Color borderDark = Color(0xFF242A32);
  static const Color electricCyan = Color(0xFF4C8DFF);
  static const Color neonCyan = Color(0xFF00E5FF);
  static const Color emeraldGreen = Color(0xFF0ECB81);
  static const Color mintAccent = Color(0xFF00F5A0);
  static const Color goldAccent = Color(0xFFF0B90B);

  const OwlTerminalLogoPainter({
    this.showBackground = true,
    this.glowing = true,
    this.customBgColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final double s = size.width < size.height ? size.width : size.height;
    final center = Offset(size.width / 2, size.height / 2);

    // 1. App Icon Squircle Base (Obsidian with Dual Glow Rim)
    if (showBackground) {
      _drawSquircleBackground(canvas, size, s, center);
    }

    // 2. Subtle Trading Grid and Trend Rays
    _drawTradingGrid(canvas, center, s);

    // 3. Faceted Geometric Owl Head & Chevrons
    _drawOwlFaceGeometry(canvas, center, s);

    // 4. Reticle Eyes & Candlestick Pupils
    _drawReticleEyes(canvas, center, s);

    // 5. Angular Metallic Beak & Breakeven Point
    _drawBeak(canvas, center, s);
  }

  void _drawSquircleBackground(
    Canvas canvas,
    Size size,
    double s,
    Offset center,
  ) {
    final rect = Rect.fromCenter(center: center, width: s, height: s);
    final rrect = RRect.fromRectAndRadius(rect, Radius.circular(s * 0.22));

    // Deep Obsidian Gradient Fill
    final bgPaint = Paint()
      ..shader = ui.Gradient.linear(
        rect.topLeft,
        rect.bottomRight,
        [
          customBgColor ?? surfaceElevated,
          customBgColor ?? obsidianBase,
        ],
      );
    canvas.drawRRect(rrect, bgPaint);

    // Subtle Radial Ambient Glow from center
    if (glowing) {
      final ambientGlow = Paint()
        ..shader = ui.Gradient.radial(
          Offset(center.dx, center.dy * 0.9),
          s * 0.55,
          [
            electricCyan.withOpacity(0.18),
            emeraldGreen.withOpacity(0.04),
            Colors.transparent,
          ],
          [0.0, 0.45, 1.0],
        );
      canvas.drawRRect(rrect, ambientGlow);
    }

    // Fine Rim Border (Dual Cyan -> Emerald Hairline)
    final rimPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.015
      ..shader = ui.Gradient.linear(
        rect.topLeft,
        rect.bottomRight,
        [
          electricCyan.withOpacity(0.85),
          borderDark,
          emeraldGreen.withOpacity(0.75),
        ],
        [0.0, 0.5, 1.0],
      );
    canvas.drawRRect(rrect, rimPaint);
  }

  void _drawTradingGrid(Canvas canvas, Offset c, double s) {
    final gridPaint = Paint()
      ..color = borderDark.withOpacity(0.35)
      ..strokeWidth = s * 0.003
      ..style = PaintingStyle.stroke;

    final double half = s * 0.38;
    // Faint vertical order-book grid lines
    canvas.drawLine(Offset(c.dx - half * 0.5, c.dy - half), Offset(c.dx - half * 0.5, c.dy + half), gridPaint);
    canvas.drawLine(Offset(c.dx + half * 0.5, c.dy - half), Offset(c.dx + half * 0.5, c.dy + half), gridPaint);

    // Dynamic 45-degree ascending trendline behind the emblem
    final trendPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.004
      ..shader = ui.Gradient.linear(
        Offset(c.dx - half, c.dy + half * 0.6),
        Offset(c.dx + half, c.dy - half * 0.6),
        [
          Colors.transparent,
          emeraldGreen.withOpacity(0.25),
          Colors.transparent,
        ],
        [0.0, 0.5, 1.0], // <--- FIX IS HERE: Added explicit stops for the 3 colors
      );
    canvas.drawLine(
      Offset(c.dx - half * 0.9, c.dy + half * 0.55),
      Offset(c.dx + half * 0.9, c.dy - half * 0.55),
      trendPaint,
    );
  }

  void _drawOwlFaceGeometry(Canvas canvas, Offset c, double s) {
    Offset pt(double x, double y) => Offset(c.dx + (x - 0.5) * s, c.dy + (y - 0.5) * s);

    // 1. Ear Candlestick Wicks (Horns)
    final wickPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.016
      ..strokeCap = StrokeCap.round
      ..color = neonCyan.withOpacity(0.7);

    // Left Wick
    canvas.drawLine(pt(0.22, 0.28), pt(0.18, 0.16), wickPaint);
    // Right Wick
    canvas.drawLine(pt(0.78, 0.28), pt(0.82, 0.16), wickPaint);

    // 2. Crown & Brow Ribs (Ascending Chevron)
    final browPath = Path()
      ..moveTo(pt(0.50, 0.30).dx, pt(0.50, 0.30).dy) // Center top dip
      ..lineTo(pt(0.22, 0.24).dx, pt(0.22, 0.24).dy) // Left ear tip
      ..lineTo(pt(0.32, 0.39).dx, pt(0.32, 0.39).dy) // Inner brow left
      ..lineTo(pt(0.50, 0.44).dx, pt(0.50, 0.44).dy) // Forehead center
      ..lineTo(pt(0.68, 0.39).dx, pt(0.68, 0.39).dy) // Inner brow right
      ..lineTo(pt(0.78, 0.24).dx, pt(0.78, 0.24).dy) // Right ear tip
      ..close();

    final browFill = Paint()
      ..style = PaintingStyle.fill
      ..shader = ui.Gradient.linear(
        pt(0.50, 0.20),
        pt(0.50, 0.45),
        [
          neonCyan.withOpacity(0.9),
          electricCyan.withOpacity(0.7),
        ],
      );

    if (glowing) {
      final glowPaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = s * 0.03
        ..color = electricCyan.withOpacity(0.25)
        ..maskFilter = MaskFilter.blur(BlurStyle.normal, s * 0.06);
      canvas.drawPath(browPath, glowPaint);
    }

    canvas.drawPath(browPath, browFill);

    // 3. Faceted Cheek Flanks (Outer Orderbook Wings)
    final leftCheek = Path()
      ..moveTo(pt(0.22, 0.24).dx, pt(0.22, 0.24).dy)
      ..lineTo(pt(0.15, 0.52).dx, pt(0.15, 0.52).dy)
      ..lineTo(pt(0.29, 0.70).dx, pt(0.29, 0.70).dy)
      ..lineTo(pt(0.40, 0.62).dx, pt(0.40, 0.62).dy)
      ..lineTo(pt(0.32, 0.39).dx, pt(0.32, 0.39).dy)
      ..close();

    final rightCheek = Path()
      ..moveTo(pt(0.78, 0.24).dx, pt(0.78, 0.24).dy)
      ..lineTo(pt(0.85, 0.52).dx, pt(0.85, 0.52).dy)
      ..lineTo(pt(0.71, 0.70).dx, pt(0.71, 0.70).dy)
      ..lineTo(pt(0.60, 0.62).dx, pt(0.60, 0.62).dy)
      ..lineTo(pt(0.68, 0.39).dx, pt(0.68, 0.39).dy)
      ..close();

    final cheekPaint = Paint()
      ..style = PaintingStyle.fill
      ..shader = ui.Gradient.linear(
        pt(0.15, 0.24),
        pt(0.85, 0.70),
        [
          const Color(0xFF1E2836),
          const Color(0xFF10161F),
        ],
      );

    canvas.drawPath(leftCheek, cheekPaint);
    canvas.drawPath(rightCheek, cheekPaint);

    final cheekStroke = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.008
      ..color = borderDark.withOpacity(0.9);

    canvas.drawPath(leftCheek, cheekStroke);
    canvas.drawPath(rightCheek, cheekStroke);

    // 4. Lower Chin Guard (V-Shield)
    final chinPath = Path()
      ..moveTo(pt(0.29, 0.70).dx, pt(0.29, 0.70).dy)
      ..lineTo(pt(0.50, 0.85).dx, pt(0.50, 0.85).dy) // Bottom tip
      ..lineTo(pt(0.71, 0.70).dx, pt(0.71, 0.70).dy)
      ..lineTo(pt(0.50, 0.74).dx, pt(0.50, 0.74).dy) // Inner notch
      ..close();

    final chinPaint = Paint()
      ..style = PaintingStyle.fill
      ..shader = ui.Gradient.linear(
        pt(0.50, 0.70),
        pt(0.50, 0.85),
        [
          emeraldGreen.withOpacity(0.55),
          mintAccent.withOpacity(0.15),
        ],
      );
    canvas.drawPath(chinPath, chinPaint);

    final chinBorder = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.012
      ..shader = ui.Gradient.linear(
        pt(0.29, 0.70),
        pt(0.71, 0.70),
        [
          emeraldGreen.withOpacity(0.9),
          mintAccent,
        ],
      );
    canvas.drawPath(chinPath, chinBorder);
  }

  void _drawReticleEyes(Canvas canvas, Offset c, double s) {
    Offset pt(double x, double y) => Offset(c.dx + (x - 0.5) * s, c.dy + (y - 0.5) * s);

    final double eyeR = s * 0.105;
    final leftCenter = pt(0.35, 0.505);
    final rightCenter = pt(0.65, 0.505);

    for (final eye in [leftCenter, rightCenter]) {
      // Background Eye Socket
      canvas.drawCircle(
        eye,
        eyeR,
        Paint()..color = const Color(0xFF07090C),
      );

      // Outer Angular Diamond Ring
      final diamondPath = Path()
        ..moveTo(eye.dx, eye.dy - eyeR)
        ..lineTo(eye.dx + eyeR, eye.dy)
        ..lineTo(eye.dx, eye.dy + eyeR)
        ..lineTo(eye.dx - eyeR, eye.dy)
        ..close();

      canvas.drawPath(
        diamondPath,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = s * 0.014
          ..color = electricCyan.withOpacity(0.65),
      );

      // Inner Glowing Emerald Reticle Target
      if (glowing) {
        canvas.drawCircle(
          eye,
          eyeR * 0.58,
          Paint()
            ..color = emeraldGreen.withOpacity(0.4)
            ..maskFilter = MaskFilter.blur(BlurStyle.normal, s * 0.045),
        );
      }

      // Emerald Candlestick Pupil (Vertical Diamond Pill)
      final pupilPath = Path()
        ..moveTo(eye.dx, eye.dy - eyeR * 0.55)
        ..lineTo(eye.dx + eyeR * 0.35, eye.dy)
        ..lineTo(eye.dx, eye.dy + eyeR * 0.55)
        ..lineTo(eye.dx - eyeR * 0.35, eye.dy)
        ..close();

      canvas.drawPath(
        pupilPath,
        Paint()
          ..style = PaintingStyle.fill
          ..shader = ui.Gradient.linear(
            Offset(eye.dx, eye.dy - eyeR * 0.55),
            Offset(eye.dx, eye.dy + eyeR * 0.55),
            [
              mintAccent,
              emeraldGreen,
            ],
          ),
      );

      // Core Specular Glint
      canvas.drawCircle(
        Offset(eye.dx - eyeR * 0.08, eye.dy - eyeR * 0.12),
        eyeR * 0.12,
        Paint()..color = Colors.white,
      );
    }
  }

  void _drawBeak(Canvas canvas, Offset c, double s) {
    Offset pt(double x, double y) => Offset(c.dx + (x - 0.5) * s, c.dy + (y - 0.5) * s);

    // Razor-faceted Downward Crystal Beak (two faceted halves for 3D bevel)
    final leftBeak = Path()
      ..moveTo(pt(0.50, 0.46).dx, pt(0.50, 0.46).dy)
      ..lineTo(pt(0.44, 0.56).dx, pt(0.44, 0.56).dy)
      ..lineTo(pt(0.50, 0.68).dx, pt(0.50, 0.68).dy)
      ..close();

    final rightBeak = Path()
      ..moveTo(pt(0.50, 0.46).dx, pt(0.50, 0.46).dy)
      ..lineTo(pt(0.56, 0.56).dx, pt(0.56, 0.56).dy)
      ..lineTo(pt(0.50, 0.68).dx, pt(0.50, 0.68).dy)
      ..close();

    // Left facet: Highlight cyan/emerald
    canvas.drawPath(
      leftBeak,
      Paint()
        ..style = PaintingStyle.fill
        ..shader = ui.Gradient.linear(
          pt(0.44, 0.46),
          pt(0.50, 0.68),
          [
            neonCyan,
            electricCyan,
          ],
        ),
    );

    // Right facet: Shadowed cyan/dark navy
    canvas.drawPath(
      rightBeak,
      Paint()
        ..style = PaintingStyle.fill
        ..shader = ui.Gradient.linear(
          pt(0.56, 0.46),
          pt(0.50, 0.68),
          [
            electricCyan.withOpacity(0.85),
            const Color(0xFF101B2E),
          ],
        ),
    );

    // Beak edge outlines
    final beakBorder = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = s * 0.008
      ..color = Colors.white.withOpacity(0.35);

    canvas.drawPath(leftBeak, beakBorder);
    canvas.drawPath(rightBeak, beakBorder);

    // Breakeven target pip in the beak center
    canvas.drawCircle(
      pt(0.50, 0.55),
      s * 0.016,
      Paint()..color = goldAccent,
    );
  }

  @override
  bool shouldRepaint(covariant OwlTerminalLogoPainter oldDelegate) {
    return oldDelegate.showBackground != showBackground ||
        oldDelegate.glowing != glowing ||
        oldDelegate.customBgColor != customBgColor;
  }
}
