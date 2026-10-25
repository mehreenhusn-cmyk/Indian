import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../utils/format.dart';

/// One open Dual Bot trade as a card, same idea as the Positions tab:
/// coin + side + where the entry came from, live P&L, entry / live / stop, and a ladder
/// from the stop to take-profit 4 with the live price on it. Tap opens the big chart.
/// Only shows data the Dual Bot already sends (entry, sl, path, tps, lpx_now, live_now).
class DualTradeCard extends StatelessWidget {
  final Map<String, dynamic> row;
  final double margin;
  final VoidCallback onTap;

  /// Optional one-line "how did this setup do before" widget, built by the screen.
  final Widget? setupLine;

  const DualTradeCard({super.key, required this.row, required this.margin, required this.onTap, this.setupLine});

  static double? _n(dynamic v) => v is num ? v.toDouble() : null;

  static String _age(dynamic tMs) {
    final t = _n(tMs);
    if (t == null) return '';
    final secs = (DateTime.now().millisecondsSinceEpoch - t) / 1000.0;
    if (secs < 60) return 'just now';
    final m = (secs / 60).floor();
    if (m < 60) return '${m}m';
    final h = m ~/ 60;
    return '${h}h ${m % 60}m';
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final long = (_n(row['d']) ?? 1) > 0;
    final sym = '${row['s'] ?? ''}'.replaceAll('USDT', '');
    final src = '${row['src'] ?? ''}';
    final srcName = src == 'MAIN' ? 'Main chart' : (src == 'Z' ? 'Z pane' : (src == 'BOTH' ? 'Both' : ''));

    final entry = _n(row['entry']);
    final live = _n(row['lpx_now']) ?? _n(row['lpx']);
    final sl0 = _n(row['sl']);
    double? slNow = sl0;
    final pathN = row['path'] is List ? (row['path'] as List).length : 0;
    if (pathN > 0) {
      final last = (row['path'] as List).last;
      if (last is List && last.length >= 2 && last[1] is num) slNow = (last[1] as num).toDouble();
    }
    final tps = <double>[];
    if (row['tps'] is List) {
      for (final v in (row['tps'] as List)) {
        final d = _n(v);
        if (d != null) tps.add(d);
      }
    }

    final roi = _n(row['live_now']) ?? _n(row['live']);
    final usdt = roi == null ? null : roi * margin / 100.0;
    final up = (usdt ?? 0) >= 0;
    final pnlColor = usdt == null ? p.textMuted : (up ? p.profit : p.loss);
    final sideColor = long ? p.profit : p.loss;

    const tab = [FontFeature.tabularFigures()];

    Widget chip(String text, Color c) => Container(
          padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
          decoration: BoxDecoration(
            color: c.withOpacity(0.12),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700, color: c)),
        );

    Widget stat(String label, String value, {Color? color}) => Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label, style: TextStyle(fontSize: 10.5, color: p.textMuted)),
              const SizedBox(height: 2),
              Text(
                value,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                    fontSize: 13, fontWeight: FontWeight.w700, color: color ?? p.textPrimary, fontFeatures: tab),
              ),
            ],
          ),
        );

    final age = _age(row['t']);

    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
          decoration: BoxDecoration(
            color: p.surface,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: p.border, width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  Text(sym, style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: p.textPrimary)),
                  const SizedBox(width: 8),
                  chip(long ? 'LONG' : 'SHORT', sideColor),
                  const SizedBox(width: 6),
                  chip('${row['f'] ?? ''}', p.textMuted),
                  if (srcName.isNotEmpty) ...[
                    const SizedBox(width: 6),
                    chip(srcName, p.accent),
                  ],
                  const Spacer(),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Text(
                        usdt == null ? '--' : '${fmtSigned(usdt)} USDT',
                        style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: pnlColor, fontFeatures: tab),
                      ),
                      if (roi != null)
                        Text('${fmtSigned(roi, 1)}% of margin',
                            style: TextStyle(fontSize: 10.5, color: pnlColor, fontFeatures: tab)),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  stat('Entry', fmtPrice(entry)),
                  stat('Live', live == null ? '--' : fmtPrice(live)),
                  stat('Stop now', fmtPrice(slNow), color: p.loss),
                ],
              ),
              const SizedBox(height: 12),
              SizedBox(
                height: 34,
                width: double.infinity,
                child: CustomPaint(
                  painter: _LadderPainter(
                    entry: entry,
                    live: live,
                    stop: slNow,
                    tps: tps,
                    long: long,
                    good: p.profit,
                    bad: p.loss,
                    track: p.border,
                    text: p.textMuted,
                    dot: p.textPrimary,
                  ),
                ),
              ),
              const SizedBox(height: 8),
              Row(
                children: [
                  Icon(Icons.schedule_rounded, size: 13, color: p.textMuted),
                  const SizedBox(width: 4),
                  Expanded(
                    child: Text(
                      '${age.isEmpty ? 'Open' : (age == 'just now' ? 'Opened just now' : 'Open for $age')}'
                      '${pathN > 0 ? '  ·  stop moved $pathN×' : '  ·  stop not moved'}',
                      style: TextStyle(fontSize: 11, color: p.textMuted),
                    ),
                  ),
                  Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
                ],
              ),
              if (setupLine != null) ...[
                const SizedBox(height: 4),
                setupLine!,
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// Stop ... entry ... TP1-TP4 on one line. Left = stop side, right = profit side (flipped for shorts
/// by using real prices, so it always reads "worse on the left, better on the right").
class _LadderPainter extends CustomPainter {
  final double? entry, live, stop;
  final List<double> tps;
  final bool long;
  final Color good, bad, track, text, dot;

  _LadderPainter({
    required this.entry,
    required this.live,
    required this.stop,
    required this.tps,
    required this.long,
    required this.good,
    required this.bad,
    required this.track,
    required this.text,
    required this.dot,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (entry == null) return;
    final pts = <double>[entry!, if (stop != null) stop!, if (live != null) live!, ...tps];
    var lo = pts.reduce((a, b) => a < b ? a : b);
    var hi = pts.reduce((a, b) => a > b ? a : b);
    if (hi - lo <= 0) return;
    final pad = (hi - lo) * 0.04;
    lo -= pad;
    hi += pad;
    // Profit direction is always to the right.
    double x(double v) {
      final f = (v - lo) / (hi - lo);
      return (long ? f : 1 - f) * size.width;
    }

    final y = 11.0;
    final base = Paint()
      ..color = track
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;
    canvas.drawLine(Offset(0, y), Offset(size.width, y), base);

    // Filled part between entry and live price.
    if (live != null) {
      final up = long ? live! >= entry! : live! <= entry!;
      final fill = Paint()
        ..color = up ? good : bad
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round;
      canvas.drawLine(Offset(x(entry!), y), Offset(x(live!), y), fill);
    }

    void tick(double v, Color c, String label) {
      final px = x(v).clamp(2.0, size.width - 2.0).toDouble();
      canvas.drawLine(Offset(px, y - 6), Offset(px, y + 6), Paint()..color = c..strokeWidth = 2);
      final tp = TextPainter(
        text: TextSpan(text: label, style: TextStyle(fontSize: 9, color: c, fontWeight: FontWeight.w700)),
        textDirection: TextDirection.ltr,
      )..layout();
      final lx = (px - tp.width / 2).clamp(0.0, size.width - tp.width).toDouble();
      tp.paint(canvas, Offset(lx, y + 9));
    }

    if (stop != null) tick(stop!, bad, 'SL');
    tick(entry!, text, 'IN');
    for (var k = 0; k < tps.length && k < 4; k++) {
      tick(tps[k], good, 'TP${k + 1}');
    }

    if (live != null) {
      final px = x(live!).clamp(4.0, size.width - 4.0).toDouble();
      canvas.drawCircle(Offset(px, y), 5.5, Paint()..color = dot);
      canvas.drawCircle(
          Offset(px, y), 3.2, Paint()..color = (long ? live! >= entry! : live! <= entry!) ? good : bad);
    }
  }

  @override
  bool shouldRepaint(covariant _LadderPainter o) =>
      o.entry != entry || o.live != live || o.stop != stop || o.tps.length != tps.length || o.long != long;
}
