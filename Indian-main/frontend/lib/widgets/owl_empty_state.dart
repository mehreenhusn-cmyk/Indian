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
                color: p.surfaceElevated,
                shape: BoxShape.circle,
                border: Border.all(color: p.border, width: 1),
              ),
              child: Icon(icon, size: 28, color: p.textMuted),
            ),
            const SizedBox(height: AppSpacing.l),
            Text(title, style: t.section.copyWith(fontSize: 15)),
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
