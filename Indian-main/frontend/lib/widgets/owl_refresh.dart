import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// Pull-down-to-refresh wrapper in the app's accent colour with a light
/// haptic when the refresh starts. The child MUST be scrollable - use
/// [OWLPullEmpty] to wrap empty states so they can be pulled too.
class OWLRefresh extends StatelessWidget {
  final Future<void> Function() onRefresh;
  final Widget child;

  const OWLRefresh({super.key, required this.onRefresh, required this.child});

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return RefreshIndicator(
      color: p.accent,
      backgroundColor: p.surfaceElevated,
      onRefresh: () async {
        AppHaptics.light();
        await onRefresh();
      },
      child: child,
    );
  }
}

/// Makes a non-scrolling widget (empty state, message) pull-to-refreshable.
class OWLPullEmpty extends StatelessWidget {
  final Widget child;
  const OWLPullEmpty({super.key, required this.child});

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, c) => SingleChildScrollView(
        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: c.maxHeight),
          child: Center(child: child),
        ),
      ),
    );
  }
}

/// Scroll physics that always allows the pull gesture, even for short lists.
// ClampingScrollPhysics = normal Android feel. BouncingScrollPhysics (iOS) flings very far on a long page,
// which sent the Dashboard all the way to the bottom after one swipe. Pull-to-refresh still works.
const ScrollPhysics owlPullPhysics =
    AlwaysScrollableScrollPhysics(parent: ClampingScrollPhysics());
