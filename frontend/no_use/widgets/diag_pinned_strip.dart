import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/diag_history.dart';
import '../models/diag_status.dart';
import '../providers/app_provider.dart';
import '../screens/diagnostics_screen.dart';
import '../theme/app_theme.dart';
import 'diagnostics_card.dart' show buildDiagStatus;
import 'owl_route.dart';

/// Part 26 (Diagnostics 4 of 4): the health strip PINNED at the top of the Dashboard.
/// Real cause of the old problem: the Diagnostics card was the LAST child of the Dashboard's
/// one big SingleChildScrollView, so the health line scrolled away with everything else.
/// Fix: this slim strip lives OUTSIDE that scroll view (Column: strip, then Expanded(scroll view)),
/// so it never moves; the long page scrolls under it. Nothing is faked: same buildDiagStatus()
/// as the card and the Part 25 page, so the three can never disagree.
/// Tap = open the Diagnostics page. Read-only.
class DiagPinnedStrip extends StatelessWidget {
  const DiagPinnedStrip({super.key});

  static Color _c(BuildContext context, DiagLevel l) {
    final p = context.palette;
    switch (l) {
      case DiagLevel.ok:
        return p.profit;
      case DiagLevel.warn:
        return p.warning;
      case DiagLevel.bad:
        return p.loss;
      default:
        return p.textMuted;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Consumer<AppProvider>(
      builder: (context, provider, child) {
        final diag = buildDiagStatus(provider);
        DiagHistory.instance.record(diag); // adds only on a level change
        final over = diag.overall;
        final text = over == DiagLevel.ok
            ? 'All 6 checks OK'
            : '${diag.count(DiagLevel.bad)} bad - ${diag.count(DiagLevel.warn)} warn - ${diag.count(DiagLevel.unknown)} unknown';
        return Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 0),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
            onTap: () {
              AppHaptics.light();
              Navigator.of(context).push(OwlRoute<void>(builder: (_) => const DiagnosticsScreen()));
            },
            child: Container(
              height: 34,
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m),
              decoration: BoxDecoration(
                color: p.surface,
                borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
                border: Border.all(color: _c(context, over).withOpacity(0.5), width: 1),
              ),
              child: Row(
                children: [
                  for (final i in diag.items)
                    Padding(
                      padding: const EdgeInsets.only(right: 4),
                      child: Container(width: 8, height: 8, decoration: BoxDecoration(color: _c(context, i.level), shape: BoxShape.circle)),
                    ),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(text,
                        overflow: TextOverflow.ellipsis,
                        style: AppTypography.metadata.copyWith(color: p.textPrimary, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                  Icon(Icons.chevron_right, size: 18, color: p.textMuted),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
