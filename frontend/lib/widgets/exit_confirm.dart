import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/app_theme.dart';

/// Back-button rule shared by both markets.
///
/// Back never switches market. Order of steps:
///   1. a pushed page / open drawer closes first (Flutter does that itself),
///   2. on any tab except the first, Back goes to the first tab (Dash),
///   3. on the first tab, Back asks "Exit app?".
///
/// Each market screen registers a `goHome` callback while it is on screen. It returns true
/// when it moved to the first tab (so no dialog), false when it is already there.
class BackGuard {
  BackGuard._();

  static bool Function()? cryptoGoHome;
  static bool Function()? indiaGoHome;

  /// Called from the root PopScope. [market] is 'crypto' or 'india'.
  static Future<void> handleBack(BuildContext context, String market) async {
    final goHome = market == 'india' ? indiaGoHome : cryptoGoHome;
    if (goHome != null && goHome()) return;
    final exit = await ExitConfirm.ask(context);
    if (exit) SystemNavigator.pop();
  }
}

class ExitConfirm {
  ExitConfirm._();

  static bool _open = false; // a second Back press must not stack a second dialog

  /// Returns true only when the person taps "Exit".
  static Future<bool> ask(BuildContext context) async {
    if (_open) return false;
    _open = true;
    try {
      final r = await showDialog<bool>(
        context: context,
        builder: (ctx) {
          final p = ctx.palette;
          final t = ctx.type;
          return AlertDialog(
            backgroundColor: p.surfaceElevated,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(16),
              side: BorderSide(color: p.border),
            ),
            title: Text('Exit app?', style: t.section.copyWith(fontWeight: FontWeight.w700)),
            content: Text(
              'Your bot keeps running on the server. Only this screen will close.',
              style: t.secondary,
            ),
            actionsPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            actions: [
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(false),
                child: Text('Cancel', style: TextStyle(color: p.textSecondary, fontWeight: FontWeight.w700)),
              ),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: p.loss, foregroundColor: Colors.white),
                onPressed: () => Navigator.of(ctx).pop(true),
                child: const Text('Exit', style: TextStyle(fontWeight: FontWeight.w700)),
              ),
            ],
          );
        },
      );
      return r == true;
    } finally {
      _open = false;
    }
  }
}
