import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// Standard OWL surface: solid card, thin border, optional profit/loss glow.
/// Same premium look as GlassCard (soft rim in dark, soft shadow in light)
/// but no blur, so it is safe inside long live lists.
class OWLCard extends StatelessWidget {
  final Widget child;
  final EdgeInsetsGeometry? padding;
  final bool hasPositiveGlow;
  final bool hasNegativeGlow;
  final double? width;

  /// Optional coloured rim (e.g. green = good, red = bad, yellow = careful) without any glow.
  final Color? edge;

  const OWLCard({
    super.key,
    required this.child,
    this.padding,
    this.hasPositiveGlow = false,
    this.hasNegativeGlow = false,
    this.width,
    this.edge,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final dark = p.brightness == Brightness.dark;
    final Color? glow = hasPositiveGlow
        ? p.positive
        : (hasNegativeGlow ? p.negative : null);

    return Container(
      width: width,
      padding: padding ?? const EdgeInsets.all(AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        gradient: dark
            ? LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [
                  Color.alphaBlend(Colors.white.withOpacity(0.05), p.surfaceElevated),
                  p.surfaceElevated,
                ],
              )
            : null,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(
          color: glow != null ? glow.withOpacity(0.32) : (edge != null ? edge!.withOpacity(0.55) : p.border),
          width: 1,
        ),
        boxShadow: glow != null
            ? [BoxShadow(color: glow.withOpacity(dark ? 0.08 : 0.10), blurRadius: 14)]
            : (dark
                ? null
                : [
                    BoxShadow(
                      color: p.accent.withOpacity(0.06),
                      blurRadius: 18,
                      offset: const Offset(0, 6),
                    ),
                  ]),
      ),
      child: child,
    );
  }
}

/// Shared building blocks, so every screen uses the same card, title, chip and number style.

/// A titled card: small bold caps title, optional one-line hint, then the content. One look for every section on every screen.
class OwlSectionCard extends StatelessWidget {
  final String title;
  final String? hint;
  final Color? edge;
  final Widget? trailing;
  final List<Widget> children;
  final EdgeInsetsGeometry margin;

  const OwlSectionCard({
    super.key,
    required this.title,
    required this.children,
    this.hint,
    this.edge,
    this.trailing,
    this.margin = const EdgeInsets.only(bottom: AppSpacing.cardGap),
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: margin,
      child: OWLCard(
        edge: edge,
        padding: const EdgeInsets.all(AppSpacing.cardPad),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text(title, style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 0.6))),
            if (trailing != null) trailing!,
          ]),
          if (hint != null) ...[
            const SizedBox(height: 2),
            Text(hint!, style: context.type.metadata.copyWith(color: p.textMuted)),
          ],
          const SizedBox(height: AppSpacing.s),
          ...children,
        ]),
      ),
    );
  }
}

/// Small status chip: tinted background, coloured text and thin rim. Use it for BUY / SELL, scores, verdicts.
class OwlChip extends StatelessWidget {
  final String text;
  final Color color;

  const OwlChip(this.text, this.color, {super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withOpacity(0.14),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withOpacity(0.5)),
      ),
      child: Text(text, style: context.type.metadata.copyWith(color: color, fontWeight: FontWeight.w700)),
    );
  }
}

/// One number with its label underneath: the same "big value, small label" pair everywhere.
class OwlStat extends StatelessWidget {
  final String label;
  final String value;
  final Color? color;
  final double size;

  const OwlStat({super.key, required this.label, required this.value, this.color, this.size = 22});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
      Text(value, style: TextStyle(fontSize: size, fontWeight: FontWeight.w800, height: 1.1, color: color ?? p.textPrimary)),
      const SizedBox(height: 2),
      Text(label, style: context.type.metadata),
    ]);
  }
}

/// Round filter chip (All | BTC ...). Same size on Signals and Alerts.
class OwlFilterChip extends StatelessWidget {
  final String label;
  final bool on;
  final VoidCallback onTap;

  const OwlFilterChip({super.key, required this.label, required this.on, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return OWLPressable(
      onTap: () {
        if (on) return;
        AppHaptics.light();
        onTap();
      },
      child: AnimatedContainer(
        duration: AppMotion.base,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: on ? p.accent.withOpacity(0.25) : p.surfaceElevated,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: on ? p.accent : p.border),
        ),
        child: Text(label,
            style: AppTypography.secondaryData.copyWith(color: on ? p.accent : p.textSecondary, fontSize: 12, fontWeight: FontWeight.w700)),
      ),
    );
  }
}

/// Segmented tabs (Running | Closed | Skipped). One look for every list screen.
class OwlSegmented extends StatelessWidget {
  final List<(String, String)> items; // (key, text)
  final String active;
  final ValueChanged<String> onPick;

  const OwlSegmented({super.key, required this.items, required this.active, required this.onPick});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.s),
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: p.surfaceHigher.withOpacity(0.6),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: p.border),
      ),
      child: Row(children: [
        for (final it in items)
          Expanded(
            child: OWLPressable(
              onTap: () => onPick(it.$1),
              pressedScale: 0.97,
              child: AnimatedContainer(
                duration: AppMotion.base,
                alignment: Alignment.center,
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(
                  color: active == it.$1 ? p.accent.withOpacity(0.16) : Colors.transparent,
                  borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                  border: Border.all(color: active == it.$1 ? p.accent.withOpacity(0.45) : Colors.transparent),
                ),
                child: Text(it.$2,
                    style: AppTypography.secondaryData.copyWith(
                        color: active == it.$1 ? p.accent : p.textSecondary, fontSize: 13, fontWeight: FontWeight.w700)),
              ),
            ),
          ),
      ]),
    );
  }
}

/// A row of equal "big number over small label" stats.
class OwlStatRow extends StatelessWidget {
  final List<(String, String, Color)> stats; // (label, value, colour)
  const OwlStatRow(this.stats, {super.key});

  @override
  Widget build(BuildContext context) {
    final t = context.type;
    return Row(children: [
      for (final s in stats)
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(s.$1, style: t.label.copyWith(fontSize: 10)),
            const SizedBox(height: 2),
            Text(s.$2, style: t.primary.copyWith(color: s.$3, fontWeight: FontWeight.w800, fontSize: 17)),
          ]),
        ),
    ]);
  }
}

/// LONG / SHORT (or any) solid side badge, white text.
class OwlSideBadge extends StatelessWidget {
  final String word;
  final Color color;
  const OwlSideBadge(this.word, this.color, {super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(5)),
      child: Text(word,
          style: const TextStyle(color: Colors.white, fontSize: 10.5, fontWeight: FontWeight.w800, height: 1.1, letterSpacing: 0.4)),
    );
  }
}

/// Day heading between groups of cards ("Today  ·  5 signals ...").
class OwlDayHeader extends StatelessWidget {
  final String text;
  const OwlDayHeader(this.text, {super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 10, bottom: 6),
      child: Text(text, style: context.type.label.copyWith(fontWeight: FontWeight.w800)),
    );
  }
}
