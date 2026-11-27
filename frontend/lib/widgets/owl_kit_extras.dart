import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_hero_card.dart';

/// Part 9 (D1b, 28 Nov 2026): shared UI kit, piece 3 = EMPTY STATE + PICK CHIPS + SHIMMER helpers.
/// Part 8 gave the hero card, section header and stat tile. This file finishes the kit; screens (parts 10 to 19) reuse it.
/// New names on purpose: OwlChip, OwlFilterChip and OwlStatRow already exist in widgets/owl_card.dart and are NOT touched.
/// Plain widgets, no provider, no network. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.

/// Empty state: a soft round icon, one bold line, one short muted line, optional button. Use it when a list has nothing yet.
class OwlEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String sub;
  final String actionLabel;
  final VoidCallback? onAction;
  final String tone;

  const OwlEmptyState({
    super.key,
    this.icon = Icons.inbox_rounded,
    required this.title,
    this.sub = '',
    this.actionLabel = '',
    this.onAction,
    this.tone = '',
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = tone.isEmpty ? p.textMuted : owlToneColor(p, tone);
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxl, vertical: AppSpacing.section),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(
            width: 56,
            height: 56,
            decoration: BoxDecoration(shape: BoxShape.circle, color: c.withOpacity(0.10), border: Border.all(color: c.withOpacity(0.25))),
            child: Icon(icon, size: 26, color: c),
          ),
          const SizedBox(height: AppSpacing.m),
          Text(title, textAlign: TextAlign.center, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
          if (sub.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(sub, textAlign: TextAlign.center, style: TextStyle(fontSize: 12.5, height: 1.3, color: p.textMuted)),
            ),
          if (actionLabel.isNotEmpty && onAction != null)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.m),
              child: TextButton(
                onPressed: onAction,
                style: TextButton.styleFrom(
                  foregroundColor: p.accent,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusPill), side: BorderSide(color: p.accent.withOpacity(0.4))),
                ),
                child: Text(actionLabel, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w700)),
              ),
            ),
        ]),
      ),
    );
  }
}

/// One tap chip (a filter or a tab-like choice): selected = tinted with the accent, not selected = plain. Optional small count on the right.
class OwlPickChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final int? count;
  final String tone;

  const OwlPickChip({super.key, required this.label, this.selected = false, this.onTap, this.count, this.tone = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final c = tone.isEmpty ? p.accent : owlToneColor(p, tone);
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(
            color: selected ? c.withOpacity(0.14) : p.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
            border: Border.all(color: selected ? c.withOpacity(0.55) : p.border),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Text(label, style: TextStyle(fontSize: 12.5, fontWeight: selected ? FontWeight.w800 : FontWeight.w600, color: selected ? c : p.textSecondary)),
            if (count != null) ...[
              const SizedBox(width: 6),
              Text('$count', style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700, color: selected ? c : p.textMuted)),
            ],
          ]),
        ),
      ),
    );
  }
}

/// A sideways-scrolling row of pick chips. [labels] are shown in order, [selected] is the index that is lit,
/// [onSelect] gets the tapped index. Optional [counts] (same length as labels, a null entry = no count).
class OwlPickChipRow extends StatelessWidget {
  final List<String> labels;
  final int selected;
  final ValueChanged<int> onSelect;
  final List<int?>? counts;
  final EdgeInsetsGeometry padding;

  const OwlPickChipRow({
    super.key,
    required this.labels,
    required this.selected,
    required this.onSelect,
    this.counts,
    this.padding = EdgeInsets.zero,
  });

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: padding,
      child: Row(children: [
        for (var i = 0; i < labels.length; i++) ...[
          if (i > 0) const SizedBox(width: AppSpacing.s),
          OwlPickChip(
            label: labels[i],
            selected: i == selected,
            count: (counts != null && i < counts!.length) ? counts![i] : null,
            onTap: () => onSelect(i),
          ),
        ],
      ]),
    );
  }
}

/// Shimmer: one soft light band that slides over every child that uses [OwlShimmerBox]. Wrap a whole skeleton layout in ONE OwlShimmer
/// (one ticker for the whole layout, not one per box). It only runs while it is on screen and stops when it is removed.
class OwlShimmer extends StatefulWidget {
  final Widget child;
  final Duration period;

  const OwlShimmer({super.key, required this.child, this.period = const Duration(milliseconds: 1300)});

  /// The current band position (-1 to 2) for the boxes below it; 0.5 when there is no OwlShimmer above.
  static double phaseOf(BuildContext context) {
    final s = context.dependOnInheritedWidgetOfExactType<_OwlShimmerScope>();
    return s?.phase ?? 0.5;
  }

  @override
  State<OwlShimmer> createState() => _OwlShimmerState();
}

class _OwlShimmerState extends State<OwlShimmer> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: widget.period)..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _c,
      child: widget.child,
      builder: (context, child) => _OwlShimmerScope(phase: -1.0 + 3.0 * _c.value, child: child!),
    );
  }
}

class _OwlShimmerScope extends InheritedWidget {
  final double phase;

  const _OwlShimmerScope({required this.phase, required super.child});

  @override
  bool updateShouldNotify(_OwlShimmerScope old) => old.phase != phase;
}

/// A grey rounded box with the shimmer band. Put it inside an [OwlShimmer]; alone it shows a calm still box.
class OwlShimmerBox extends StatelessWidget {
  final double? width;
  final double height;
  final double radius;

  const OwlShimmerBox({super.key, this.width, this.height = 14, this.radius = 6});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final phase = OwlShimmer.phaseOf(context);
    final base = p.border.withOpacity(0.55);
    final light = p.textMuted.withOpacity(0.18);
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment(phase - 1.0, 0),
          end: Alignment(phase, 0),
          colors: [base, light, base],
          stops: const [0.0, 0.5, 1.0],
        ),
      ),
    );
  }
}

/// A ready skeleton card: a short title line, a big number block and [lines] text lines. Same outer look as the hero card.
class OwlShimmerCard extends StatelessWidget {
  final int lines;
  final double bigHeight;

  const OwlShimmerCard({super.key, this.lines = 2, this.bigHeight = 30});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
        const OwlShimmerBox(width: 90, height: 11),
        const SizedBox(height: 10),
        OwlShimmerBox(width: 160, height: bigHeight, radius: 8),
        for (var i = 0; i < lines; i++) ...[
          const SizedBox(height: 10),
          OwlShimmerBox(width: i.isEven ? double.infinity : 200, height: 11),
        ],
      ]),
    );
  }
}

/// A column of [count] skeleton cards inside ONE shimmer: the loading look of a whole screen.
class OwlShimmerList extends StatelessWidget {
  final int count;
  final EdgeInsetsGeometry padding;

  const OwlShimmerList({super.key, this.count = 3, this.padding = const EdgeInsets.all(AppSpacing.l)});

  @override
  Widget build(BuildContext context) {
    return OwlShimmer(
      child: Padding(
        padding: padding,
        child: Column(children: [
          for (var i = 0; i < count; i++) ...[
            if (i > 0) const SizedBox(height: AppSpacing.cardGap),
            OwlShimmerCard(lines: i == 0 ? 2 : 1),
          ],
        ]),
      ),
    );
  }
}
