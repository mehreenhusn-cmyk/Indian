import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_motion2.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../utils/format.dart';

/// R31b (Part 12a): the number building blocks of the new look. Used by Part 12b (Dashboard) and later screens; nothing uses them yet, so this Part changes no screen.
///   OwlNumber     ONE money / count number: green when above 0, red when below, plain at 0 or when [neutral]. Tabular (Mono in the new font), never wraps, shrinks to fit (FittedBox), "--" when null.
///   OwlPill       ONE small status tag: tone 'good' / 'bad' / 'warn' / '' = grey. One solid tint, only for a status or a change percent, never decoration.
///   OwlStatStrip  a flat line of 2 to 4 facts (big value over a small label), no box per fact (like the exchange page the owner liked).
/// Colours come from the palette, so Light and Dark both follow.
/// P-E: [animate] = a short count-up (first time from 0, later from the old value to the new one, 350 ms ease-out). Off by default (a list of many numbers stays still); the Dashboard hero turns it on. The colour follows the FINAL value, so it never flashes red / green on the way. Dart NOT compiled.
class OwlNumber extends StatelessWidget {
  final double? value;
  final String suffix;
  final double size;
  final bool signed;
  final int decimals;
  final bool neutral;
  final bool alignRight;
  final bool animate;

  const OwlNumber(this.value, {super.key, this.suffix = '', this.size = 20, this.signed = true, this.decimals = 2, this.neutral = false, this.alignRight = false, this.animate = false});

  Widget _text(BuildContext context, double? shown) {
    final p = context.palette;
    final v = value;
    final color = v == null || neutral || v == 0 ? p.textPrimary : (v > 0 ? p.profit : p.loss);
    final text = shown == null ? '--' : '${signed ? fmtSigned(shown, decimals) : shown.toStringAsFixed(decimals)}${suffix.isEmpty ? '' : ' $suffix'}';
    return FittedBox(
      fit: BoxFit.scaleDown,
      alignment: alignRight ? Alignment.centerRight : Alignment.centerLeft,
      child: Text(text, maxLines: 1, style: context.type.number.copyWith(fontSize: size, color: v == null ? p.textMuted : color)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final v = value;
    if (!animate || v == null) return _text(context, v);
    return TweenAnimationBuilder<double>(
      tween: Tween<double>(begin: 0, end: v),
      duration: const Duration(milliseconds: 350),
      curve: OwlMotion.smooth,
      builder: (context, x, _) => _text(context, x),
    );
  }
}

class OwlPill extends StatelessWidget {
  final String text;
  final String tone;

  const OwlPill(this.text, {super.key, this.tone = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = tone == 'good' ? p.profit : tone == 'bad' ? p.loss : tone == 'warn' ? p.warning : p.textMuted;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(AppSpacing.radiusPill)),
      child: Text(text, maxLines: 1, style: context.type.metadata.copyWith(color: c, fontWeight: FontWeight.w700, fontSize: 11)),
    );
  }
}

class OwlStat {
  final String value;
  final String label;
  final String tone;
  /// Plan A: optional tap (e.g. Open P&L -> Positions Live). Old calls without it work as before.
  final VoidCallback? onTap;
  /// Plan A: optional small grey line under the value (e.g. the INR amount). Empty = nothing shown.
  final String sub;
  const OwlStat(this.value, this.label, {this.tone = '', this.onTap, this.sub = ''});
}

class OwlStatStrip extends StatelessWidget {
  final List<OwlStat> items;

  const OwlStatStrip(this.items, {super.key});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.m),
      decoration: BoxDecoration(border: Border(top: BorderSide(color: p.border), bottom: BorderSide(color: p.border))),
      child: Row(children: [
        for (final s in items)
          Expanded(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: s.onTap,
              child: Padding(padding: const EdgeInsets.only(right: 8), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(s.value, maxLines: 1, style: context.type.number.copyWith(fontSize: 17, color: s.tone == 'good' ? p.profit : s.tone == 'bad' ? p.loss : p.textPrimary)), // Part 3: 17 sp so FittedBox is only a safety net, not the normal case
              ),
              const SizedBox(height: 2),
              Text(s.label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(fontSize: 11, letterSpacing: 0.8)),
            ])),
            ),
          ),
      ]),
    );
  }
}

/// Plan A: a grid of stat TILES (2 per row by default) instead of squeezing 4 numbers into one line.
/// Each tile: small caps label, the value (big number scale, shrinks only if it really must), an optional small grey line ([OwlStat.sub], e.g. INR),
/// and a chevron when the tile is tappable. A tile with an empty value shows "--" (never a made-up 0). Colours follow the palette (Dark and Light).
class OwlStatGrid extends StatelessWidget {
  final List<OwlStat> items;
  final int columns;

  const OwlStatGrid(this.items, {super.key, this.columns = 2});

  Widget _tile(BuildContext context, OwlStat s) {
    final p = context.palette;
    final color = s.tone == 'good' ? p.profit : (s.tone == 'bad' ? p.loss : p.textPrimary);
    final shown = s.value.isEmpty ? '--' : s.value;
    final tile = Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Row(children: [
          Expanded(child: Text(s.label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(fontSize: 11, letterSpacing: 0.8))),
          if (s.onTap != null) Icon(Icons.chevron_right_rounded, size: 16, color: p.textMuted),
        ]),
        const SizedBox(height: 4),
        FittedBox(
          fit: BoxFit.scaleDown,
          alignment: Alignment.centerLeft,
          child: Text(shown, maxLines: 1, style: context.type.number.copyWith(color: s.value.isEmpty ? p.textMuted : color)),
        ),
        if (s.sub.isNotEmpty) ...[
          const SizedBox(height: 2),
          Text(s.sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(color: p.textMuted)),
        ],
      ]),
    );
    if (s.onTap == null) return tile;
    return GestureDetector(behavior: HitTestBehavior.opaque, onTap: s.onTap, child: tile);
  }

  @override
  Widget build(BuildContext context) {
    final rows = <Widget>[];
    for (var i = 0; i < items.length; i += columns) {
      final cells = <Widget>[];
      for (var j = 0; j < columns; j++) {
        if (j > 0) cells.add(const SizedBox(width: AppSpacing.cardGap));
        cells.add(Expanded(child: i + j < items.length ? _tile(context, items[i + j]) : const SizedBox.shrink()));
      }
      if (rows.isNotEmpty) rows.add(const SizedBox(height: AppSpacing.cardGap));
      rows.add(IntrinsicHeight(child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: cells)));
    }
    return Column(children: rows);
  }
}

/// Plan A: a ring (circle gauge) with one text in the middle, e.g. daily target progress or win rate.
/// [fraction] is 0.0 to 1.0 and must be a REAL measured value; when there is nothing real to show (no target set, no data) the caller does not build the ring.
/// [tone] 'good' / 'bad' / '' = accent. Static, no animation (cheap on a phone).
class OwlRing extends StatelessWidget {
  final double fraction;
  final String center;
  final String caption;
  final String tone;
  final double size;

  const OwlRing({super.key, required this.fraction, required this.center, this.caption = '', this.tone = '', this.size = 64});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final arc = tone == 'good' ? p.profit : (tone == 'bad' ? p.loss : p.accent);
    return SizedBox(
      width: size,
      height: size,
      child: Stack(alignment: Alignment.center, children: [
        CustomPaint(size: Size.square(size), painter: _RingPainter(fraction.isNaN ? 0.0 : fraction.clamp(0.0, 1.0).toDouble(), p.border, arc, size >= 56 ? 6.0 : 4.0)),
        Padding(
          padding: EdgeInsets.all(size * 0.2),
          child: Column(mainAxisSize: MainAxisSize.min, mainAxisAlignment: MainAxisAlignment.center, children: [
            FittedBox(fit: BoxFit.scaleDown, child: Text(center, maxLines: 1, style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13))),
            if (caption.isNotEmpty) FittedBox(fit: BoxFit.scaleDown, child: Text(caption, maxLines: 1, style: context.type.metadata.copyWith(fontSize: 10, color: p.textMuted))),
          ]),
        ),
      ]),
    );
  }
}

class _RingPainter extends CustomPainter {
  final double fraction;
  final Color track;
  final Color arc;
  final double stroke;

  _RingPainter(this.fraction, this.track, this.arc, this.stroke);

  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(stroke / 2);
    final base = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..color = track;
    final top = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = stroke
      ..strokeCap = StrokeCap.round
      ..color = arc;
    canvas.drawArc(rect, -math.pi / 2, 2 * math.pi, false, base);
    if (fraction > 0) canvas.drawArc(rect, -math.pi / 2, 2 * math.pi * fraction, false, top);
  }

  @override
  bool shouldRepaint(covariant _RingPainter old) => old.fraction != fraction || old.track != track || old.arc != arc || old.stroke != stroke;
}

/// Plan A: the small grey INR line under a USDT number: "approx. INR 977". Nothing is shown when the amount or the rate is missing.
/// The rate is the fixed setting inr_rate (not a live exchange rate), so the text says "approx.".
class OwlInr extends StatelessWidget {
  final double? usdt;
  final double rate;
  final bool signed;

  const OwlInr(this.usdt, this.rate, {super.key, this.signed = true});

  @override
  Widget build(BuildContext context) {
    final t = fmtInr(usdt, rate, signed: signed);
    if (t == null) return const SizedBox.shrink();
    return Text('approx. $t', maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata.copyWith(color: context.palette.textMuted));
  }
}
