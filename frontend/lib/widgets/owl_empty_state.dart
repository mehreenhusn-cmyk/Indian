import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import 'owl_button.dart';

/// Centered icon + title + subtitle (+ optional action) for empty lists.
class OWLEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const OWLEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.xxl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: p.surface,
                shape: BoxShape.circle,
                border: Border.all(color: p.border, width: 1),
                boxShadow: p.brightness == Brightness.light
                    ? [BoxShadow(color: const Color(0xFF101828).withOpacity(0.05), blurRadius: 16, offset: const Offset(0, 4))]
                    : null,
              ),
              child: Icon(icon, size: 28, color: p.textMuted),
            ),
            const SizedBox(height: AppSpacing.l),
            Text(title, style: t.section.copyWith(fontSize: 16, fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text(
              subtitle,
              textAlign: TextAlign.center,
              style: t.secondary.copyWith(color: p.textMuted, height: 1.4),
            ),
            if (actionLabel != null && onAction != null) ...[
              const SizedBox(height: AppSpacing.xl),
              OWLButton(
                text: actionLabel!,
                onPressed: onAction,
                style: OWLButtonStyle.secondary,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// UI5: one calm loading / failed note for every card and screen (small spinner + one line).
/// [inline] = left aligned, for inside a card; otherwise centered.
class OwlLoading extends StatelessWidget {
  final String text;
  final bool failed;
  final String failedText;
  final bool inline;

  const OwlLoading({
    super.key,
    this.text = 'Loading...',
    this.failed = false,
    this.failedText = 'No data from the backend. Pull down to try again.',
    this.inline = false,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final row = Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (!failed) ...[
          SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: p.textMuted)),
          const SizedBox(width: 10),
        ] else ...[
          Icon(Icons.cloud_off_rounded, size: 16, color: p.textMuted),
          const SizedBox(width: 8),
        ],
        Flexible(child: Text(failed ? failedText : text, style: context.type.secondary.copyWith(color: p.textMuted))),
      ],
    );
    return inline ? row : Center(child: Padding(padding: const EdgeInsets.all(AppSpacing.xl), child: row));
  }
}
