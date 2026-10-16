import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Dashboard "Live wallet" card - the REAL Binance USDT futures wallet (LIVE mode only).
/// Numbers come from the backend (status['live_wallet'], read in the background every few seconds).
/// If Binance cannot be read, the card says WHY (wrong key, no Futures permission, IP not allowed ...)
/// instead of staying blank.
class LiveWalletCard extends StatelessWidget {
  const LiveWalletCard({super.key});

  static String _fmt(dynamic v) {
    final d = (v is num) ? v.toDouble() : 0.0;
    return d.toStringAsFixed(2);
  }

  @override
  Widget build(BuildContext context) {
    return Selector<AppProvider, String>(
      selector: (_, p) {
        final w = p.liveWallet;
        if (w == null) return 'none';
        return '${w['ok']}|${w['wallet']}|${w['available']}|${w['unrealized']}|${w['margin_used']}|${w['error']}';
      },
      builder: (context, _, __) {
        final w = context.read<AppProvider>().liveWallet;
        if (w == null) return const SizedBox.shrink();
        final pal = context.palette;
        final ok = w['ok'] == true;
        final upnl = (w['unrealized'] is num) ? (w['unrealized'] as num).toDouble() : 0.0;
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: pal.surface,
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: pal.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text('Live wallet (Binance USDT)',
                      style: TextStyle(color: pal.textSecondary, fontSize: 12, fontWeight: FontWeight.w600)),
                  const Spacer(),
                  Text(ok ? 'REAL' : 'NO DATA',
                      style: TextStyle(color: ok ? pal.profit : pal.warning, fontSize: 11, fontWeight: FontWeight.w700)),
                ],
              ),
              const SizedBox(height: 8),
              if (!ok)
                Text(
                  (w['loading'] == true)
                      ? 'Loading wallet...'
                      : 'Could not read the wallet: ${w['error'] ?? 'unknown error'}',
                  style: TextStyle(color: pal.warning, fontSize: 12),
                )
              else ...[
                Text('${_fmt(w['wallet'])} USDT',
                    style: TextStyle(color: pal.textPrimary, fontSize: 24, fontWeight: FontWeight.w700)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    _cell(pal, 'Available', _fmt(w['available']), pal.textPrimary),
                    _cell(pal, 'In trades (margin)', _fmt(w['margin_used']), pal.textPrimary),
                    _cell(pal, 'Open P&L', (upnl >= 0 ? '+' : '') + _fmt(upnl), upnl >= 0 ? pal.profit : pal.loss),
                  ],
                ),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _cell(AppPalette pal, String label, String value, Color color) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(label, style: TextStyle(color: pal.textMuted, fontSize: 10.5)),
          const SizedBox(height: 2),
          Text(value, style: TextStyle(color: color, fontSize: 13.5, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}
