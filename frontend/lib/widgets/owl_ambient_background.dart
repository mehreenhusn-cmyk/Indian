import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Faint ambient glow behind the whole app (dark theme only).
///
/// Two soft radial gradients - accent-blue top-left, profit-green
/// bottom-right - on the true-black canvas. It is a single static
/// DecoratedBox (no blur, no animation), so it costs nothing per frame.
/// In the light theme it renders nothing.
class OwlAmbientBackground extends StatelessWidget {
  const OwlAmbientBackground({super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    if (p.brightness == Brightness.light) return const SizedBox.shrink();
    return IgnorePointer(
      child: Stack(
        fit: StackFit.expand,
        children: [
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(-1.0, -1.0),
                radius: 1.1,
                colors: [p.accent.withOpacity(0.10), Colors.transparent],
              ),
            ),
          ),
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(1.0, 1.0),
                radius: 1.0,
                colors: [p.profit.withOpacity(0.06), Colors.transparent],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
