import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

enum ConnectionStatus { live, connecting, offline }

/// Slim status strip shown at the very top only while the live feed is not
/// healthy. Collapses to zero height when [status] is live.
///
/// The caller owns the SafeArea (main.dart applies the top inset once around
/// the whole body), so this widget adds no inset of its own.
class OWLConnectionBanner extends StatelessWidget {
  final ConnectionStatus status;
  final VoidCallback? onRetry;

  const OWLConnectionBanner({
    super.key,
    required this.status,
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final isLive = status == ConnectionStatus.live;
    final isConnecting = status == ConnectionStatus.connecting;
    final color = isConnecting ? p.warning : p.negative;
    final message = isConnecting
        ? 'Live connection lost \u2014 reconnecting...'
        : 'Terminal offline \u2022 realtime feed paused';

    return AnimatedSize(
      duration: const Duration(milliseconds: 220),
      curve: Curves.easeOut,
      alignment: Alignment.topCenter,
      child: isLive
          ? const SizedBox(width: double.infinity)
          : Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.l,
                vertical: 6,
              ),
              color: color.withOpacity(0.12),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                  ),
                  const SizedBox(width: 8),
                  Flexible(
                    child: Text(
                      message,
                      overflow: TextOverflow.ellipsis,
                      style: AppTypography.metadata.copyWith(
                        color: color,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  if (!isConnecting && onRetry != null) ...[
                    const SizedBox(width: 10),
                    GestureDetector(
                      onTap: onRetry,
                      behavior: HitTestBehavior.opaque,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 4),
                        child: Text(
                          'RETRY',
                          style: AppTypography.metadata.copyWith(
                            color: p.accent,
                            fontWeight: FontWeight.w700,
                            decoration: TextDecoration.underline,
                          ),
                        ),
                      ),
                    ),
                  ],
                ],
              ),
            ),
    );
  }
}
