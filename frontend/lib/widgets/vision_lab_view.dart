import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_spacing.dart';
import 'owl_refresh.dart';

/// Lab page: the AI Own paper account (100 USDT), today's target / loss lock, what the AI is watching, and the
/// shadow results of every setup it has seen. Paper only. All numbers come from the backend (ai_capital / ai_candidates).
class VisionLabView extends StatefulWidget {
  const VisionLabView({super.key});

  @override
  State<VisionLabView> createState() => _VisionLabViewState();
}

class _VisionLabViewState extends State<VisionLabView> {
  Map<String, dynamic>? _data;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVisionLab();
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _data = r;
        _failed = false;
      } else if (_data == null) {
        _failed = true;
      }
    });
  }

  Map<String, dynamic> _m(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
  List _l(dynamic x) => x is List ? x : const [];
  double _d(dynamic x) => x is num ? x.toDouble() : (double.tryParse('$x') ?? 0.0);
  String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  String _hm(dynamic t) {
    final ms = (_d(t) * 1000).round();
    final dt = DateTime.fromMillisecondsSinceEpoch(ms);
    String two(int n) => n.toString().padLeft(2, '0');
    return '${two(dt.hour)}:${two(dt.minute)}';
  }

  Widget _card(AppPalette p, String title, List<Widget> kids, {Color? glow}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow.withOpacity(0.45) : p.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7)),
          const SizedBox(height: 8),
          ...kids,
        ],
      ),
    );
  }

  Widget _pill(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5), width: 0.7)),
        child: Text(text, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
      );

  Color _gradeColor(AppPalette p, String g) {
    switch (g) {
      case 'A':
        return p.profit;
      case 'C':
        return p.loss;
      case 'U':
        return p.warning;
      default:
        return p.textSecondary;
    }
  }

  Widget _capital(AppPalette p, Map<String, dynamic> c) {
    final net = _d(c['net']);
    final target = _d(c['target']);
    final lossLim = _d(c['loss_limit']);
    final state = (c['state'] ?? 'active').toString();
    final locked = state != 'active';
    final up = net >= 0;
    final frac = up ? (target > 0 ? (net / target).clamp(0.0, 1.0) : 0.0) : (lossLim > 0 ? (-net / lossLim).clamp(0.0, 1.0) : 0.0);
    final col = up ? p.profit : p.loss;
    final stateText = state == 'target_locked'
        ? 'TARGET REACHED - LOCKED'
        : (state == 'loss_locked' ? 'LOSS LIMIT - LOCKED' : 'ACTIVE');
    final stateCol = state == 'target_locked' ? p.profit : (state == 'loss_locked' ? p.loss : p.accent);
    return _card(
      p,
      'AI OWN PAPER ACCOUNT',
      [
        Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Text('${_d(c['balance']).toStringAsFixed(2)} USDT', style: TextStyle(color: p.textPrimary, fontSize: 22, fontWeight: FontWeight.w800)),
            const Spacer(),
            _pill(stateText, stateCol),
          ],
        ),
        const SizedBox(height: 10),
        Row(
          children: [
            Text('Today ${_sg(net)} USDT', style: TextStyle(color: col, fontWeight: FontWeight.w800, fontSize: 13)),
            const Spacer(),
            Text(up ? 'target +${target.toStringAsFixed(0)}' : 'loss limit -${lossLim.toStringAsFixed(0)}', style: context.type.metadata.copyWith(fontSize: 11)),
          ],
        ),
        const SizedBox(height: 6),
        ClipRRect(
          borderRadius: BorderRadius.circular(6),
          child: LinearProgressIndicator(value: frac, minHeight: 9, backgroundColor: p.border, valueColor: AlwaysStoppedAnimation<Color>(col)),
        ),
        const SizedBox(height: 8),
        Text(
          'Realized ${_sg(_d(c['realized']))}  ·  open ${_sg(_d(c['unrealized']))}  ·  ${_d(c['open']).toInt()}/${_d(c['max_open']).toInt()} open  ·  '
          '${_d(c['trades_today']).toInt()} trades today  ·  risk ${_d(c['risk']).toStringAsFixed(2)} USDT per trade',
          style: context.type.metadata.copyWith(height: 1.4, fontSize: 11.5),
        ),
        const SizedBox(height: 6),
        Text(
          locked
              ? 'No new AI Own trades until 5:30 AM IST. Open trades are still managed. What the AI learned is kept.'
              : 'The target is only a stop line. If no A-grade setup shows up, 0 today is a fine result.',
          style: context.type.metadata.copyWith(height: 1.4, fontSize: 11.5, color: p.textPrimary),
        ),
      ],
      glow: stateCol,
    );
  }

  Widget _shadow(AppPalette p, Map<String, dynamic> sh) {
    final by = _m(sh['by_src']);
    final rows = <List<Object>>[
      ['Bot signals', 'bot'],
      ['AI Own setups', 'own'],
      ['AI Own rejected (sample)', 'own_scan'],
    ];
    final kids = <Widget>[
      Text('${_d(sh['resolved']).toInt()} setups judged, ${_d(sh['pending']).toInt()} waiting for their candles. Same yardstick for every row: stop 1.5 ATR, target 2R, after fees.',
          style: context.type.metadata.copyWith(height: 1.4, fontSize: 11.5)),
      const SizedBox(height: 8),
    ];
    for (final r in rows) {
      final s = _m(by[r[1]]);
      final n = _d(s['n']).toInt();
      final avg = _d(s['avg_r']);
      kids.add(Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(r[0] as String, style: TextStyle(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w700)),
                  Text(n == 0 ? 'nothing judged yet' : '$n setups  ·  win ${s['win_rate']}%', style: context.type.metadata.copyWith(fontSize: 11)),
                ],
              ),
            ),
            Text(n == 0 ? '--' : '${_sg(avg)} R', style: TextStyle(color: n == 0 ? p.textMuted : (avg >= 0 ? p.profit : p.loss), fontWeight: FontWeight.w800, fontSize: 14)),
          ],
        ),
      ));
    }
    kids.add(Text('R = one stop distance. Average R per setup after fees. If "AI Own setups" beat "Bot signals" for a long time, the AI finds better entries by itself.',
        style: context.type.metadata.copyWith(height: 1.4, fontSize: 11)));
    return _card(p, 'WHO FINDS BETTER SETUPS? (SHADOW RESULT)', kids);
  }

  Widget _candidate(AppPalette p, Map<String, dynamic> c) {
    final stage = (c['stage'] ?? '').toString();
    final grade = (c['grade'] ?? '').toString();
    final sh = _m(c['shadow']);
    final stageCol = stage == 'TAKEN' ? p.profit : (stage == 'READY' ? p.accent : (stage == 'WATCH' ? p.warning : p.textSecondary));
    final why = (c['gate_note'] ?? '').toString().isNotEmpty ? c['gate_note'] : ((c['grade_why'] ?? '').toString().isNotEmpty ? c['grade_why'] : c['reason']);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: p.surfaceElevated, borderRadius: BorderRadius.circular(10), border: Border.all(color: p.border)),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(_hm(c['t']), style: TextStyle(color: p.textMuted, fontSize: 12)),
              const SizedBox(width: 8),
              Expanded(child: Text('${c['symbol'] ?? ''}  ${c['side'] ?? ''}  ·  ${c['src'] == 'own' ? 'AI Own' : 'bot'}', style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w600, fontSize: 13))),
              if (grade.isNotEmpty) ...[_pill('GRADE $grade', _gradeColor(p, grade)), const SizedBox(width: 6)],
              _pill(stage, stageCol),
            ],
          ),
          if ('$why'.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('$why', style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.3, fontSize: 11.5)),
          ],
          if (sh.containsKey('r'))
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text(
                'What happened next: ${_sg(_d(sh['r']))} R (${sh['o']}, best ${_d(sh['mfe']).toStringAsFixed(1)}R, worst ${_d(sh['mae']).toStringAsFixed(1)}R)',
                style: context.type.metadata.copyWith(fontSize: 11, color: _d(sh['r']) >= 0 ? p.profit : p.loss),
              ),
            ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (d == null) {
      return Center(
        child: _failed
            ? Column(mainAxisSize: MainAxisSize.min, children: [
                Text('Could not load the lab. It needs the newest backend.', style: context.type.metadata),
                TextButton(onPressed: _load, child: const Text('Retry')),
              ])
            : const CircularProgressIndicator(strokeWidth: 2),
      );
    }
    final cands = _l(d['candidates']).map(_m).toList();
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.s),
            child: Text('${d['note'] ?? ''}', style: context.type.metadata.copyWith(height: 1.4)),
          ),
          _capital(p, _m(d['capital'])),
          _shadow(p, _m(d['shadow'])),
          Padding(
            padding: const EdgeInsets.only(bottom: 6, top: 2),
            child: Text('What the AI is looking at', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
          ),
          if (cands.isEmpty)
            Padding(padding: const EdgeInsets.all(8), child: Text('No setups yet.', style: context.type.metadata)),
          for (final c in cands) _candidate(p, c),
        ],
      ),
    );
  }
}
