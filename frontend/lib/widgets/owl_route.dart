import 'package:flutter/material.dart';

import '../theme/app_motion2.dart';

/// Page route with a short fade + small upward slide. Runs on the GPU as a plain opacity / translate on one layer, so it stays smooth on low-end
/// phones (no blur, no scale, no extra package). Use instead of MaterialPageRoute for full-screen pushes.
/// P-F: the times now come from the premium motion tokens (open 250 ms, back 180 ms, ease-out) so every page push feels like the sheets and the bar.
/// The page UNDER the new one fades a little (secondaryAnimation), so the new page reads as "on top". Dart NOT compiled.
class OwlRoute<T> extends PageRouteBuilder<T> {
  OwlRoute({required WidgetBuilder builder})
      : super(
          transitionDuration: OwlMotion.slide,
          reverseTransitionDuration: OwlMotion.fade,
          pageBuilder: (context, animation, secondaryAnimation) => builder(context),
          transitionsBuilder: (context, animation, secondaryAnimation, child) {
            final curved = CurvedAnimation(parent: animation, curve: OwlMotion.smooth);
            final under = Tween<double>(begin: 1.0, end: 0.92).animate(CurvedAnimation(parent: secondaryAnimation, curve: OwlMotion.smooth));
            return FadeTransition(
              opacity: under,
              child: FadeTransition(
                opacity: curved,
                child: SlideTransition(
                  position: Tween<Offset>(begin: const Offset(0, 0.04), end: Offset.zero).animate(curved),
                  child: child,
                ),
              ),
            );
          },
        );
}
