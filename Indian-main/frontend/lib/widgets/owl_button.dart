import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

enum OWLButtonStyle { primary, secondary, danger, success }

/// Themed action button with a built-in loading state.
///
/// SAFETY: this widget only styles a tap. Destructive or real-money actions
/// (close, flatten, live-mode toggle) must still be gated by the caller's own
/// confirm dialog / hold-to-confirm - never pass a raw provider call here.
class OWLButton extends StatelessWidget {
  final String text;
  final VoidCallback? onPressed;
  final bool isLoading;
  final OWLButtonStyle style;
  final bool isFullWidth;
  final IconData? icon;

  const OWLButton({
    super.key,
    required this.text,
    this.onPressed,
    this.isLoading = false,
    this.style = OWLButtonStyle.primary,
    this.isFullWidth = false,
    this.icon,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;

    Color bg;
    Color fg;
    switch (style) {
      case OWLButtonStyle.secondary:
        bg = p.surfaceHigher;
        fg = p.textPrimary;
        break;
      case OWLButtonStyle.danger:
        bg = p.negative;
        fg = Colors.white;
        break;
      case OWLButtonStyle.success:
        bg = p.positive;
        fg = Colors.white;
        break;
      case OWLButtonStyle.primary:
        bg = p.accent;
        fg = Colors.white;
        break;
    }

    return SizedBox(
      width: isFullWidth ? double.infinity : null,
      height: 42,
      child: ElevatedButton(
        style: ElevatedButton.styleFrom(
          backgroundColor: bg,
          foregroundColor: fg,
          disabledBackgroundColor: bg.withOpacity(0.5),
          disabledForegroundColor: fg.withOpacity(0.7),
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
          textStyle: AppTypography.primaryData.copyWith(
            fontWeight: FontWeight.w700,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
          ),
        ),
        onPressed: isLoading ? null : onPressed,
        child: isLoading
            ? SizedBox(
                height: 18,
                width: 18,
                child: CircularProgressIndicator(strokeWidth: 2, color: fg),
              )
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (icon != null) ...[
                    Icon(icon, size: 16),
                    const SizedBox(width: 6),
                  ],
                  Flexible(
                    child: Text(text, maxLines: 1, overflow: TextOverflow.ellipsis),
                  ),
                ],
              ),
      ),
    );
  }
}
