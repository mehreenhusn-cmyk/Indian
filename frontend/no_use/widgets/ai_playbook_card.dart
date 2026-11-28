import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'ai_chat_popup.dart';

/// PLAYBOOK: one card per scenario the AI found on its own (time block, session, SD zone, EMA,
/// volume, choppy/clean, SL distance - alone or as a combo of 2-3):
///   LO or CHHODO, when it happens, how it did, whether to HOLD or BOOK profit (TP1..TP4),
///   and how to improve it. Every number is counted by the backend (ai_playbook.py) from your
///   closed trades; the chat AI is given the same lines. PAKKA = found on older trades and still
///   true on newer ones. ISHAARA = not proven yet, can be luck. Tap a card = ask the AI about it.
class AiPlaybookCard extends StatelessWidget {
  const AiPlaybookCard({super.key});

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static String _sg(double v, {int digits = 0}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Selector<AppProvider, Map<String, dynamic>?>(
      selector: (_, pr) => pr.aiInsights,
      shouldRebuild: (a, b) => !identical(a, b),
      builder: (context, data, child) {
        final raw = data == null ? null : data['playbook'];
        if (raw is! Map) return const SizedBox.shrink();
        final pb = Map<String, dynamic>.from(raw);
        final list = (pb['scenarios'] is List) ? List<dynamic>.from(pb['scenarios'] as List) : <dynamic>[];
        final take = list.where((s) => s is Map && s['kind'] == 'TAKE').toList();
        final avoid = list.where((s) => s is Map && s['kind'] == 'AVOID').toList();
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
            border: Border.all(color: p.accent.withOpacity(0.45), width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(Icons.menu_book_rounded, size: 15, color: p.accent),
                const SizedBox(width: 6),
                Expanded(
                  child: Text('PLAYBOOK: KAB LO, KAB CHHODO, HOLD YA BOOK',
                      style: AppTypography.metadata.copyWith(
                          color: p.textMuted, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.6)),
                ),
              ]),
              const SizedBox(height: 8),
              if (pb['ready'] != true)
                Text(
                  'AI abhi seekh raha hai: ${_i(pb['n'])} trades hain, kam se kam ${_i(pb['min_total'])} chahiye. '
                      'Tab tak koi scenario nahi banega.',
                  style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12.5),
                )
              else ...[
                Text(
                  'AI ne khud scenario dhoondhe (time, session, zone, EMA, volume, combo) aur purane trades par '
                  'mila hua naye trades par dobara jaancha. PAKKA = naye par bhi chala. ISHAARA = abhi pakka nahi, luck ho sakta hai.',
                  style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11),
                ),
                _section(context, 'KAB PROFIT DETI HAI (LO)', p.profit),
                if (take.isEmpty)
                  _none(context, 'Abhi koi scenario nahi mila jo paisa kama raha ho.')
                else
                  for (final s in take) _scenario(context, Map<String, dynamic>.from(s as Map)),
                _section(context, 'KAB NUKSAAN DETI HAI (CHHODO)', p.loss),
                if (avoid.isEmpty)
                  _none(context, 'Abhi koi scenario nahi mila jo saaf nuksaan kar raha ho.')
                else
                  for (final s in avoid) _scenario(context, Map<String, dynamic>.from(s as Map)),
                if ((pb['overall_text'] is List) && (pb['overall_text'] as List).isNotEmpty) ...[
                  _section(context, 'SAB TRADES MILAKE: HOLD YA BOOK', p.accent),
                  for (final l in (pb['overall_text'] as List))
                    Padding(
                      padding: const EdgeInsets.only(bottom: 4),
                      child: Text('$l', style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12)),
                    ),
                ],
                const SizedBox(height: 8),
                Text('${pb['note'] ?? ''}', style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5)),
              ],
            ],
          ),
        );
      },
    );
  }

  Widget _section(BuildContext context, String text, Color c) {
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 6),
      child: Row(children: [
        Container(width: 6, height: 6, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
        const SizedBox(width: 6),
        Text(text,
            style: AppTypography.metadata.copyWith(
                color: context.palette.textMuted, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.6)),
      ]),
    );
  }

  Widget _none(BuildContext context, String t) =>
      Text(t, style: AppTypography.metadata.copyWith(color: context.palette.textSecondary, fontSize: 12.5));

  Widget _tag(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(7)),
        child: Text(text, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
      );

  Widget _scenario(BuildContext context, Map<String, dynamic> s) {
    final p = context.palette;
    final take = s['kind'] == 'TAKE';
    final c = take ? p.profit : p.loss;
    final pakka = s['tier'] == 'PAKKA';
    final pnl = _d(s['pnl']);
    final plan = (s['plan_text'] is List) ? List<dynamic>.from(s['plan_text'] as List) : <dynamic>[];
    final name = '${s['name']}';
    final oldA = s['avg_old'] is num ? _d(s['avg_old']) : null;
    final newA = s['avg_new'] is num ? _d(s['avg_new']) : null;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        AppHaptics.light();
        showAiChatPopup(context,
            preset: 'Playbook scenario: "$name" (${_i(s['n'])} trade, ${_sg(pnl)} USDT). '
                'Isme mujhe kya karna chahiye: lo ya chhodo, hold karun ya profit book karun, aur strategy kaise improve karun? '
                'Simple Hindi mein samjhao.');
      },
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
        decoration: BoxDecoration(
          color: c.withOpacity(0.06),
          borderRadius: BorderRadius.circular(10),
          border: Border(left: BorderSide(color: c, width: 3)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
              _tag(take ? 'LO' : 'CHHODO', c),
              _tag(pakka ? 'PAKKA' : 'ISHAARA', pakka ? p.textSecondary : p.warning),
            ]),
            const SizedBox(height: 6),
            Text(name,
                style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700)),
            const SizedBox(height: 3),
            Text('${_i(s['n'])} trade · ${_i(s['wins'])} jeete (${_i(s['win_rate'])}%) · ${_sg(pnl)} USDT',
                style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12)),
            if (oldA != null)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(
                  'Purane trades avg ROI ${_sg(oldA, digits: 1)}%'
                  '${newA != null ? ' · naye trades ${_sg(newA, digits: 1)}%' : ' · naye trades abhi kam'}',
                  style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11),
                ),
              ),
            const SizedBox(height: 6),
            for (final l in plan)
              Padding(
                padding: const EdgeInsets.only(bottom: 3),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Icon(Icons.flag_rounded, size: 12, color: p.accent),
                  const SizedBox(width: 5),
                  Expanded(
                    child: Text('$l', style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5)),
                  ),
                ]),
              ),
            Text('Improve: ${s['improve']}',
                style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11)),
          ],
        ),
      ),
    );
  }
}


/// AI KE RULE: the rules the AI wrote from the playbook (SKIP / TPk par book) and what they
/// would have done: "agar ye sab lagte to P&L X ki jagah Y hota", each trade counted once.
/// Old vs new trades shown separately. SCOREBOARD per rule = only trades that closed AFTER the
/// rule was first proposed. ADVICE ONLY: nothing here is applied to the bot.
class AiRulesCard extends StatelessWidget {
  const AiRulesCard({super.key});

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static String _sg(double v, {int digits = 0}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Selector<AppProvider, Map<String, dynamic>?>(
      selector: (_, pr) => pr.aiInsights,
      shouldRebuild: (a, b) => !identical(a, b),
      builder: (context, data, child) {
        final raw = data == null ? null : data['rules'];
        if (raw is! Map || raw['ready'] != true) return const SizedBox.shrink();
        final rs = Map<String, dynamic>.from(raw);
        final all = Map<String, dynamic>.from((rs['all'] as Map?) ?? {});
        final pk = Map<String, dynamic>.from((rs['pakka'] as Map?) ?? {});
        final rules = (rs['rules'] is List) ? List<dynamic>.from(rs['rules'] as List) : <dynamic>[];
        if (rules.isEmpty) return const SizedBox.shrink();
        final base = _d(rs['base']);
        final wouldBe = _d(all['would_be']);
        final total = _d(all['total']);
        return Container(
          width: double.infinity,
          margin: const EdgeInsets.only(top: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
            border: Border.all(color: p.profit.withOpacity(0.45), width: 1),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(children: [
                Icon(Icons.rule_rounded, size: 15, color: p.profit),
                const SizedBox(width: 6),
                Expanded(
                  child: Text('AI KE RULE: AGAR YE LAGTE TO',
                      style: AppTypography.metadata.copyWith(
                          color: p.textMuted, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.6)),
                ),
              ]),
              const SizedBox(height: 8),
              Text('${_sg(base)}  ->  ${_sg(wouldBe)} USDT',
                  style: AppTypography.primaryData.copyWith(color: wouldBe >= base ? p.profit : p.loss, fontSize: 22, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(
                'Pichhle ${_i(rs['n'])} trade. Badlav ${_sg(total)} USDT: skip se ${_sg(_d(all['skip_effect']))} '
                '(${_i(all['skip_n'])} trade), TP par book se ${_sg(_d(all['book_effect']))} (${_i(all['book_n'])} trade).',
                style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12),
              ),
              const SizedBox(height: 4),
              Text(
                'Purane trades par ${_sg(_d(all['total_old']))}, naye trades par ${_sg(_d(all['total_new']))}. '
                'Sirf PAKKA rules se ${_sg(_d(pk['total']))}. Har trade sirf ek baar ginta gaya.',
                style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11),
              ),
              const SizedBox(height: 10),
              for (final r in rules) if (r is Map) _rule(context, Map<String, dynamic>.from(r)),
              Text('${rs['note'] ?? ''}', style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5)),
              const SizedBox(height: 10),
              OutlinedButton.icon(
                onPressed: () {
                  AppHaptics.light();
                  showAiChatPopup(context,
                      preset: 'Mere AI rules dekho. Har rule ke liye batao: leak kahan hai, skip karun ya beech mein TP par '
                          'profit book karun, aur kaun sa rule pakka hai kaun sirf ishaara? Simple Hindi mein.');
                },
                icon: Icon(Icons.chat_bubble_outline_rounded, size: 15, color: p.purple),
                label: Text('AI se rules samjho', style: TextStyle(color: p.purple, fontWeight: FontWeight.w700, fontSize: 12.5)),
                style: OutlinedButton.styleFrom(
                  minimumSize: const Size.fromHeight(40),
                  side: BorderSide(color: p.purple.withOpacity(0.5)),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _tag(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(7)),
        child: Text(text, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
      );

  Widget _rule(BuildContext context, Map<String, dynamic> r) {
    final p = context.palette;
    final skip = r['type'] == 'SKIP';
    final pakka = r['tier'] == 'PAKKA';
    final sc = Map<String, dynamic>.from((r['score'] as Map?) ?? {});
    final verdict = '${sc['verdict']}';
    final vColor = verdict == 'CHAL RAHA' ? p.profit : (verdict == 'NAHI CHALA' ? p.loss : p.textMuted);
    final c = skip ? p.warning : p.accent;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
      decoration: BoxDecoration(
        color: c.withOpacity(0.06),
        borderRadius: BorderRadius.circular(10),
        border: Border(left: BorderSide(color: c, width: 3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(spacing: 6, runSpacing: 4, children: [
            _tag(skip ? 'SKIP' : 'TP PAR BOOK', c),
            _tag(pakka ? 'PAKKA' : 'ISHAARA', pakka ? p.textSecondary : p.warning),
            _tag(verdict == 'COLLECTING' ? 'SEEKH RAHA' : verdict, vColor),
          ]),
          const SizedBox(height: 6),
          Text('${r['text']}',
              style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700)),
          const SizedBox(height: 3),
          Text('${_i(r['n'])} trade · asar ${_sg(_d(r['effect']))} USDT (purane ${_sg(_d(r['effect_old']))}, naye ${_sg(_d(r['effect_new']))})',
              style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12)),
          const SizedBox(height: 2),
          Text(
            verdict == 'COLLECTING'
                ? 'Scoreboard: rule bane ke baad ${_i(sc['n'])}/${_i(sc['need'])} naye trade mile, abhi nateeja nahi.'
                : 'Scoreboard: rule bane ke baad ${_i(sc['n'])} naye trade, asar ${_sg(_d(sc['effect']))} USDT.',
            style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11),
          ),
        ],
      ),
    );
  }
}
