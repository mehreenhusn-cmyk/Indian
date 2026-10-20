import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'backend_status_panel.dart';
import 'owl_route.dart';
import '../screens/ai_assistant_screen.dart';
import '../services/market_mode.dart';

/// Left-side swipe drawer, reachable from any screen (it lives on
/// MainScreen's own Scaffold in main.dart, underneath every tab).
///
///   - Header: OWL Terminal identity + live WebSocket status - a pulsing
///     dot (green = connected / red = offline) plus the round-trip ping in
///     ms once the first pong has arrived (see AppProvider.wsConnected /
///     wsLatencyMs, fed by websocket_service.dart's sendPing()/onLatency
///     wiring in main.dart).
///   - Exchange: OWL Terminal is hard-locked to Binance Futures. The old
///     KuCoin/Binance exchange switcher (and its POST /api/exchange/switch
///     round trip) was removed in the Batch 3 KuCoin purge, so this is now
///     a static, non-interactive glass chip confirming which exchange is
///     active - not a control.
///   - Bottom: Quick AI Assistant access - opens the chat from wherever the
///     user currently is, instead of having to go through Settings first.
class OwlDrawer extends StatelessWidget {
  const OwlDrawer({super.key});

  @override
  Widget build(BuildContext context) {
    return Drawer(
      backgroundColor: context.palette.bg,
      child: SafeArea(
        child: Selector<AppProvider, int>(
          selector: (_, p) => Object.hash(p.wsConnected, p.wsLatencyMs),
          builder: (context, _k, child) {
            final provider = context.read<AppProvider>();
            final connected = provider.wsConnected;
            final latency = provider.wsLatencyMs;
            final p = context.palette;
            final t = context.type;
            final statusColor = connected ? p.profit : p.loss;

            return Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // ---- Header: Terminal identity + live connection status ----
                Container(
                  padding: const EdgeInsets.all(AppSpacing.l),
                  decoration: BoxDecoration(
                    border: Border(bottom: BorderSide(color: p.border)),
                  ),
                  child: Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(AppSpacing.s),
                        decoration: BoxDecoration(
                          color: p.accent.withOpacity(0.15),
                          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
                          border: Border.all(color: p.accent.withOpacity(0.4)),
                        ),
                        child: Icon(Icons.bolt, color: p.accent, size: 24),
                      ),
                      const SizedBox(width: AppSpacing.m),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              'OWL TERMINAL',
                              style: t.section.copyWith(
                                fontWeight: FontWeight.w700,
                                letterSpacing: 1.2,
                              ),
                            ),
                            const SizedBox(height: 2),
                            Row(
                              children: [
                                AnimatedContainer(
                                  duration: AppMotion.slow,
                                  width: 8,
                                  height: 8,
                                  decoration: BoxDecoration(
                                    shape: BoxShape.circle,
                                    color: statusColor,
                                    boxShadow: [
                                      BoxShadow(
                                        color: statusColor.withOpacity(0.6),
                                        blurRadius: 6,
                                      ),
                                    ],
                                  ),
                                ),
                                const SizedBox(width: 6),
                                Text(
                                  connected
                                      ? (latency != null ? 'ONLINE · ${latency}ms' : 'ONLINE')
                                      : 'OFFLINE',
                                  style: AppTypography.metadata.copyWith(
                                    color: statusColor,
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),

                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.all(AppSpacing.l),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // ---- Market switch: Crypto (this app) / India Paper ----
                        Text(
                          'MARKET',
                          style: t.metadata.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.1,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.m - 2),
                        Row(
                          children: [
                            Expanded(
                              child: _MarketSwitchChip(
                                label: 'Crypto',
                                icon: Icons.currency_bitcoin,
                                selected: true,
                                onTap: () => Navigator.of(context).pop(),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.s),
                            Expanded(
                              child: _MarketSwitchChip(
                                label: 'India Paper',
                                icon: Icons.show_chart,
                                selected: false,
                                onTap: () {
                                  AppHaptics.light();
                                  Navigator.of(context).pop(); // close the drawer first
                                  MarketMode.set('india'); // India is a top-level market, not a pushed page
                                },
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.l),

                        // ---- Backend status (swipe-from-left panel) ----
                        Text(
                          'BACKEND',
                          style: t.metadata.copyWith(
                            fontWeight: FontWeight.w700,
                            letterSpacing: 1.1,
                          ),
                        ),
                        const SizedBox(height: AppSpacing.m - 2),
                        const BackendStatusPanel(),
                      ],
                    ),
                  ),
                ),

                // ---- Quick navigation ----
                Divider(color: p.border, height: 1),
                ListTile(
                  leading: Icon(Icons.smart_toy_outlined, color: p.accent),
                  title: Text('AI Assistant', style: t.primary),
                  subtitle: Text('Ask a quick question', style: t.secondary.copyWith(fontSize: 12)),
                  onTap: () {
                    AppHaptics.light();
                    Navigator.of(context).pop(); // close the drawer first
                    Navigator.of(context).push(
                      OwlRoute(builder: (_) => const AiAssistantScreen()),
                    );
                  },
                ),
                const SizedBox(height: AppSpacing.m),
              ],
            );
          },
        ),
      ),
    );
  }
}


class _MarketSwitchChip extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  const _MarketSwitchChip({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.m - 2),
        decoration: BoxDecoration(
          color: selected ? p.accent.withOpacity(0.15) : Colors.transparent,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          border: Border.all(color: selected ? p.accent : p.border),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 16, color: selected ? p.accent : p.textSecondary),
            const SizedBox(width: 6),
            Text(
              label,
              style: t.primary.copyWith(
                fontWeight: FontWeight.w700,
                color: selected ? p.accent : p.textSecondary,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
