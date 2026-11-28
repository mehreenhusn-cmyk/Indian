import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import '../theme/app_typography.dart';

/// Part 8 (D1a, 28 Nov 2026): shared UI kit, piece 1 = the HERO CARD and the thin win / loss bar.
/// One big number per card, a short plain label above it and one plain line under it. Same look as the Pump/Dump tab
/// (soft tint of the tone colour, thin accent border, soft shadow). Plain widgets: no provider, no timer, no network.
/// tone: 'good' = green, 'bad' = red, 'warn' = amber, anything else = the app accent. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.
Color owlToneColor(AppPalette p, String tone) {
  switch (tone) {
    case 'good':
      return p.profit;
    case 'bad':
      return p.loss;
    case 'warn':
      return p.warning;
    default:
      return p.accent;
  }
}

/// Thin bar: the green part is [share] (0 to 1), the rest is the loss colour. Optional small caption under it.
class OwlWinBar extends StatelessWidget {
  final double share;
  final String caption;
  final double height;

  const OwlWinBar({super.key, required this.share, this.caption = '', this.height = 5});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final s = share.isNaN ? 0.0 : share.clamp(0.0, 1.0).toDouble();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      ClipRRect(
        borderRadius: BorderRadius.circular(height),
        child: SizedBox(
          height: height,
          child: Stack(children: [
            Positioned.fill(child: ColoredBox(color: p.loss.withOpacity(0.35))),
            FractionallySizedBox(widthFactor: s, child: ColoredBox(color: p.profit, child: SizedBox(height: height))),
          ]),
        ),
      ),
      if (caption.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(caption, style: TextStyle(fontSize: 11, color: p.textMuted))),
    ]);
  }
}

/// Part 22: [value] now uses the app's big tabular number style (digits do not jump), [unit] is a small word after it (USDT), [delta] is one small coloured line ("-2.18% vs yesterday").
/// The hero card: [label] (small, muted), [value] (big), [sub] (one plain line). Optional win bar ([share]), a [trailing] widget (a switch, a chip) and a tap.
class OwlHeroCard extends StatelessWidget {
  final String label;
  final String value;
  final String sub;
  final String tone;
  final String unit;
  final String delta;
  final String deltaTone;
  final double? share;
  final String shareCaption;
  final Widget? trailing;
  final VoidCallback? onTap;

  const OwlHeroCard({
    super.key,
    required this.label,
    required this.value,
    this.sub = '',
    this.tone = '',
    this.unit = '',
    this.delta = '',
    this.deltaTone = '',
    this.share,
    this.shareCaption = '',
    this.trailing,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = owlToneColor(p, tone);
    final body = Padding(
      padding: const EdgeInsets.all(AppSpacing.l),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
          Expanded(child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, letterSpacing: 0.6, color: p.textMuted))),
          if (trailing != null) trailing!,
        ]),
        const SizedBox(height: 6),
        Text.rich(
          TextSpan(children: [
            TextSpan(text: value),
            if (unit.isNotEmpty) TextSpan(text: ' $unit', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0, color: p.textMuted)),
          ]),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: AppTypography.heroXL.copyWith(color: tone.isEmpty ? p.textPrimary : c),
        ),
        if (delta.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(delta, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700, color: deltaTone.isEmpty ? p.textSecondary : owlToneColor(p, deltaTone)))),
        if (sub.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(sub, style: TextStyle(fontSize: 12.5, color: p.textSecondary))),
        if (share != null) Padding(padding: const EdgeInsets.only(top: 12), child: OwlWinBar(share: share!, caption: shareCaption)),
      ]),
    );
    return Container(
      decoration: BoxDecoration(
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [c.withOpacity(0.09), p.surface]),
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: c.withOpacity(0.28)),
        boxShadow: [BoxShadow(color: Colors.black.withOpacity(0.10), blurRadius: 14, offset: const Offset(0, 5))],
      ),
      child: onTap == null
          ? body
          : Material(
              color: Colors.transparent,
              child: InkWell(borderRadius: BorderRadius.circular(AppSpacing.radiusLarge), onTap: onTap, child: body),
            ),
    );
  }
}
