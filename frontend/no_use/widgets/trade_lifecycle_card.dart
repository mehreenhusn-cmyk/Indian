import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// PHASE 4 - TRADE LIFECYCLE PROGRESS NEEDLE.
///
/// Clean horizontal price track for an open position card:
///   Left:   Stop Loss   (#FF3B69)
///   Center: Entry       (#64748B)
///   Right:  TP1..TP4    (#00E676)
///   A moving dot tracks the real-time LTP along the track.
///
/// Unlike a raw price-value mapping (which flips left/right on a SELL,
/// since SL > entry there), every marker's x-position is driven by its
/// PATH ORDER (SL -> Entry -> TP1 -> TP2 -> TP3 -> TP4), evenly spaced -
/// a schematic lifecycle diagram, not a literal price axis. Missing TP
/// levels (percent-mode trades often only have TP1/TP2) are simply
/// skipped, and the remaining markers reflow into the freed space.
///
/// The live dot's position is then interpolated using REAL price
/// distances within whichever segment the current LTP actually falls in,
/// so it visibly creeps toward the next marker rather than only jumping
/// between fixed stops.
class TradeLifecycleTrack extends StatelessWidget {
  final double sl;
  final double entry;
  final Map<int, double?> tpLevels; // 1..4 -> price (nulls skipped)
  final double? ltp;
  final bool isLong;

  static const Color slColor = Color(0xFFFF3B69);
  static const Color entryColor = Color(0xFF64748B);
  static const Color tpColor = Color(0xFF00E676);

  const TradeLifecycleTrack({
    super.key,
    required this.sl,
    required this.entry,
    required this.tpLevels,
    required this.ltp,
    required this.isLong,
  });

  @override
  Widget build(BuildContext context) {
    // Ordered markers along the path: SL, Entry, then whichever TP1..4 are
    // actually set on this position, in level order.
    final markers = <_Marker>[
      _Marker('SL', sl, slColor),
      _Marker('Entry', entry, entryColor),
    ];
    for (final level in [1, 2, 3, 4]) {
      final price = tpLevels[level];
      if (price != null) markers.add(_Marker('TP$level', price, tpColor));
    }
    if (markers.length < 2) return const SizedBox.shrink();

    final n = markers.length;
    final slots = List<double>.generate(n, (i) => n == 1 ? 0.0 : i / (n - 1));

    // Locate the live dot: which segment [i, i+1] the LTP currently falls
    // in (walking the path in SL->...->TP4 order, using isLong to decide
    // which direction along that path counts as "progress"), then
    // interpolate its fraction within that segment's slot span using real
    // price distances.
    double? dotFrac;
    Color dotColor = entryColor;
    if (ltp != null) {
      bool better(double a, double b) => isLong ? a >= b : a <= b;
      int seg = 0;
      for (int i = 0; i < n - 1; i++) {
        if (better(ltp!, markers[i].price)) seg = i;
      }
      final a = markers[seg];
      final b = markers[seg + 1];
      final span = b.price - a.price;
      final t = span == 0 ? 0.0 : ((ltp! - a.price) / span).clamp(0.0, 1.0);
      dotFrac = slots[seg] + (slots[seg + 1] - slots[seg]) * t;
      dotColor = (isLong ? ltp! >= entry : ltp! <= entry) ? tpColor : slColor;
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final width = constraints.maxWidth;
        return SizedBox(
          height: 40,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              // Base track
              Positioned(
                top: 17,
                left: 0,
                right: 0,
                child: Container(
                  height: 4,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(2),
                    gradient: LinearGradient(
                      colors: [slColor.withOpacity(0.7), entryColor.withOpacity(0.7), tpColor.withOpacity(0.8)],
                    ),
                  ),
                ),
              ),
              // Static markers + labels
              for (int i = 0; i < n; i++)
                Positioned(
                  left: (slots[i] * width - 16).clamp(0.0, width - 32),
                  top: 0,
                  width: 32,
                  child: Column(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: markers[i].color,
                          border: Border.all(color: Colors.black.withOpacity(0.3), width: 1),
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        markers[i].label,
                        textAlign: TextAlign.center,
                        style: TextStyle(color: markers[i].color, fontSize: 9, fontWeight: FontWeight.bold),
                      ),
                    ],
                  ),
                ),
              // Animated live-LTP needle
              if (dotFrac != null)
                AnimatedPositioned(
                  duration: AppMotion.slow,
                  curve: AppMotion.standard,
                  left: (dotFrac * width - 6).clamp(0.0, width - 12),
                  top: 11,
                  child: Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: dotColor,
                      border: Border.all(color: context.palette.surfacePrimary, width: 2),
                      boxShadow: [
                        BoxShadow(color: dotColor.withOpacity(0.6), blurRadius: 6, spreadRadius: 1),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _Marker {
  final String label;
  final double price;
  final Color color;
  const _Marker(this.label, this.price, this.color);
}
