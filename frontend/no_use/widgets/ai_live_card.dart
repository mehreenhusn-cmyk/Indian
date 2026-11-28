import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../screens/ai_live_screen.dart';
import '../theme/app_theme.dart';

/// REAL TRADING (Stage 2) summary in the Bot vs AI tab: is the AI trading its OWN Binance account, today's real P&L, open real trades.
/// The full controls (key, limits, ON switch, PANIC) are on the screen this card opens.
class AiLiveCard extends StatefulWidget {
  const AiLiveCard({super.key});

  @override
  State<AiLiveCard> createState() => _AiLiveCardState();
}

class _AiLiveCardState extends State<AiLiveCard> {
  Map<String, dynamic>? _d;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchAiLive();
    if (!mounted) return;
    setState(() => _d = r ?? _d);
  }

  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static double _n(dynamic v) => v is num ? v.toDouble() : (double.tryParse('$v') ?? 0);

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    final g = _m(d?['guard']);
    final on = g['enabled'] == true;
    final halted = '${g['halted'] ?? ''}'.isNotEmpty;
    final today = _m(d?['today']);
    final open = d?['open'] is List ? (d!['open'] as List).length : 0;
    final pnl = _n(today['pnl']);
    final hasKey = _m(d?['key'])['has'] == true;
    final status = d == null ? 'Loading...' : halted ? 'HALTED' : on ? 'ON' : 'OFF';
    final statusCol = halted ? p.loss : on ? p.profit : p.textMuted;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: halted ? p.loss : p.border, width: 0.8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('REAL TRADING (AI own account)', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted))),
          Text(status, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w900, color: statusCol)),
        ]),
        const SizedBox(height: 8),
        if (d != null && !hasKey)
          Text('Not set up. The AI only trades its paper account. To let it trade a separate Binance account, add that account\'s own API key.',
              style: TextStyle(fontSize: 12.5, height: 1.4, color: p.textPrimary))
        else if (d != null) ...[
          if (halted) Text('${g['halted']}', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.loss)),
          Row(children: [
            Expanded(child: _col(p, 'Real P&L today', '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT', pnl >= 0 ? p.profit : p.loss)),
            Expanded(child: _col(p, 'Open real trades', '$open', p.textPrimary)),
            Expanded(child: _col(p, 'Balance', d['balance'] == null ? '-' : _n(d['balance']).toStringAsFixed(2), p.textPrimary)),
          ]),
        ],
        const SizedBox(height: 8),
        OutlinedButton(
          onPressed: () async {
            await Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AiLiveScreen()));
            if (mounted) _load();
          },
          child: Text(hasKey ? 'Open real trading controls' : 'Set up real trading'),
        ),
      ]),
    );
  }

  Widget _col(AppPalette p, String label, String value, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 11, color: p.textMuted)),
        Text(value, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
      ]);
}
