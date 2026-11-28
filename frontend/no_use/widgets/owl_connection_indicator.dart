import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_eye_dot.dart';

/// Compact "BE • WS • 42 ms" health readout.
///
/// Every value comes from the caller (AppProvider.wsConnected /
/// wsLatencyMs etc.) - nothing here is hardcoded. When the latency is
/// unknown (socket down, no ping yet) it shows "--" instead of a fake number.
class OWLConnectionIndicator extends StatelessWidget {
  final bool isBackendLive;
  final bool isWsLive;
  final int? latency;

  const OWLConnectionIndicator({
    super.key,
    required this.isBackendLive,
    required this.isWsLive,
    this.latency,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final ms = latency;
    final hasLatency = isWsLive && ms != null;

    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        _dot(p, 'BE', isBackendLive),
        const SizedBox(width: 10),
        _dot(p, 'WS', isWsLive),
        const SizedBox(width: 10),
        Text(
          hasLatency ? '$ms ms' : '-- ms',
          style: AppTypography.metadata.copyWith(
            color: hasLatency ? _latencyColor(p, ms) : p.textMuted,
          ),
        ),
      ],
    );
  }

  Color _latencyColor(AppPalette p, int ms) {
    if (ms < 150) return p.positive;
    if (ms < 400) return p.warning;
    return p.negative;
  }

  Widget _dot(AppPalette p, String label, bool live) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(label, style: AppTypography.metadata.copyWith(color: p.textSecondary)),
        const SizedBox(width: 4),
        OwlEyeDot(live: live, color: live ? p.positive : p.negative, size: 7),
      ],
    );
  }
}
