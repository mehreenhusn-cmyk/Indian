import 'package:flutter/material.dart';
import '../theme/app_scale.dart';
import '../theme/app_spacing.dart';
import '../theme/app_styles.dart';
import '../theme/app_theme.dart';
import 'owl_number.dart';
import 'owl_pressable.dart';
import 'owl_skeleton.dart';

/// R31b (Part 12a): the LIST building blocks of the new look (plan H3: no card per row, ONE card around the whole list, thin divider between rows, rows at least 56 high).
///   OwlRow         title (+ one grey line under it) on the left, a number / pill on the right ([trailing]), optional [leading] icon, optional tap. Long text ends with "..." (never overflows).
///   OwlListCard    ONE card around a list of rows with a 1 px divider between them.
///   OwlRowSkeleton the same card with grey shimmer rows, shown instead of a spinner while the data loads.
/// P-E: OwlListCard has the gradient hairline edge; the loading rows already shimmer (OWLSkeleton), the tap feedback is OWLPressable (110 ms fade + small scale).
/// Part 12b: the row height follows the screen (AppScale.rowHeight = 56 x screen factor 0.92 - 1.10). Used by the Dashboard open pairs (12b); Part 13 brings the other screens. Dart NOT compiled.
class OwlRow extends StatelessWidget {
  final String title;
  final String sub;
  final Widget? leading;
  final Widget? trailing;
  final VoidCallback? onTap;

  const OwlRow({super.key, required this.title, this.sub = '', this.leading, this.trailing, this.onTap});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = Container(
      constraints: BoxConstraints(minHeight: AppScale.rowHeight(context)),
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.rowPadV),
      child: Row(children: [
        if (leading != null) ...[leading!, const SizedBox(width: AppSpacing.m)],
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
            Text(title, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w600)),
            if (sub.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(sub, maxLines: 1, overflow: TextOverflow.ellipsis, style: context.type.metadata)),
          ]),
        ),
        if (trailing != null) ...[const SizedBox(width: AppSpacing.m), Flexible(child: Align(alignment: Alignment.centerRight, child: trailing!))],
        if (onTap != null) Padding(padding: const EdgeInsets.only(left: 4), child: Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted)),
      ]),
    );
    return onTap == null ? row : OWLPressable(pressedScale: 0.99, onTap: onTap, child: row);
  }
}

class OwlListCard extends StatelessWidget {
  final List<Widget> children;

  const OwlListCard({super.key, required this.children});

  /// P-E: the 1 px edge is a soft gradient (a touch brighter at the top-left, fading into the normal border), no shadow.
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    const r = AppSpacing.radiusMedium;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(1),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(r),
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color.lerp(p.border, p.textPrimary, 0.14)!, p.border]),
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(r - 1),
        child: ColoredBox(
          color: p.surface,
          child: Column(children: [
            for (var i = 0; i < children.length; i++) ...[
              if (i > 0) AppStyles.divider(context),
              children[i],
            ],
          ]),
        ),
      ),
    );
  }
}

class OwlRowSkeleton extends StatelessWidget {
  final int rows;

  const OwlRowSkeleton({super.key, this.rows = 4});

  @override
  Widget build(BuildContext context) {
    return OwlListCard(children: [
      for (var i = 0; i < rows; i++)
        Container(
          constraints: BoxConstraints(minHeight: AppScale.rowHeight(context)),
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.cardPad, vertical: AppSpacing.rowPadV),
          child: Row(children: [
            const Expanded(child: Align(alignment: Alignment.centerLeft, child: OWLSkeleton.text(width: 120, height: 14))),
            const OWLSkeleton.text(width: 56, height: 14),
          ]),
        ),
    ]);
  }
}

/// P-F: ONE pinned summary line under the tabs of a screen: the SOURCE in small accent capitals (so a number is never anonymous), then 1 to 3 facts (value + small label),
/// or just a [note]. A hairline under it. It sits OUTSIDE the scroll list, so it stays on screen. Too long on a small phone = it shrinks, never wraps or overflows.
class OwlSummaryLine extends StatelessWidget {
  final String source;
  final List<OwlStat> facts;
  final String note;

  const OwlSummaryLine({super.key, required this.source, this.facts = const [], this.note = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    Color tone(String t) => t == 'good' ? p.profit : (t == 'bad' ? p.loss : p.textPrimary);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l, vertical: AppSpacing.s),
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.border))),
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Text(source.toUpperCase(), style: context.type.label.copyWith(fontSize: 10.5, letterSpacing: 1.0, fontWeight: FontWeight.w800, color: p.accent)),
          if (note.isNotEmpty) ...[const SizedBox(width: 10), Text(note, style: context.type.metadata)],
          for (final f in facts) ...[
            const SizedBox(width: 12),
            Text(f.value, style: context.type.number.copyWith(fontSize: 13, color: tone(f.tone))),
            const SizedBox(width: 4),
            Text(f.label, style: context.type.metadata),
          ],
        ]),
      ),
    );
  }
}
