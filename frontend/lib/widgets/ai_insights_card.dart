import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import 'ai_verdict_card.dart';
import '../theme/app_theme.dart';
import 'owl_route.dart';

/// Dashboard "AI Insights" card - shows WHEN the strategy wins and loses.
///
/// Every number here comes from the backend's ai_stats.py via
/// GET /api/ai/insights (AppProvider.aiInsights): win rate by SD zone /
/// session / direction / EMA slope / volume surge, plus MFE/MAE. They are
/// the exact same numbers the AI Assistant is given, computed by code and
/// never by the AI. Nothing is estimated on the phone - when there is not
/// enough data the card says so instead of showing a pattern.
///
/// Compact only: badge + one-line best/weak hint. Tap opens the full
/// AiInsightsScreen (all the bars live there so the Dashboard stays short).
class AiInsightsCard extends StatefulWidget {
  const AiInsightsCard({super.key});

  @override
  State<AiInsightsCard> createState() => _AiInsightsCardState();
}

class _AiInsightsCardState extends State<AiInsightsCard> {
  Timer? _refresh;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.read<AppProvider>().fetchAiInsights();
    });
    // Closed trades change slowly - a 60s refresh is plenty.
    _refresh = Timer.periodic(const Duration(seconds: 60), (_) {
      if (mounted) context.read<AppProvider>().fetchAiInsights();
    });
  }

  @override
  void dispose() {
    _refresh?.cancel();
    super.dispose();
  }

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, Map<String, dynamic>?>(
      selector: (_, p) => p.aiInsights,
      shouldRebuild: (a, b) => !identical(a, b),
      builder: (context, _data, child) {
        final provider = context.read<AppProvider>();
        final data = provider.aiInsights;
        final sample = data == null ? 0 : _i(data['sample']);
        final minSample = data == null ? 30 : _i(data['min_sample']);
        final low = data == null ? true : (data['low_sample'] == true);
        final overall = (data != null && data['overall'] is Map)
            ? Map<String, dynamic>.from(data['overall'] as Map)
            : null;

        // ---- header badge ----
        Color badgeColor;
        String badgeText;
        if (data == null) {
          badgeColor = context.palette.textMuted;
          badgeText = 'Loading';
        } else if (sample == 0) {
          badgeColor = context.palette.textMuted;
          badgeText = 'No trades yet';
        } else if (low) {
          badgeColor = context.palette.warning;
          badgeText = 'Learning $sample/$minSample';
        } else {
          final wr = _d(overall?['win_rate']);
          badgeColor = wr >= 50 ? context.palette.profit : context.palette.loss;
          badgeText = 'Win ${wr.toStringAsFixed(0)}% (last $sample)';
        }
        // Bot-cycle phase (from the backend's archive stats): only shown when it
        // is worth a glance - CHOPPY (many quick stop-losses) or RECOVERING.
        final phase = (data?['cycle'] is Map) ? '${(data!['cycle'] as Map)['phase'] ?? ''}' : '';

        // ---- collapsed one-line hint ----
        String hint;
        if (data == null) {
          hint = 'Stats load ho rahe hain...';
        } else if (sample == 0) {
          hint = 'Trades band hone ke baad yahan patterns dikhenge.';
        } else if (data['best'] is Map && data['worst'] is Map) {
          final b = Map<String, dynamic>.from(data['best'] as Map);
          final w = Map<String, dynamic>.from(data['worst'] as Map);
          hint = 'Best: ${b['label']} ${_d(b['win_rate']).toStringAsFixed(0)}%'
              '  ·  Weak: ${w['label']} ${_d(w['win_rate']).toStringAsFixed(0)}%'
              '${low ? '  (tentative)' : ''}';
        } else {
          hint = '$sample closed trades - abhi group-wise pattern ke liye kam data.';
        }

        return Container(
          margin: const EdgeInsets.only(bottom: AppSpacing.l),
          decoration: BoxDecoration(
            color: context.palette.surface,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: context.palette.glassBorder, width: 1),
          ),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            onTap: () {
              AppHaptics.light();
              Navigator.of(context).push(OwlRoute(builder: (_) => const AiVerdictPage()));
            },
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.m - 2),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Icon(Icons.psychology_alt_outlined, size: 16, color: context.palette.accent),
                      const SizedBox(width: 8),
                      Text(
                        'AI Insights',
                        style: AppTypography.secondaryData.copyWith(
                          color: context.palette.textPrimary,
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const Spacer(),
                      if (phase == 'choppy' || phase == 'recovering') ...[
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                          decoration: BoxDecoration(
                            color: (phase == 'choppy' ? context.palette.warning : context.palette.profit).withOpacity(0.16),
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Text(
                            phase == 'choppy' ? 'CHOPPY' : 'RECOVERING',
                            style: AppTypography.metadata.copyWith(
                              color: phase == 'choppy' ? context.palette.warning : context.palette.profit,
                              fontSize: 10,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        const SizedBox(width: 6),
                      ],
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: badgeColor.withOpacity(0.16),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: Text(
                          badgeText,
                          style: AppTypography.metadata.copyWith(
                            color: badgeColor,
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ),
                      const SizedBox(width: 4),
                      Icon(Icons.chevron_right, color: context.palette.textMuted, size: 20),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    hint,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: AppTypography.metadata.copyWith(color: context.palette.textSecondary, fontSize: 12),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}
