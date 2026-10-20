import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import '../theme/app_motion.dart';
import 'live_ticker_bar.dart' show MarketModeSwitch;

/// Bottom bar of the India terminal: Dash | Chain | Trades | Stats | Settings.
/// Same idea as the crypto bottom bar (big targets, thumb reach, one tap per page). The selected page uses the
/// India saffron colour so one glance tells which market is on screen.
class IndiaBottomNav extends StatelessWidget {
  final int index;
  final ValueChanged<int> onTap;
  final int openTrades; // small dot on Trades while a position is open
  const IndiaBottomNav({super.key, required this.index, required this.onTap, this.openTrades = 0});

  static const _items = <(String, IconData, IconData)>[
    ('Dash', Icons.dashboard_outlined, Icons.dashboard_rounded),
    ('Chain', Icons.table_rows_outlined, Icons.table_rows_rounded),
    ('Trades', Icons.swap_vert_circle_outlined, Icons.swap_vert_circle_rounded),
    ('Stats', Icons.insights_outlined, Icons.insights_rounded),
    ('Settings', Icons.tune_outlined, Icons.tune_rounded),
  ];

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    const on = MarketModeSwitch.indiaColor;
    return Container(
      decoration: BoxDecoration(
        color: p.surface,
        border: Border(top: BorderSide(color: p.border)),
      ),
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 62,
          child: Row(
            children: List.generate(_items.length, (i) {
              final sel = i == index;
              final it = _items[i];
              return Expanded(
                child: InkWell(
                  onTap: () {
                    if (!sel) AppHaptics.light();
                    onTap(i);
                  },
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 160),
                        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
                        decoration: BoxDecoration(
                          color: sel ? on.withOpacity(0.18) : Colors.transparent,
                          borderRadius: BorderRadius.circular(14),
                        ),
                        child: Stack(clipBehavior: Clip.none, children: [
                          Icon(sel ? it.$3 : it.$2, size: 22, color: sel ? on : p.textSecondary),
                          if (i == 2 && openTrades > 0)
                            Positioned(
                              right: -4,
                              top: -2,
                              child: Container(
                                width: 8,
                                height: 8,
                                decoration: BoxDecoration(color: p.profit, shape: BoxShape.circle),
                              ),
                            ),
                        ]),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        it.$1,
                        maxLines: 1,
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: sel ? FontWeight.w800 : FontWeight.w600,
                          color: sel ? on : p.textSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
              );
            }),
          ),
        ),
      ),
    );
  }
}
