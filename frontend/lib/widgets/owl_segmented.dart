import 'package:flutter/material.dart';
import '../theme/app_motion2.dart';
import '../theme/app_theme.dart';

/// Part P-C: a SLIDING segmented switch (used for CRYPTO / INDIA at the top). One thumb slides under the word in 250 ms (ease-out), its colour fades to the colour of the chosen side.
/// Tap a side, or swipe across the control. Track = soft fill + ONE hairline border (no heavy coloured border). Light haptic on a real change. Text colour follows the thumb. Dart NOT compiled.
class OwlSegmented extends StatelessWidget {
  final List<String> labels;
  final int index;
  final ValueChanged<int> onChanged;
  final List<Color> colors; // thumb colour per side
  final List<Color> textOn; // text colour on the thumb per side
  final double width;
  final double height;

  const OwlSegmented({
    super.key,
    required this.labels,
    required this.index,
    required this.onChanged,
    required this.colors,
    required this.textOn,
    this.width = 120,
    this.height = 28,
  });

  void _pick(int i) {
    if (i < 0 || i >= labels.length || i == index) return;
    AppHaptics.light();
    onChanged(i);
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final n = labels.length;
    final c = colors[index];
    final r = height / 2;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      // a swipe across the switch moves one side (left = next, right = previous)
      onHorizontalDragEnd: (d) {
        final v = d.primaryVelocity ?? 0;
        if (v.abs() < 200) return;
        _pick(v < 0 ? index + 1 : index - 1);
      },
      child: Container(
        width: width,
        height: height,
        padding: const EdgeInsets.all(2),
        decoration: BoxDecoration(color: p.surfaceHigher, borderRadius: BorderRadius.circular(r), border: Border.all(color: p.border, width: 1)),
        child: Stack(children: [
          AnimatedAlign(
            duration: OwlMotion.slide,
            curve: OwlMotion.smooth,
            alignment: Alignment(n == 1 ? 0 : -1 + 2 * index / (n - 1), 0),
            child: FractionallySizedBox(
              widthFactor: 1 / n,
              heightFactor: 1,
              child: AnimatedContainer(
                duration: OwlMotion.slide,
                curve: OwlMotion.smooth,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(r - 2),
                  gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [c, Color.lerp(c, p.purple, 0.25)!]),
                ),
              ),
            ),
          ),
          Row(children: [
            for (var i = 0; i < n; i++)
              Expanded(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => _pick(i),
                  child: Center(
                    child: AnimatedDefaultTextStyle(
                      duration: OwlMotion.slide,
                      style: TextStyle(color: i == index ? textOn[i] : p.textSecondary, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.8),
                      child: Text(labels[i], maxLines: 1),
                    ),
                  ),
                ),
              ),
          ]),
        ]),
      ),
    );
  }
}
