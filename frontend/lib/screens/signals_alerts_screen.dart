import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../widgets/owl_pressable.dart';
import 'alerts_screen.dart';
import 'signals_screen.dart';

/// One tab for "what the bot saw" (Signals) and "what the bot did" (Alerts).
/// A two-button switch sits on top; the two screens below are the same ones as before,
/// only one of them is built at a time, so the tab stays light.
class SignalsAlertsScreen extends StatefulWidget {
  const SignalsAlertsScreen({super.key});

  @override
  State<SignalsAlertsScreen> createState() => _SignalsAlertsScreenState();
}

class _SignalsAlertsScreenState extends State<SignalsAlertsScreen> {
  /// Remembers the last choice, so coming back to this tab shows the same part.
  static int _lastSegment = 0;
  int _segment = _lastSegment;

  void _pick(int i) {
    if (i == _segment) return;
    _lastSegment = i;
    setState(() => _segment = i);
  }

  Widget _button(BuildContext context, int i, String label, IconData icon) {
    final p = context.palette;
    final on = _segment == i;
    return Expanded(
      child: OWLPressable(
        onTap: () => _pick(i),
        child: AnimatedContainer(
          duration: AppMotion.base,
          padding: const EdgeInsets.symmetric(vertical: 9),
          decoration: BoxDecoration(
            color: on ? p.accent.withOpacity(0.14) : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 16, color: on ? p.accent : p.textMuted),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: on ? FontWeight.w700 : FontWeight.w500,
                  color: on ? p.accent : p.textMuted,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 0),
            child: Container(
              padding: const EdgeInsets.all(3),
              decoration: BoxDecoration(
                color: p.surface,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: p.border, width: 1),
              ),
              child: Row(
                children: [
                  _button(context, 0, 'Signals', Icons.sensors_rounded),
                  _button(context, 1, 'Alerts', Icons.notifications_none_rounded),
                ],
              ),
            ),
          ),
          Expanded(
            child: KeyedSubtree(
              key: ValueKey<int>(_segment),
              child: _segment == 0 ? const SignalsScreen() : const AlertsScreen(),
            ),
          ),
        ],
      ),
    );
  }
}
