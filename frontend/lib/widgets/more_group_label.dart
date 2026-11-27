import 'package:flutter/material.dart';

import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';

/// Part 11 (D2b, 28 Nov 2026): the group heading of the More page: a short accent bar, the group name in small bold capitals
/// and, on the right, an optional muted note (for example a row count). Replaces the plain OwlSectionLabel on this page only.
/// Plain widget, no provider. Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.
class MoreGroupLabel extends StatelessWidget {
  final String title;
  final String note;

  const MoreGroupLabel(this.title, {super.key, this.note = ''});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.xl, bottom: AppSpacing.s),
      child: Row(children: [
        Container(width: 3, height: 14, decoration: BoxDecoration(color: p.accent, borderRadius: BorderRadius.circular(2))),
        const SizedBox(width: 8),
        Text(title.toUpperCase(), style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, letterSpacing: 0.9, color: p.textSecondary)),
        const Spacer(),
        if (note.isNotEmpty) Text(note, style: TextStyle(fontSize: 11.5, color: p.textMuted)),
      ]),
    );
  }
}
