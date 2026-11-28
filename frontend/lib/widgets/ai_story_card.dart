import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import 'ai_chat_popup.dart';

/// "Strategy kahan maar kha rahi hai": the ONE simple card that answers
///   1) where is the strategy losing money,
///   2) where does it earn,
///   3) for each losing spot: SKIP those trades, or CHANGE that part of the strategy?
/// Every number is counted by the backend (ai_stats.build_story) from closed trades - the
/// same lines are given to the chat AI, so you and the AI read the same facts. This widget
/// only draws them. Tap a row = ask the AI about exactly that spot.
/// compact = true (Overview): only the money-losing spots + a "poori kahani" link.
class AiStoryCard extends StatefulWidget {
  final bool compact;
  final VoidCallback? onMore;
  const AiStoryCard({super.key, this.compact = false, this.onMore});

  @override
  State<AiStoryCard> createState() => _AiStoryCardState();
}

class _AiStoryCardState extends State<AiStoryCard> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final pr = context.read<AppProvider>();
      if (pr.aiInsights == null) pr.fetchAiInsights();
    });
  }

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
        final raw = data == null ? null : data['story'];
        final Map<String, dynamic>? st = raw is Map ? Map<String, dynamic>.from(raw) : null;
        return Container(
          width: double.infinity,
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
            border: Border.all(color: p.purple.withOpacity(0.45), width: 1),
            boxShadow: [BoxShadow(color: p.purple.withOpacity(0.10), blurRadius: 18)],
          ),
          child: st == null ? _empty(context, data == null) : _body(context, st),
        );
      },
    );
  }

  Widget _head(BuildContext context, String right) {
    final p = context.palette;
    return Row(
      children: [
        Icon(Icons.auto_awesome_rounded, size: 15, color: p.purple),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            'STRATEGY KAHAN MAAR KHA RAHI HAI',
            style: AppTypography.metadata.copyWith(
                color: p.textMuted, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.6),
          ),
        ),
        if (right.isNotEmpty) Text(right, style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10)),
      ],
    );
  }

  Widget _empty(BuildContext context, bool loading) {
    final p = context.palette;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _head(context, ''),
        const SizedBox(height: 10),
        Text(
          loading
              ? 'Load ho raha hai...'
              : 'Abhi itne trades nahi hue ki saaf pata chale. Kuch aur trades band hone do.',
          style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12.5),
        ),
      ],
    );
  }

  Widget _body(BuildContext context, Map<String, dynamic> st) {
    final p = context.palette;
    final n = _i(st['n']);
    final net = _d(st['net']);
    final wins = _i(st['wins']);
    final killers = (st['killers'] is List) ? List<dynamic>.from(st['killers'] as List) : <dynamic>[];
    final earners = (st['earners'] is List) ? List<dynamic>.from(st['earners'] as List) : <dynamic>[];
    final netColor = net >= 0 ? p.profit : p.loss;

    final kids = <Widget>[
      _head(context, 'last $n trades'),
      const SizedBox(height: 10),
      Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text('${_sg(net)} USDT',
              style: AppTypography.primaryData.copyWith(color: netColor, fontSize: 26, fontWeight: FontWeight.w800)),
          const SizedBox(width: 10),
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Text('$wins jeete · ${n - wins} haare · ${_i(st['win_rate'])}%',
                style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5)),
          ),
        ],
      ),
    ];

    if (st['low'] == true) {
      kids.add(const SizedBox(height: 8));
      kids.add(_note(context, 'Trades kam hain ($n), neeche sab sirf ishaara hai, pakka nahi.', p.warning));
    }

    kids.add(_section(context, 'NUKSAAN YAHAN HO RAHA HAI', p.loss));
    if (killers.isEmpty) {
      kids.add(Text('Abhi koi ek jagah saaf nuksaan wali nahi mili.',
          style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12.5)));
    } else {
      for (final k in killers) {
        if (k is Map) kids.add(_row(context, Map<String, dynamic>.from(k), true));
      }
    }

    if (!widget.compact) {
      kids.add(_section(context, 'KAMAYI YAHAN HO RAHI HAI', p.profit));
      if (earners.isEmpty) {
        kids.add(Text('Abhi koi ek jagah saaf kamayi wali nahi mili.',
            style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12.5)));
      } else {
        for (final e in earners) {
          if (e is Map) kids.add(_row(context, Map<String, dynamic>.from(e), false));
        }
      }
      kids.add(const SizedBox(height: 10));
      kids.add(Text(
        'Skip = un trades ko chhodna. Badlo = strategy ka wo hissa (SL, zone, filter) badalna. '
        'Ye pichhle trades ka hisaab hai, bhavishya ki guarantee nahi. Alag-alag numbers jodo mat, kuch trade dono mein aa sakte hain.',
        style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5),
      ));
    }

    kids.add(const SizedBox(height: 10));
    kids.add(Row(
      children: [
        Expanded(
          child: OutlinedButton.icon(
            onPressed: () {
              AppHaptics.light();
              showAiChatPopup(context,
                  preset: 'Mere strategy ki sabse bade nuksaan wali jagah batao. Har ek ke liye simple Hindi mein batao: '
                      'wo trade skip karun ya strategy ka wo hissa badlun, aur kyun?');
            },
            icon: Icon(Icons.chat_bubble_outline_rounded, size: 15, color: p.purple),
            label: Text('AI se poocho', style: TextStyle(color: p.purple, fontWeight: FontWeight.w700, fontSize: 12.5)),
            style: OutlinedButton.styleFrom(
              side: BorderSide(color: p.purple.withOpacity(0.5)),
              padding: const EdgeInsets.symmetric(vertical: 10),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
            ),
          ),
        ),
        if (widget.compact && widget.onMore != null) ...[
          const SizedBox(width: 8),
          Expanded(
            child: OutlinedButton(
              onPressed: () {
                AppHaptics.light();
                widget.onMore!();
              },
              style: OutlinedButton.styleFrom(
                side: BorderSide(color: p.accent.withOpacity(0.5)),
                padding: const EdgeInsets.symmetric(vertical: 10),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
              ),
              child: Text('Poori kahani', style: TextStyle(color: p.accent, fontWeight: FontWeight.w700, fontSize: 12.5)),
            ),
          ),
        ],
      ],
    ));
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: kids);
  }

  Widget _section(BuildContext context, String text, Color c) {
    return Padding(
      padding: const EdgeInsets.only(top: 14, bottom: 6),
      child: Row(
        children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text(text,
              style: AppTypography.metadata.copyWith(
                  color: context.palette.textMuted, fontSize: 10.5, fontWeight: FontWeight.w800, letterSpacing: 0.6)),
        ],
      ),
    );
  }

  Widget _note(BuildContext context, String text, Color c) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(color: c.withOpacity(0.10), borderRadius: BorderRadius.circular(10)),
      child: Text(text, style: AppTypography.metadata.copyWith(color: c, fontSize: 11.5)),
    );
  }

  Widget _tag(String text, Color c) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.14), borderRadius: BorderRadius.circular(7)),
      child: Text(text, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
    );
  }

  Widget _row(BuildContext context, Map<String, dynamic> it, bool killer) {
    final p = context.palette;
    final pnl = _d(it['pnl']);
    final sure = it['sure'] == true;
    final skip = it['action'] == 'skip';
    final barColor = killer ? p.loss : p.profit;
    final title = '${it['title']}';
    final kids = <Widget>[
      Text(title, style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700)),
      const SizedBox(height: 3),
      Text('${_i(it['n'])} trade · ${_i(it['wins'])} jeete (${_i(it['win_rate'])}%) · ${_sg(pnl)} USDT',
          style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 12)),
    ];
    if (killer) {
      kids.add(const SizedBox(height: 6));
      kids.add(Wrap(
        spacing: 6,
        runSpacing: 4,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          _tag(skip ? 'SKIP KARKE DEKHO' : 'STRATEGY BADLO', skip ? p.warning : p.purple),
          _tag(sure ? 'PAKKA' : 'SIRF ISHAARA', sure ? p.textSecondary : p.textMuted),
        ],
      ));
      kids.add(const SizedBox(height: 4));
      kids.add(Text(
        'Pichhle trades mein ye na hota to ~${_sg(_d(it['effect']))} USDT behtar. ${it['hint'] ?? ''}',
        style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11),
      ));
    } else if (!sure) {
      kids.add(const SizedBox(height: 4));
      kids.add(_tag('SIRF ISHAARA', p.textMuted));
    }
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        AppHaptics.light();
        showAiChatPopup(context,
            preset: killer
                ? '"$title" mein mera strategy loss mein hai (${_i(it['n'])} trade, ${_sg(pnl)} USDT). '
                    'Isko skip karun ya strategy ka wo hissa badlun? Simple Hindi mein samjhao.'
                : '"$title" mein strategy kamayi kar rahi hai (${_i(it['n'])} trade, ${_sg(pnl)} USDT). Isse kya seekhna chahiye?');
      },
      child: Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.fromLTRB(10, 9, 10, 9),
        decoration: BoxDecoration(
          color: barColor.withOpacity(0.06),
          borderRadius: BorderRadius.circular(10),
          border: Border(left: BorderSide(color: barColor, width: 3)),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: kids),
      ),
    );
  }
}
