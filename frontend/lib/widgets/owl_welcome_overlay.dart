import 'dart:async';
import 'dart:io';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'owl_load_sequence.dart';

/// Wraps the app's real home screen and shows a short black and white
/// "OWL TERMINAL" boot screen on top of it when more than [gate] has passed
/// since it was last shown (default 12 hours).
///
/// Same constructor and same SharedPreferences key as before, so main.dart
/// does not change:
///   home: OwlWelcomeOverlay(prefs: prefs, child: const MainScreen()),
///
/// The loading bar is real (see OwlLoadSequence). The screen closes by itself
/// a moment after the bar is complete and the signature is typed.
/// [_maxDuration] is only a safety net. It is longer than the longest
/// possible loading, so it can no longer cut the screen before the name shows.
/// You can tap to skip after about 1.4 seconds. Always black, in any app theme.
class OwlWelcomeOverlay extends StatefulWidget {
  final SharedPreferences prefs;
  final Widget child;
  final Duration gate;

  const OwlWelcomeOverlay({
    super.key,
    required this.prefs,
    required this.child,
    this.gate = const Duration(hours: 12),
  });

  /// false when main.dart had to fall back to an in-memory store (the time of the last splash is then lost on every restart).
  static bool storeIsPersistent = true;

  /// Change this text when you ship a new app build: the welcome screen then shows once on the first start of that build
  /// (new install or update), and after that once every 12 hours.
  static const String buildId = '2026-10-25-plate5';

  static const _prefsKey = 'owl_welcome_last_shown_ms';
  static const Duration _maxDuration = Duration(seconds: 40);

  @override
  State<OwlWelcomeOverlay> createState() => _OwlWelcomeOverlayState();
}

class _OwlWelcomeOverlayState extends State<OwlWelcomeOverlay> with TickerProviderStateMixin {
  late final AnimationController _entrance;
  late final Animation<double> _fade;

  bool _showSplash = false;
  bool _canDismiss = false;
  Timer? _autoDismiss;
  Timer? _tapEnable;

  @override
  void initState() {
    super.initState();

    _entrance = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 450),
      reverseDuration: const Duration(milliseconds: 300),
    );
    _fade = CurvedAnimation(parent: _entrance, curve: Curves.easeOutCubic);

    _decide();
  }

  // The time of the last welcome is saved in a small FILE in the app's own folder (the settings plugin is not reliable on this phone).
  // File content: "<milliseconds>|<build id>". No file = fresh install = show. Other build id = new version = show. Older than 12 h = show.
  Future<File?> _stampFile() async {
    try {
      final dir = await getApplicationSupportDirectory();
      return File('${dir.path}/owl_welcome_stamp.txt');
    } catch (_) {
      return null;
    }
  }

  Future<void> _decide() async {
    final now = DateTime.now().millisecondsSinceEpoch;
    var lastShown = 0;
    var build = '';
    final f = await _stampFile();
    try {
      if (f != null && await f.exists()) {
        final parts = (await f.readAsString()).trim().split('|');
        lastShown = int.tryParse(parts.first) ?? 0;
        build = parts.length > 1 ? parts[1] : '';
      }
    } catch (_) {}
    if (lastShown == 0) {
      // file missing or unreadable: fall back to the settings value if that works on this phone
      try {
        lastShown = widget.prefs.getInt(OwlWelcomeOverlay._prefsKey) ?? 0;
      } catch (_) {}
    }
    final fresh = lastShown == 0 || build != OwlWelcomeOverlay.buildId || now - lastShown >= widget.gate.inMilliseconds;
    if (!fresh || !mounted) return;
    try {
      await f?.writeAsString('$now|${OwlWelcomeOverlay.buildId}');
    } catch (_) {}
    try {
      widget.prefs.setInt(OwlWelcomeOverlay._prefsKey, now);
    } catch (_) {}
    if (!mounted) return;
    setState(() => _showSplash = true);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      _entrance.forward();
    });
    // Guard against an accidental tap while the screen fades in.
    _tapEnable = Timer(const Duration(milliseconds: 1400), () {
      if (mounted) setState(() => _canDismiss = true);
    });
    _autoDismiss = Timer(OwlWelcomeOverlay._maxDuration, _dismiss);
  }

  void _dismiss() {
    if (!mounted || !_showSplash) return;
    HapticFeedback.lightImpact();
    _autoDismiss?.cancel();
    _tapEnable?.cancel();
    _entrance.reverse().then((_) {
      if (mounted) setState(() => _showSplash = false);
    });
  }

  @override
  void dispose() {
    _autoDismiss?.cancel();
    _tapEnable?.cancel();
    _entrance.dispose();
    super.dispose();
  }

  TextStyle _mono(double size, Color color, {FontWeight w = FontWeight.w600, double spacing = 1.0}) =>
      TextStyle(fontFamily: 'monospace', fontSize: size, fontWeight: w, letterSpacing: spacing, color: color);

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        if (_showSplash)
          Positioned.fill(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _canDismiss ? _dismiss : null,
              child: FadeTransition(
                opacity: _fade,
                child: Material(
                  color: Colors.black,
                  child: Stack(
                    children: [
                      // Futuristic dashboard picture behind the loading screen (assets/welcome_bg.jpg). If the file is
                      // ever missing, errorBuilder keeps the plain black screen.
                      Positioned.fill(
                        child: Image.asset('assets/welcome_bg.jpg', fit: BoxFit.cover, gaplessPlayback: true, errorBuilder: (_, __, ___) => const SizedBox.shrink()),
                      ),
                      // Dark layer over the picture: the bright parts of the picture used to swallow the white title.
                      Positioned.fill(
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            gradient: LinearGradient(
                              begin: Alignment.topCenter,
                              end: Alignment.bottomCenter,
                              colors: [Colors.black.withOpacity(0.50), Colors.black.withOpacity(0.32), Colors.black.withOpacity(0.64)],
                            ),
                          ),
                        ),
                      ),
                      // Copper CPU chip with circuit traces (AI / processor look).
                      const Positioned.fill(
                        child: RepaintBoundary(
                          child: CustomPaint(painter: _ChipPainter()),
                        ),
                      ),
                      const Positioned.fill(
                        child: RepaintBoundary(
                          child: CustomPaint(painter: _ScanlinePainter()),
                        ),
                      ),
                      SafeArea(
                        child: Center(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 28),
                            child: _content(context),
                          ),
                        ),
                      ),
                      if (_canDismiss)
                        Positioned(
                          left: 0,
                          right: 0,
                          bottom: 28,
                          child: SafeArea(
                            child: Center(
                              child: Text('TAP TO SKIP', style: _mono(10, const Color(0xFF9A7653), w: FontWeight.w700, spacing: 2.0)),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  Widget _content(BuildContext context) {
    return ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 420),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          ShaderMask(
            blendMode: BlendMode.srcIn,
            shaderCallback: (r) => const LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [Color(0xFFFFD9B0), Color(0xFFE59A5B), Color(0xFFB8672E)],
            ).createShader(r),
            child: Text(
              'OWL TERMINAL',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontFamily: 'Inter',
                fontSize: 30,
                fontWeight: FontWeight.w700,
                letterSpacing: 7,
                color: Colors.white,
                shadows: [Shadow(color: const Color(0xFFE59A5B).withOpacity(0.55), blurRadius: 18)],
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text('AUTONOMOUS TRADING SYSTEM', textAlign: TextAlign.center, style: _mono(10.5, const Color(0xFFD9A06B), spacing: 3.2)),
          const SizedBox(height: 6),
          Text('LOSSES TEACH. GREEN IS EARNED.', textAlign: TextAlign.center, style: _mono(9, const Color(0xFF9A7653), w: FontWeight.w700, spacing: 2.4)),
          const SizedBox(height: 18),
          Container(
            height: 1,
            decoration: BoxDecoration(
              gradient: LinearGradient(colors: [Colors.transparent, const Color(0xFFE59A5B).withOpacity(0.8), Colors.transparent]),
            ),
          ),
          const SizedBox(height: 22),
          OwlLoadSequence(
            // Bar complete and both names typed: close a moment later.
            onDone: () => Future.delayed(const Duration(milliseconds: 900), _dismiss),
          ),
        ],
      ),
    );
  }
}

/// A copper CPU chip in the middle with pins and circuit traces running to the screen edges. Painted once, no animation.
class _ChipPainter extends CustomPainter {
  const _ChipPainter();

  @override
  void paint(Canvas canvas, Size size) {
    const copper = Color(0xFFE59A5B);
    final c = Offset(size.width / 2, size.height * 0.42);
    final half = math.min(size.width, size.height) * 0.20;
    final chip = Rect.fromCenter(center: c, width: half * 2, height: half * 2);
    final line = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.1
      ..color = copper.withOpacity(0.28);
    final dot = Paint()..color = copper.withOpacity(0.45);
    // traces: from each pin, straight out, one right-angle turn, ends in a small via
    final rnd = math.Random(11);
    const pins = 7;
    for (var k = 0; k < pins; k++) {
      final t = (k + 1) / (pins + 1);
      final x = chip.left + chip.width * t;
      final y = chip.top + chip.height * t;
      for (final side in [0, 1, 2, 3]) {
        final start = side == 0 ? Offset(x, chip.top) : side == 1 ? Offset(x, chip.bottom) : side == 2 ? Offset(chip.left, y) : Offset(chip.right, y);
        final dir = side == 0 ? const Offset(0, -1) : side == 1 ? const Offset(0, 1) : side == 2 ? const Offset(-1, 0) : const Offset(1, 0);
        canvas.drawLine(start, start + dir * 9, Paint()..color = copper.withOpacity(0.5)..strokeWidth = 2);
        final len1 = 20.0 + rnd.nextInt(70);
        final mid = start + dir * (9 + len1);
        final turn = (dir.dx == 0 ? Offset(rnd.nextBool() ? 1.0 : -1.0, 0) : Offset(0, rnd.nextBool() ? 1.0 : -1.0)) * (14.0 + rnd.nextInt(60));
        final end = mid + turn;
        final path = Path()..moveTo(start.dx + dir.dx * 9, start.dy + dir.dy * 9)..lineTo(mid.dx, mid.dy)..lineTo(end.dx, end.dy);
        canvas.drawPath(path, line);
        canvas.drawCircle(end, 2.2, dot);
      }
    }
    // falling data (binary rain): faint copper columns, a few green ones
    final rainRnd = math.Random(5);
    for (var col = 0; col < 16; col++) {
      final x = size.width * (col + 0.5) / 16 + rainRnd.nextInt(10) - 5;
      final top = rainRnd.nextDouble() * size.height * 0.5;
      final green = col % 5 == 2;
      for (var k = 0; k < 14; k++) {
        final fade = (1 - k / 14.0);
        final dg = TextPainter(
          text: TextSpan(
              text: rainRnd.nextBool() ? '1' : '0',
              style: TextStyle(fontFamily: 'monospace', fontSize: 10, color: (green ? const Color(0xFF22C55E) : copper).withOpacity(0.05 + 0.22 * fade))),
          textDirection: TextDirection.ltr,
        )..layout();
        dg.paint(canvas, Offset(x, top + k * 13));
      }
    }
    // candle silhouette at the bottom: starts red (loss) and turns green (profit) from left to right
    final cr = math.Random(9);
    var price = size.height * 0.93;
    const cn = 34;
    final cw = size.width / cn;
    for (var k = 0; k < cn; k++) {
      final drift = (k < cn * 0.45 ? 1.2 : -2.1) + (cr.nextDouble() - 0.5) * 7;
      final o = price;
      price = (price + drift).clamp(size.height * 0.84, size.height * 0.96).toDouble();
      final col = (k + 0.5) / cn < 0.5 ? const Color(0xFFEF4444) : const Color(0xFF22C55E);
      final hi = math.min(o, price) - 3 - cr.nextDouble() * 5, lo = math.max(o, price) + 3 + cr.nextDouble() * 5;
      final cx = cw * (k + 0.5);
      canvas.drawLine(Offset(cx, hi), Offset(cx, lo), Paint()..color = col.withOpacity(0.22)..strokeWidth = 1);
      canvas.drawRect(Rect.fromLTRB(cx - cw * 0.28, math.min(o, price), cx + cw * 0.28, math.max(o, price) + 1.5), Paint()..color = col.withOpacity(0.28));
    }
    // HUD corner brackets
    final br = Paint()..style = PaintingStyle.stroke..strokeWidth = 1.4..color = copper.withOpacity(0.55);
    const m = 14.0, L = 22.0;
    canvas.drawPath(Path()..moveTo(m, m + L)..lineTo(m, m)..lineTo(m + L, m), br);
    canvas.drawPath(Path()..moveTo(size.width - m - L, m)..lineTo(size.width - m, m)..lineTo(size.width - m, m + L), br);
    canvas.drawPath(Path()..moveTo(m, size.height - m - L)..lineTo(m, size.height - m)..lineTo(m + L, size.height - m), br);
    canvas.drawPath(Path()..moveTo(size.width - m - L, size.height - m)..lineTo(size.width - m, size.height - m)..lineTo(size.width - m, size.height - m - L), br);
    // the chip body
    final body = RRect.fromRectAndRadius(chip, const Radius.circular(8));
    canvas.drawRRect(body, Paint()..color = const Color(0xFF1A0F08).withOpacity(0.85));
    canvas.drawRRect(body, Paint()..style = PaintingStyle.stroke..strokeWidth = 1.6..color = copper.withOpacity(0.6));
    final inner = RRect.fromRectAndRadius(chip.deflate(half * 0.28), const Radius.circular(4));
    canvas.drawRRect(inner, Paint()..style = PaintingStyle.stroke..strokeWidth = 1..color = copper.withOpacity(0.35));
    final tp = TextPainter(
      text: TextSpan(text: 'AI', style: TextStyle(fontFamily: 'Inter', fontSize: half * 0.55, fontWeight: FontWeight.w800, color: copper.withOpacity(0.35), letterSpacing: 2)),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, c - Offset(tp.width / 2, tp.height / 2));
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}

/// Very faint horizontal lines, like an old monitor. Painted once.
class _ScanlinePainter extends CustomPainter {
  const _ScanlinePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = Colors.white.withOpacity(0.03)
      ..strokeWidth = 1;
    for (double y = 0; y < size.height; y += 4) {
      canvas.drawLine(Offset(0, y), Offset(size.width, y), paint);
    }
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
