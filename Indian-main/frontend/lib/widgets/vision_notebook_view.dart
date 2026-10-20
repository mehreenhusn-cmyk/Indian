import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../theme/app_motion.dart';
import '../theme/app_spacing.dart';
import 'owl_pressable.dart';
import 'owl_refresh.dart';

/// Vision AI "Notebook" tab: what the AI learned from its own closed trades.
///   Guide   - how to use EMA, TSI, Z-score and SD bands, plus what the AI found in its own closed trades (with / without each signal).
///   Rules   - plain-words rules the AI proposed. A rule switches ON by itself once its evidence is PROVEN (20+ trades, older and newer
///             halves agree, gap bigger than luck) and pauses by itself if it stops holding. You can still Delete any rule.
///   Lessons - one line per closed AI trade.
/// All text and numbers come from the backend (ai_vision_lessons.py). The phone only draws them and sends your tap.

Map<String, dynamic> _nm(dynamic x) => x is Map ? Map<String, dynamic>.from(x) : <String, dynamic>{};
List _nl(dynamic x) => x is List ? x : const [];
double _nd(dynamic x) => x is num ? x.toDouble() : (double.tryParse('$x') ?? 0.0);

class VisionNotebookView extends StatefulWidget {
  const VisionNotebookView({super.key});

  @override
  State<VisionNotebookView> createState() => _VisionNotebookViewState();
}

class _VisionNotebookViewState extends State<VisionNotebookView> {
  Map<String, dynamic>? _data;
  bool _failed = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) {
      if (mounted) _load();
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchVisionLessons();
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

  Future<void> _act(String id, String action) async {
    AppHaptics.light();
    final ok = await context.read<AppProvider>().actVisionRule(id, action);
    if (!mounted) return;
    if (!ok) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not save. Check the connection.')));
    }
    _load();
  }

  Widget _card(AppPalette p, {required Widget child, Color? glow}) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: AppSpacing.cardGap),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: glow != null ? glow.withOpacity(0.45) : p.border, width: 1),
      ),
      child: child,
    );
  }

  Widget _label(String text) => Padding(
        padding: const EdgeInsets.only(top: 6, bottom: 8),
        child: Text(text, style: context.type.metadata.copyWith(fontSize: 10, fontWeight: FontWeight.w700, letterSpacing: 0.7)),
      );

  Color _verdictColor(AppPalette p, String v) {
    switch (v) {
      case 'proven':
        return p.profit;
      case 'contradicted':
        return p.loss;
      case 'mixed':
        return p.warning;
      default:
        return p.textMuted;
    }
  }

  String _verdictWord(String v) {
    switch (v) {
      case 'proven':
        return 'PROVEN';
      case 'contradicted':
        return 'NOT SUPPORTED';
      case 'mixed':
        return 'NOT CLEAR';
      case 'no_tag':
        return 'JUDGEMENT';
      default:
        return 'UNPROVEN';
    }
  }

  Widget _smallButton(AppPalette p, String text, Color color, VoidCallback onTap) {
    return OWLPressable(
      pressedScale: 0.96,
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        decoration: BoxDecoration(
          color: color.withOpacity(0.14),
          borderRadius: BorderRadius.circular(AppSpacing.radiusSmall + 2),
          border: Border.all(color: color.withOpacity(0.5), width: 0.8),
        ),
        child: Text(text, style: TextStyle(color: color, fontWeight: FontWeight.w800, fontSize: 12)),
      ),
    );
  }

  Widget _ruleCard(AppPalette p, Map<String, dynamic> r) {
    final ev = _nm(r['evidence']);
    final verdict = (ev['verdict'] ?? 'unproven').toString();
    final status = (r['status'] ?? 'proposed').toString();
    final approved = status == 'approved' || status == 'auto';
    final isAuto = status == 'auto';
    final c = _verdictColor(p, verdict);
    final why = (r['why'] ?? '').toString();
    final tagText = (r['tag_text'] ?? '').toString();
    final n = _nd(ev['n']).toInt();
    final need = _nd(ev['need']).toInt();
    return _card(
      p,
      glow: approved ? p.accent : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(6)),
                child: Text(_verdictWord(verdict), style: TextStyle(color: c, fontSize: 10, fontWeight: FontWeight.w800, letterSpacing: 0.5)),
              ),
              const SizedBox(width: 8),
              Text((r['do'] ?? '') == 'take' ? 'TAKE rule' : 'SKIP rule', style: context.type.metadata.copyWith(fontSize: 10.5)),
              const Spacer(),
              if (approved) Text(isAuto ? 'ON (AUTO)' : 'ON', style: TextStyle(color: p.accent, fontSize: 10.5, fontWeight: FontWeight.w800)),
              if (status == 'paused') Text('PAUSED', style: TextStyle(color: p.warning, fontSize: 10.5, fontWeight: FontWeight.w800)),
            ],
          ),
          const SizedBox(height: 8),
          Text((r['text'] ?? '').toString(), style: TextStyle(color: p.textPrimary, fontSize: 14, fontWeight: FontWeight.w700, height: 1.3)),
          if (why.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(why, style: context.type.metadata.copyWith(height: 1.35)),
          ],
          const SizedBox(height: 8),
          Text((ev['text'] ?? '').toString(), style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.35)),
          if (tagText.isNotEmpty) ...[
            const SizedBox(height: 3),
            Text('Counted as: $tagText (${r['when'] == false ? 'false' : 'true'}).', style: context.type.metadata.copyWith(fontSize: 11, height: 1.35)),
          ],
          if (verdict == 'unproven' && need > 0) ...[
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: LinearProgressIndicator(value: (n / need).clamp(0.0, 1.0), minHeight: 5, backgroundColor: p.border, color: p.accent),
            ),
          ],
          const SizedBox(height: 10),
          Row(
            children: [
              if (status == 'approved') _smallButton(p, 'Stop using', p.warning, () => _act((r['id'] ?? '').toString(), 'propose')),
              if (status == 'approved') const SizedBox(width: 10),
              _smallButton(p, 'Delete', p.loss, () => _act((r['id'] ?? '').toString(), 'delete')),
            ],
          ),
        ],
      ),
    );
  }

  Color _guideColor(AppPalette p, String v) {
    switch (v) {
      case 'good':
        return p.profit;
      case 'bad':
        return p.loss;
      case 'hint':
        return p.warning;
      default:
        return p.textMuted;
    }
  }

  String _grp(Map<String, dynamic> g) {
    final n = _nd(g['n']).toInt();
    if (n == 0) return 'no trades';
    final avg = _nd(g['avg']);
    return '$n trades, ${_nd(g['wins']).toInt()} won, avg ${avg >= 0 ? '+' : ''}${avg.toStringAsFixed(2)} USDT';
  }

  Widget _guideCard(AppPalette p, Map<String, dynamic> g) {
    final fs = _nl(g['findings']).map(_nm).toList();
    return _card(
      p,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text((g['indicator'] ?? '').toString(), style: TextStyle(color: p.textPrimary, fontSize: 14.5, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          Text((g['how'] ?? '').toString(), style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4)),
          for (final f in fs) ...[
            const SizedBox(height: 10),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  margin: const EdgeInsets.only(top: 5, right: 8),
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(color: _guideColor(p, (f['verdict'] ?? '').toString()), shape: BoxShape.circle),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('When: ${f['text'] ?? ''}', style: TextStyle(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w700, height: 1.3)),
                      const SizedBox(height: 2),
                      Text('Yes: ${_grp(_nm(f['with']))}', style: context.type.metadata.copyWith(fontSize: 11, height: 1.35)),
                      Text('No: ${_grp(_nm(f['without']))}', style: context.type.metadata.copyWith(fontSize: 11, height: 1.35)),
                      Text((f['line'] ?? '').toString(), style: context.type.metadata.copyWith(fontSize: 11, height: 1.35, color: _guideColor(p, (f['verdict'] ?? '').toString()))),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _lessonRow(AppPalette p, Map<String, dynamic> x) {
    final pnl = _nd(x['pnl']);
    final win = pnl > 0;
    final feats = _nl(x['feat_text']).map((e) => e.toString()).toList();
    return _card(
      p,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('${x['symbol'] ?? ''}  ${x['side'] ?? ''}  ·  ${x['tf'] ?? ''}',
                    overflow: TextOverflow.ellipsis, style: TextStyle(color: p.textPrimary, fontWeight: FontWeight.w800, fontSize: 13)),
              ),
              Text('${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT', style: TextStyle(color: win ? p.profit : p.loss, fontWeight: FontWeight.w800, fontSize: 13)),
            ],
          ),
          const SizedBox(height: 6),
          Text((x['text'] ?? '').toString(), style: TextStyle(color: p.textPrimary, fontSize: 13, height: 1.35)),
          if (x['auto'] == true)
            Padding(
              padding: const EdgeInsets.only(top: 3),
              child: Text('Automatic note (the AI had no quota to write this one).', style: context.type.metadata.copyWith(fontSize: 10.5)),
            ),
          if (feats.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(feats.join('  ·  '), style: context.type.metadata.copyWith(fontSize: 10.5, height: 1.4)),
          ],
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
            ? Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('Could not reach the backend.', style: context.type.metadata),
                  const SizedBox(height: 8),
                  TextButton(onPressed: _load, child: const Text('Retry')),
                ],
              )
            : const CircularProgressIndicator(strokeWidth: 2),
      );
    }
    final rules = _nl(d['rules']).map(_nm).toList();
    final lessons = _nl(d['lessons']).map(_nm).toList();
    final guide = _nl(d['guide']).map(_nm).toList();
    final proposed = rules.where((r) => r['status'] != 'approved' && r['status'] != 'auto').toList();
    final approved = rules.where((r) => r['status'] == 'approved' || r['status'] == 'auto').toList();
    final minTrust = _nd(d['min_trust']).toInt();
    return OWLRefresh(
      onRefresh: _load,
      child: ListView(
        physics: owlPullPhysics,
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 96),
        children: [
          _card(
            p,
            child: Text(
              'The AI model itself cannot change. This notebook is how it learns: after every closed AI trade it writes one lesson. '
              'Once a day it turns repeated lessons into plain rules. You do not need to approve anything: a rule switches on by itself only after it is PROVEN '
              '($minTrust+ matching trades, older and newer halves agree, and the gap is bigger than luck). If it stops holding, it pauses by itself.',
              style: context.type.metadata.copyWith(color: p.textPrimary, height: 1.4),
            ),
          ),
          _label('HOW TO USE THE INDICATORS (${d['closed_n'] ?? 0} closed AI trades counted)'),
          for (final g in guide) _guideCard(p, g),
          _label('RULES BEING TESTED (${proposed.length}) - the AI does not read these yet'),
          if (proposed.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text((d['next_rules_note'] ?? 'No new rules yet.').toString(), style: context.type.metadata.copyWith(height: 1.4)),
            ),
          for (final r in proposed) _ruleCard(p, r),
          if (approved.isNotEmpty) _label('RULES THE AI READS NOW (${approved.length})'),
          for (final r in approved) _ruleCard(p, r),
          _label('LESSONS (${d['total'] ?? 0} total, newest first)'),
          if (lessons.isEmpty)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Text('Nothing yet. The first lesson appears after the first closed AI trade.', style: context.type.metadata.copyWith(height: 1.4)),
            ),
          for (final x in lessons) _lessonRow(p, x),
        ],
      ),
    );
  }
}
