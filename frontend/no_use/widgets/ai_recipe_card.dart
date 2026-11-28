import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// The RESULT card at the very top of Insights: "kaun se signal lo, kaun se skip, kahan exit".
/// One colored answer, not a table. Everything is computed on the backend (GET /api/ai/recipe,
/// see ai_recipe.py: found on the older 60% of lab signals, judged on the newer 40%, plus a luck test).
/// Display only - nothing here opens, blocks or closes a trade.
class AiRecipeCard extends StatefulWidget {
  final String tf;
  const AiRecipeCard({super.key, this.tf = ''});

  @override
  State<AiRecipeCard> createState() => _AiRecipeCardState();
}

class _AiRecipeCardState extends State<AiRecipeCard> {
  Map<String, dynamic>? _d;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(minutes: 5), (_) => _load());
  }

  @override
  void didUpdateWidget(covariant AiRecipeCard old) {
    super.didUpdateWidget(old);
    if (old.tf != widget.tf) _load();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchAiRecipe(tf: widget.tf);
    if (!mounted || r == null) return;
    setState(() => _d = r);
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<dynamic> _l(dynamic v) => v is List ? v : const [];

  String _pct(dynamic v) => '${_n(v) >= 0 ? '+' : ''}${_n(v).toStringAsFixed(1)}%';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    if (d == null) return const SizedBox.shrink();
    final v = (d['verdict'] ?? 'TOO_FEW').toString();
    final c = v == 'FOUND' ? p.profit : (v == 'NONE' ? p.loss : (v == 'MAYBE' ? p.warning : p.textMuted));
    final title = v == 'FOUND'
        ? 'SETUP MILA'
        : v == 'MAYBE'
            ? 'SHAYAD, PAKKA NAHI'
            : v == 'NONE'
                ? 'ABHI KOI SETUP NAHI'
                : 'KAM DATA';
    final rc = _m(d['recipe']);
    final test = _m(rc['test']);
    final base = _m(rc['base_test']);
    final steps = _l(d['steps']);
    final alts = _l(d['alts']);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: c.withOpacity(0.10),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
        border: Border.all(color: c.withOpacity(0.6), width: 1),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(v == 'FOUND' ? Icons.check_circle_rounded : (v == 'NONE' ? Icons.cancel_rounded : Icons.help_rounded),
              color: c, size: 20),
          const SizedBox(width: 8),
          Text(title, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w900, color: c, letterSpacing: 0.4)),
          const Spacer(),
          Text('${_i(d['signals'])} signals', style: context.type.metadata),
        ]),
        const SizedBox(height: 8),
        Text((d['headline'] ?? '').toString(), style: context.type.primary),
        if (rc.isNotEmpty && v != 'TOO_FEW') ...[
          const SizedBox(height: 10),
          Text('Kab lo:', style: context.type.metadata),
          for (final w in _l(rc['when_human']))
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('•  $w', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
            ),
          const SizedBox(height: 6),
          Text('Exit: ${rc['exit_nice']}', style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 10),
          Row(children: [
            _stat(context, p, 'Naye data pe', _pct(test['avg']), _n(test['avg']) >= 0 ? p.profit : p.loss),
            _stat(context, p, 'Sab signal lene pe', _pct(base['avg']), _n(base['avg']) >= 0 ? p.profit : p.loss),
            _stat(context, p, 'Trade', '${_i(test['n'])}', p.textPrimary),
            _stat(context, p, 'Luck chance', '${_n(rc['luck_pct']).toStringAsFixed(0)}%', p.textPrimary),
          ]),
          const SizedBox(height: 6),
          Text('Roz lagbhag ${_n(rc['per_day']).toStringAsFixed(0)} signal is rule se (kul ${_n(rc['all_per_day']).toStringAsFixed(0)}). '
              'ROI = fee ke baad, per trade.', style: context.type.metadata),
        ],
        if (steps.isNotEmpty) ...[
          const SizedBox(height: 10),
          Text('Ab kya karna hai:', style: context.type.metadata),
          for (final s in steps)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text('→  $s', style: context.type.secondary),
            ),
        ],
        if (alts.isNotEmpty)
          Theme(
            data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
            child: ExpansionTile(
              tilePadding: EdgeInsets.zero,
              childrenPadding: EdgeInsets.zero,
              title: Text('Aur 2 options (sirf dekhne ke liye)', style: context.type.metadata),
              children: [
                for (final a in alts)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                          '${_l(_m(a)['when_human']).join(' + ')}  |  ${_m(a)['exit_nice']}  |  naye data pe ${_pct(_m(_m(a)['test'])['avg'])} (${_i(_m(_m(a)['test'])['n'])} trade)',
                          style: context.type.secondary),
                    ),
                  ),
              ],
            ),
          ),
      ]),
    );
  }

  Widget _stat(BuildContext context, AppPalette p, String k, String v, Color c) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(v, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: c)),
          Text(k, style: context.type.metadata.copyWith(fontSize: 10)),
        ]),
      );
}
