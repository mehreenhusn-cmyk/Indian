import 'package:flutter/material.dart';

/// Slim SL -> Entry -> TP1..TP4 track for a signal card.
///
/// Schematic, not a price axis: markers are evenly spaced in path order so a
/// SHORT (where SL > entry) reads the same left-to-right as a LONG. TP levels
/// that were reached ([hit]) are filled; the track between entry and the last
/// reached level is coloured in.
class MiniLadder extends StatelessWidget {
  final bool hasSl;
  final List<int> tpLevels; // e.g. [1,2,3,4] - only the ones that exist
  final Set<int> hit;
  final Color slColor;
  final Color entryColor;
  final Color tpColor;
  final Color trackColor;
  final Color? labelColor; // colour of the SL / ENTRY / TP1.. captions

  /// Optional caption per TP marker (same order as [tpLevels]) - lets several
  /// levels with one price share a marker ("TP2-4"). Null = "TP<level>".
  final List<String>? tpLabels;

  /// Optional second line under each TP caption (e.g. "+4.42%").
  final List<String>? tpSubs;

  const MiniLadder({
    super.key,
    required this.hasSl,
    required this.tpLevels,
    required this.hit,
    required this.slColor,
    required this.entryColor,
    required this.tpColor,
    required this.trackColor,
    this.labelColor,
    this.tpLabels,
    this.tpSubs,
  });

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: tpSubs != null ? 40 : 26,
      width: double.infinity,
      child: CustomPaint(
        painter: _MiniLadderPainter(
          hasSl: hasSl,
          tpLevels: tpLevels,
          hit: hit,
          slColor: slColor,
          entryColor: entryColor,
          tpColor: tpColor,
          trackColor: trackColor,
          labelColor: labelColor ?? trackColor,
          tpLabels: tpLabels,
          tpSubs: tpSubs,
        ),
      ),
    );
  }
}

class _MiniLadderPainter extends CustomPainter {
  final bool hasSl;
  final List<int> tpLevels;
  final Set<int> hit;
  final Color slColor, entryColor, tpColor, trackColor, labelColor;
  final List<String>? tpLabels;
  final List<String>? tpSubs;

  _MiniLadderPainter({
    required this.hasSl,
    required this.tpLevels,
    required this.hit,
    required this.slColor,
    required this.entryColor,
    required this.tpColor,
    required this.trackColor,
    required this.labelColor,
    this.tpLabels,
    this.tpSubs,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final n = (hasSl ? 1 : 0) + 1 + tpLevels.length;
    if (n < 2) return;
    const pad = 6.0;
    final w = size.width - pad * 2;
    final y = 6.0;
    double xAt(int i) => pad + w * (i / (n - 1));

    final track = Paint()
      ..color = trackColor
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(Offset(pad, y), Offset(pad + w, y), track);

    final entryIdx = hasSl ? 1 : 0;

    // Progress fill: entry -> furthest reached TP.
    int lastHitIdx = entryIdx;
    for (var k = 0; k < tpLevels.length; k++) {
      if (hit.contains(tpLevels[k])) lastHitIdx = entryIdx + 1 + k;
    }
    if (lastHitIdx > entryIdx) {
      final fill = Paint()
        ..color = tpColor
        ..strokeWidth = 2
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(xAt(entryIdx), y), Offset(xAt(lastHitIdx), y), fill);
    }

    if (hasSl) {
      final p = Paint()
        ..color = slColor
        ..strokeWidth = 2.4
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(xAt(0), y - 4), Offset(xAt(0), y + 4), p);
    }

    canvas.drawCircle(Offset(xAt(entryIdx), y), 3.2, Paint()..color = entryColor);

    for (var k = 0; k < tpLevels.length; k++) {
      final cx = xAt(entryIdx + 1 + k);
      final reached = hit.contains(tpLevels[k]);
      if (reached) {
        canvas.drawCircle(Offset(cx, y), 3.6, Paint()..color = tpColor);
      } else {
        canvas.drawCircle(
          Offset(cx, y),
          3.2,
          Paint()
            ..color = tpColor.withOpacity(0.65)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 1.3,
        );
      }
    }

    // Captions so every marker says what it is.
    void caption(String text, int i, {FontWeight fw = FontWeight.w600, Color? color, double dy = 8, double fs = 9}) {
      final tp = TextPainter(
        text: TextSpan(text: text, style: TextStyle(color: color ?? labelColor, fontSize: fs, fontWeight: fw, letterSpacing: 0.2)),
        textDirection: TextDirection.ltr,
      )..layout();
      var x = xAt(i) - tp.width / 2;
      x = x.clamp(0.0, size.width - tp.width);
      tp.paint(canvas, Offset(x, y + dy));
    }

    if (hasSl) caption('SL', 0);
    caption('ENTRY', entryIdx);
    for (var k = 0; k < tpLevels.length; k++) {
      final lbl = (tpLabels != null && k < tpLabels!.length) ? tpLabels![k] : 'TP${tpLevels[k]}';
      caption(lbl, entryIdx + 1 + k);
      if (tpSubs != null && k < tpSubs!.length) {
        final reached = hit.contains(tpLevels[k]);
        caption(tpSubs![k], entryIdx + 1 + k,
            fw: FontWeight.w700, color: reached ? tpColor : null, dy: 20, fs: 10);
      }
    }
  }

  @override
  bool shouldRepaint(_MiniLadderPainter old) =>
      old.hasSl != hasSl ||
      old.tpLevels.length != tpLevels.length ||
      old.tpLabels != tpLabels ||
      old.tpSubs != tpSubs ||
      old.hit.length != hit.length ||
      old.tpColor != tpColor ||
      old.trackColor != trackColor ||
      old.labelColor != labelColor;
}
