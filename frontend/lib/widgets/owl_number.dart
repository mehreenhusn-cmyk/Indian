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
  const OwlStat(this.value, this.label, {this.tone = ''});
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
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(s.value, maxLines: 1, style: context.type.number.copyWith(color: s.tone == 'good' ? p.profit : s.tone == 'bad' ? p.loss : p.textPrimary)),
              ),
              const SizedBox(height: 2),
              Text(s.label.toUpperCase(), maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.label.copyWith(fontSize: 11, letterSpacing: 0.8)),
            ]),
          ),
      ]),
    );
  }
}
