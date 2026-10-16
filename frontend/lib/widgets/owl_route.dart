import 'package:flutter/material.dart';

import '../theme/app_motion.dart';

/// Page route with a short fade + small upward slide. Runs on the GPU as a
/// plain opacity/translate on one layer, so it stays smooth on low-end
/// phones (no blur, no scale, no extra package). Use instead of
/// MaterialPageRoute for full-screen pushes.
class OwlRoute<T> extends PageRouteBuilder<T> {
  OwlRoute({required WidgetBuilder builder})
      : super(
          transitionDuration: AppMotion.slow,
          reverseTransitionDuration: AppMotion.base,
          pageBuilder: (context, animation, secondaryAnimation) => builder(context),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final curved = CurvedAnimation(parent: animation, curve: AppMotion.decel);
            return FadeTransition(
              opacity: curved,
              child: SlideTransition(
                position: Tween<Offset>(begin: const Offset(0, 0.04), end: Offset.zero).animate(curved),
                child: child,
              ),
            );
          },
        );
}
