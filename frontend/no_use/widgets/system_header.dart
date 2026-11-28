import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_connection_indicator.dart';
import 'owl_pressable.dart';
import 'owl_status_pill.dart';
import 'owl_terminal_logo.dart';

/// Top brand row: logo + OWL wordmark + LIVE/OFFLINE pill on the left,
/// connection health + bell on the right.
///
/// All state is passed in (feed it AppProvider.wsConnected / wsLatencyMs) -
/// nothing is assumed live. The "Live" pill follows [isWsLive].
class SystemHeader extends StatelessWidget {
  final bool isBackendLive;
  final bool isWsLive;
  final int? latency;
  final VoidCallback? onNotificationsTap;

  const SystemHeader({
    super.key,
    required this.isBackendLive,
    required this.isWsLive,
    this.latency,
    this.onNotificationsTap,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.l,
        vertical: AppSpacing.m,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Flexible(
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const OwlTerminalLogo(size: 26, showBackground: false, glowing: false),
                const SizedBox(width: AppSpacing.s),
                Text(
                  'OWL',
                  style: AppTypography.sectionHeading.copyWith(
                    color: p.textPrimary,
                    letterSpacing: 2,
                    fontWeight: FontWeight.w700,
                  ),
                ),
                const SizedBox(width: AppSpacing.m),
                OWLStatusPill(
                  text: isWsLive ? 'Live' : 'Offline',
                  color: isWsLive ? p.positive : p.textMuted,
                ),
              ],
            ),
          ),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              OWLConnectionIndicator(
                isBackendLive: isBackendLive,
                isWsLive: isWsLive,
                latency: latency,
              ),
              const SizedBox(width: AppSpacing.l),
              OWLPressable(
                onTap: onNotificationsTap,
                child: Padding(
                  padding: const EdgeInsets.all(4),
                  child: Icon(
                    Icons.notifications_none_rounded,
                    size: 20,
                    color: p.textSecondary,
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
