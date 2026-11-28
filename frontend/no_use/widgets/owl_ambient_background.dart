import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Full-screen "heavy terminal" wallpaper behind the whole app (dark theme only).
///
/// One pre-made picture (assets/bg_terminal.jpg: code + earth at the top, a CPU
/// chip with orange glow in the middle, a trading room at the bottom) with a
/// dark layer on top so text stays easy to read. Static picture, no blur, no
/// animation, so it costs nothing per frame. In the light theme it renders
/// nothing (clean white app).
///
/// To make the picture stronger or weaker, change the three numbers in [_scrim]
/// (0.0 = picture fully visible, 1.0 = fully black).
class OwlAmbientBackground extends StatelessWidget {
  const OwlAmbientBackground({super.key});

  static const List<double> _scrim = [0.40, 0.48, 0.58]; // top, middle, bottom

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (p.brightness == Brightness.light) return const SizedBox.shrink();
    return IgnorePointer(
      child: RepaintBoundary(
        child: Stack(
          fit: StackFit.expand,
          children: [
            Image.asset(
              'assets/bg_terminal.jpg',
              fit: BoxFit.cover,
              cacheWidth: 720,
              gaplessPlayback: true,
              filterQuality: FilterQuality.low,
              errorBuilder: (_, __, ___) => const SizedBox.shrink(),
            ),
            DecoratedBox(
              decoration: BoxDecoration(
                gradient: LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [
                    Colors.black.withOpacity(_scrim[0]),
                    Colors.black.withOpacity(_scrim[1]),
                    Colors.black.withOpacity(_scrim[2]),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
