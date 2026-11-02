import 'package:flutter/material.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'verdict_badge.dart';

/// Round 7b: the PURPOSE STRIP at the top of every page (UI rules 1 and 10). Three short lines:
///   WHY     why this page was built
///   WHAT    what it shows
///   LATEST  the newest result: verdict badge + one line + n + date range
/// The texts come from the study registry (one entry per page), never typed per screen.
/// A missing text is simply left out; nothing prints "null" or "None".
class PurposeStrip extends StatelessWidget {
  final String why;
  final String what;
  final String? verdict;
  final String headline;
  final int n;
  final String range;

  const PurposeStrip({super.key, this.why = '', this.what = '', this.verdict, this.headline = '', this.n = 0, this.range = ''});

  Widget _row(BuildContext context, String tag, String text) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 52, child: Text(tag, style: context.type.label.copyWith(color: p.textMuted, fontWeight: FontWeight.w700, letterSpacing: 0.6))),
          Expanded(child: Text(text, style: context.type.secondary.copyWith(height: 1.25))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final meta = [if (n > 0) 'n = $n', if (range.isNotEmpty) range].join(' · ');
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.cardPad),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (why.isNotEmpty) _row(context, 'WHY', why),
          if (what.isNotEmpty) _row(context, 'WHAT', what),
          if (verdict != null || headline.isNotEmpty) ...[
            const SizedBox(height: 4),
            Row(
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                if (verdict != null) ...[VerdictBadge(verdict: verdict!, compact: true), const SizedBox(width: 8)],
                Expanded(child: Text(headline, maxLines: 2, overflow: TextOverflow.ellipsis, style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
              ],
            ),
            if (meta.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(meta, style: context.type.metadata)),
          ],
        ],
      ),
    );
  }
}
