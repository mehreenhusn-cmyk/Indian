import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// "Is the AI ready?" - a small card at the top of Bot vs AI.
///
/// It answers one question in plain words: is there enough data to trust the AI's result yet?
/// Everything comes from the backend (GET /api/ai/coach -> "ready", ai_coach.py _ready_view). This widget only draws it.
/// It never promises a profit and it never changes a trade. Few trades = "too little data", whatever the P&L says.
class AiReadyMeter extends StatelessWidget {
  final Map<String, dynamic> ready;
  const AiReadyMeter({super.key, required this.ready});

  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final level = (ready['level'] ?? 'low').toString();
    final n = _i(ready['n']);
    final need = _i(ready['need']) == 0 ? 100 : _i(ready['need']);
    final pct = (_n(ready['pct']) / 100.0).clamp(0.0, 1.0);
    final Color c = level == 'good' ? p.profit : (level == 'mid' ? p.warning : p.loss);
    final String head = level == 'good' ? 'ENOUGH DATA' : (level == 'mid' ? 'EARLY DATA' : 'TOO LITTLE DATA');
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: c.withOpacity(0.55), width: 1.3),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text('IS THE AI READY?', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: p.textMuted)),
          const Spacer(),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(6)),
            child: Text(head, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w900, letterSpacing: 0.5, color: c)),
          ),
        ]),
        const SizedBox(height: 10),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(value: pct, minHeight: 7, backgroundColor: p.border.withOpacity(0.6), valueColor: AlwaysStoppedAnimation<Color>(c)),
        ),
        const SizedBox(height: 6),
        Text(n >= need
            ? '$n finished trades with both a bot result and an AI result (enough: $need needed)'
            : '$n of $need finished trades with both a bot result and an AI result',
            style: TextStyle(fontSize: 11.5, color: p.textMuted)),
        const SizedBox(height: 8),
        Row(children: [
          _cell(p, 'AI better in', '${_i(ready['ai_better'])}', p.purple),
          const SizedBox(width: 18),
          _cell(p, 'Bot better in', '${_i(ready['bot_better'])}', p.warning),
        ]),
        const SizedBox(height: 8),
        Text((ready['text'] ?? '').toString(), style: TextStyle(fontSize: 12.5, height: 1.4, fontWeight: FontWeight.w600, color: p.textPrimary)),
      ]),
    );
  }

  Widget _cell(AppPalette p, String label, String value, Color c) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(label, style: TextStyle(fontSize: 11, color: p.textMuted)),
        Text(value, style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: c)),
      ]);
}
