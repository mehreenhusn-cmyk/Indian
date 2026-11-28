import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Round 11: gives a screen that has no header of its own (Owl Sniper, System Health) a title and a Material ancestor,
/// so it can sit in a bottom-bar tab. Screens that own a Scaffold (Study Lab hub, Settings and tools) do not need it.
class TabPage extends StatelessWidget {
  final String title;
  final Widget child;

  const TabPage({super.key, required this.title, required this.child});

  @override
  Widget build(BuildContext context) {
    return Material(
      type: MaterialType.transparency,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.m, AppSpacing.l, AppSpacing.xs),
            child: Text(title, style: context.type.section.copyWith(fontSize: 22, fontWeight: FontWeight.w800)),
          ),
          Expanded(child: child),
        ],
      ),
    );
  }
}
