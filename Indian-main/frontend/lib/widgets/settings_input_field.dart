import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// One settings row: label on the left, compact right-aligned input on the
/// right. Theme-aware (light + dark). Pure UI - the caller owns the
/// controller and decides what "save" means, so existing change-receipt /
/// confirm logic in Settings is untouched.
class SettingsInputField extends StatelessWidget {
  final String label;
  final String? hint;
  final TextEditingController controller;
  final TextInputType keyboardType;
  final bool obscureText;
  final String? suffix;
  final bool enabled;
  final ValueChanged<String>? onChanged;

  /// Inline validation message shown under the row (red). Null = no error.
  final String? errorText;

  /// Muted hint under the row; hidden while [errorText] is showing.
  final String? helperText;

  /// True when the value differs from the saved baseline - shows a small
  /// accent dot next to the label.
  final bool changed;

  const SettingsInputField({
    super.key,
    required this.label,
    required this.controller,
    this.hint,
    this.keyboardType = TextInputType.text,
    this.obscureText = false,
    this.suffix,
    this.enabled = true,
    this.onChanged,
    this.errorText,
    this.helperText,
    this.changed = false,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;

    OutlineInputBorder border(Color c, [double w = 1]) => OutlineInputBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusSmall),
          borderSide: BorderSide(color: c, width: w),
        );

    final hasError = errorText != null && errorText!.isNotEmpty;
    final hasHelper = !hasError && helperText != null && helperText!.isNotEmpty;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.s),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
      Row(
        children: [
          Expanded(
            flex: 4,
            child: Row(
              children: [
                Flexible(
                  child: Text(
                    label,
                    style: AppTypography.secondaryData.copyWith(color: p.textSecondary),
                  ),
                ),
                if (changed) ...[
                  const SizedBox(width: 6),
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(color: p.accent, shape: BoxShape.circle),
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            flex: 5,
            child: SizedBox(
              height: 38,
              child: TextField(
                controller: controller,
                enabled: enabled,
                onChanged: onChanged,
                keyboardType: keyboardType,
                obscureText: obscureText,
                style: AppTypography.primaryData.copyWith(
                  fontSize: 13,
                  color: p.textPrimary,
                ),
                textAlign: TextAlign.right,
                cursorColor: p.accent,
                decoration: InputDecoration(
                  hintText: hint,
                  hintStyle: AppTypography.secondaryData.copyWith(color: p.textMuted),
                  suffixText: suffix != null ? ' $suffix' : null,
                  suffixStyle: AppTypography.metadata.copyWith(color: p.textSecondary),
                  isDense: true,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.m,
                    vertical: 8,
                  ),
                  filled: true,
                  fillColor: p.surfacePrimary,
                  border: border(p.border),
                  enabledBorder: border(p.border),
                  disabledBorder: border(p.border.withOpacity(0.5)),
                  focusedBorder: border(p.accent, 1.2),
                ),
              ),
            ),
          ),
        ],
      ),
          if (hasError || hasHelper)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                hasError ? errorText! : helperText!,
                textAlign: TextAlign.right,
                style: AppTypography.metadata.copyWith(
                  color: hasError ? p.loss : p.textMuted,
                ),
              ),
            ),
        ],
      ),
    );
  }
}
