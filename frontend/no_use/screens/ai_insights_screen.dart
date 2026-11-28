import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_route.dart';
import '../widgets/ai_chat_popup.dart';
import '../widgets/ai_story_card.dart';
import '../widgets/ai_playbook_card.dart';
import 'ai_assistant_screen.dart';

/// Full AI Insights page (opened from the Dashboard's compact AI Insights
/// card). Same numbers as before - computed by the backend's ai_stats.py and
/// served at GET /api/ai/insights (AppProvider.aiInsights); nothing is
/// calculated on the phone and the AI never invents them. This page only
/// changes WHERE they are shown, so the Dashboard stays short.
class AiInsightsScreen extends StatefulWidget {
  /// true when shown inside the AI tab (no own Scaffold / app bar).
  final bool embedded;

  /// Tap on a group row -> open the Trade Book filtered to that group
  /// (kind = direction/session/zone/timeframe/sl_dist/volume, label as shown).
  final void Function(String kind, String label)? onJump;
  const AiInsightsScreen({super.key, this.embedded = false, this.onJump});

  @override
  State<AiInsightsScreen> createState() => _AiInsightsScreenState();
}

class _AiInsightsScreenState extends State<AiInsightsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.read<AppProvider>().fetchAiInsights();
    });
  }

  // Set at the top of _buildDetails: break-even win-rate from the payoff (used for the
  // bar marker) and the minimum trades before a group is trusted.
  double? _be;
  int _minN = 30;

  // What-if mode: row tap picks ONE group and shows what the P&L would have been had the
  // bot skipped it (numbers from the backend group row). Off = row tap opens the Trade Book.
  // Simple view first: the story card on top, everything else behind "Aur details dekho".
  bool _showAll = false;

  bool _whatIf = false;
  String? _pickKind;
  String? _pickLabel;

  static double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;

  static String _signed(double v, {int digits = 2}) =>
      '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}';

  @override
  Widget build(BuildContext context) {
    final body = Selector<AppProvider, Map<String, dynamic>?>(
          selector: (_, p) => p.aiInsights,
          shouldRebuild: (a, b) => !identical(a, b),
          builder: (context, _data, child) {
            final provider = context.read<AppProvider>();
            final data = provider.aiInsights;
            final sample = data == null ? 0 : _i(data['sample']);
            final minSample = data == null ? 30 : _i(data['min_sample']);
            final low = data == null ? true : (data['low_sample'] == true);
            final overall = (data != null && data['overall'] is Map)
                ? Map<String, dynamic>.from(data['overall'] as Map)
                : null;

            return OWLRefresh(
              onRefresh: () => provider.fetchAiInsights(),
              child: ListView(
                physics: owlPullPhysics,
                padding: EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, widget.embedded ? 96 : AppSpacing.xl),
                children: [
                  if (!widget.embedded) _askAiButton(context),
                  if (data == null)
                    Padding(
                      padding: const EdgeInsets.only(top: 40),
                      child: Center(
                        child: Text('Stats load ho rahe hain...',
                            style: context.type.secondary.copyWith(color: context.palette.textMuted)),
                      ),
                    )
                  else if (sample == 0)
                    Padding(
                      padding: const EdgeInsets.only(top: 40),
                      child: Center(
                        child: Text(
                          'Trades band hone ke baad yahan patterns dikhenge.',
                          textAlign: TextAlign.center,
                          style: context.type.secondary.copyWith(color: context.palette.textMuted),
                        ),
                      ),
                    )
                  else
                    _buildDetails(context, data, overall, low, sample, minSample),
                ],
              ),
            );
          },
        );
    if (widget.embedded) return body;
    return Scaffold(
      appBar: AppBar(
        title: const Text('AI Insights'),
        backgroundColor: Colors.transparent,
        elevation: 0,
      ),
      body: SafeArea(child: body),
    );
  }

  Widget _askAiButton(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: SizedBox(
        width: double.infinity,
        child: OutlinedButton.icon(
          onPressed: () {
            AppHaptics.light();
            if (widget.embedded) {
              showAiChatPopup(context);
            } else {
              Navigator.of(context).push(OwlRoute(builder: (_) => const AiAssistantScreen()));
            }
          },
          icon: Icon(Icons.chat_bubble_outline, size: 16, color: context.palette.accent),
          label: Text(
            'Ask AI: kab loss hoti hai?',
            style: TextStyle(color: context.palette.accent, fontWeight: FontWeight.w700),
          ),
          style: OutlinedButton.styleFrom(
            side: BorderSide(color: context.palette.accent.withOpacity(0.5)),
            padding: const EdgeInsets.symmetric(vertical: 12),
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
          ),
        ),
      ),
    );
  }

  Widget _buildDetails(
    BuildContext context,
    Map<String, dynamic> data,
    Map<String, dynamic>? overall,
    bool low,
    int sample,
    int minSample,
  ) {
    final groups = (data['groups'] is Map) ? Map<String, dynamic>.from(data['groups'] as Map) : <String, dynamic>{};
    final ctxTrades = _i(data['context_trades']);
    final emaMedian = data['ema_median'];
    final children = <Widget>[];
    final head = <Widget>[const AiStoryCard(), const AiRulesCard(), const AiPlaybookCard()];
    final payoffMap = (data['payoff'] is Map) ? data['payoff'] as Map : null;
    _be = (payoffMap != null && payoffMap['breakeven_wr'] is num) ? _d(payoffMap['breakeven_wr']) : null;
    _minN = minSample;

    if (low) {
      children.add(_notice(
        context,
        'Sirf $sample trades hain (kam se kam $minSample chahiye). Neeche ke pattern abhi pakke nahi hain - sirf ishaara samjho.',
        context.palette.warning,
      ));
    }

    if (overall != null) {
      children.add(Row(
        children: [
          _metric(context, 'Win rate (last $sample)', '${_d(overall['win_rate']).toStringAsFixed(0)}%',
              _d(overall['win_rate']) >= 50 ? context.palette.profit : context.palette.loss),
          _metric(context, 'Avg win', '${_signed(_d(overall['avg_win']))}%', context.palette.profit),
          _metric(context, 'Avg loss', '${_signed(_d(overall['avg_loss']))}%', context.palette.loss),
          _metric(context, 'W / L', '${_i(overall['wins'])} / ${_i(overall['losses'])}', context.palette.textPrimary),
        ],
      ));
      children.add(const SizedBox(height: 8));
    }

    final payoff = (data['payoff'] is Map) ? Map<String, dynamic>.from(data['payoff'] as Map) : null;
    if (payoff != null) {
      children.add(_line(
        context,
        'Payoff: 1 jeet ≈ ${_d(payoff['ratio']).toStringAsFixed(1)} haar. '
        'Breakeven win rate ~${_d(payoff['breakeven_wr']).toStringAsFixed(0)}% - '
        'sirf win rate se strategy ko fail mat samjho.',
      ));
    }
    final open = (data['open'] is Map) ? Map<String, dynamic>.from(data['open'] as Map) : null;
    if (open != null && _i(open['n']) > 0) {
      final openPnl = _d(open['pnl']);
      children.add(_sectionTitle(context, 'OPEN TRADES (abhi chal rahe, win rate me nahi)'));
      children.add(_line(
        context,
        '${_i(open['n'])} open · ${_i(open['green_n'])} profit me · '
        'unrealized ${_signed(openPnl)} USDT · best ${_signed(_d(open['best_roi']))}%',
      ));
      children.add(_line(
        context,
        'Closed ${_signed(_d(data['closed_pnl']))} + Open ${_signed(openPnl)} = '
        'Total ${_signed(_d(data['combined_pnl']))} USDT',
      ));
    }
    final tr = (data['tp_reach'] is Map) ? Map<String, dynamic>.from(data['tp_reach'] as Map) : null;
    if (tr != null && _i(tr['hit_tp1']) > 0) {
      children.add(_line(
        context,
        'TP1 tak ${_i(tr['hit_tp1'])}/${_i(tr['n'])} closed trades gaye; '
        '${_i(tr['hit_tp1_then_lost'])} phir bhi loss me band hue.',
      ));
    }

    final cyc = (data['cycle'] is Map) ? Map<String, dynamic>.from(data['cycle'] as Map) : null;
    if (cyc != null && cyc.isNotEmpty) {
      Map<String, dynamic> m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
      final td = m(cyc['today']);
      final yd = m(cyc['yesterday']);
      final phase = '${cyc['phase'] ?? 'normal'}';
      final phaseWord = phase == 'choppy'
          ? 'CHOPPY - quick SL zyada'
          : (phase == 'recovering' ? 'RECOVERING' : 'NORMAL');
      children.add(_sectionTitle(context, 'BOT KA CYCLE (archive se, restart me bhi bacha rehta hai)'));
      children.add(_notice(
        context,
        'Abhi ka phase: $phaseWord',
        phase == 'choppy' ? context.palette.warning : context.palette.textMuted,
      ));
      children.add(_line(
        context,
        'Aaj: ${_i(td['n'])} closed · ${_i(td['w'])}W/${_i(td['l'])}L · ${_signed(_d(td['pnl']))} USDT',
      ));
      children.add(_line(
        context,
        'Kal: ${_i(yd['n'])} closed · ${_i(yd['w'])}W/${_i(yd['l'])}L · ${_signed(_d(yd['pnl']))} USDT',
      ));
      final hrs = (cyc['hours'] is List) ? cyc['hours'] as List : const [];
      if (hrs.isNotEmpty) {
        children.add(Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final h in hrs)
              if (h is Map)
                _chip(
                  context,
                  '${_i(h['h']).toString().padLeft(2, '0')}h  ${_i(h['w'])}W/${_i(h['n']) - _i(h['w'])}L',
                  _d(h['pnl']),
                ),
          ],
        ));
      }
      final l10 = m(cyc['last10']);
      final fs = m(cyc['fast_sl']);
      children.add(_line(
        context,
        'Lagatar loss abhi: ${_i(cyc['loss_run_now'])} (sabse lambi ${_i(cyc['loss_run_max'])}) · '
        'last 10: ${_i(l10['w'])}W/${_i(l10['l'])}L · jaldi SL: ${_i(fs['n'])}/${_i(fs['of'])}',
      ));
      final ab = m(cyc['after_bad_phase']);
      if (ab.isNotEmpty) {
        children.add(_line(
          context,
          'Pehle ${_i(ab['phases'])} kharab phase ke baad: ${_i(ab['positive'])} me agle 10 trades profit me the '
          '(avg ${_signed(_d(ab['avg_pnl_next10']))} USDT)',
        ));
      }
    }

    children.add(const SizedBox(height: 6));
    children.add(Text(
      'Bar = win-rate · safed line = break-even · GOOD/AVOID = us group ka net P&L · '
      '$_minN trades se kam = PAKKA NAHI (dhundhla)'
      '${widget.onJump != null ? ' · row par tap = uske trades Trade Book mein' : ''}',
      style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 10.5),
    ));
    children.add(_whatIfBar(context, groups));
    children.add(_groupSection(context, 'TIMEFRAME', groups['timeframe'], 'timeframe'));
    children.add(_groupSection(context, 'SL DISTANCE FROM ENTRY (price %)', groups['sl_dist'], 'sl_dist'));
    children.add(_groupSection(context, 'SD ZONE AT ENTRY', groups['zone'], 'zone'));
    children.add(_groupSection(context, 'SESSION (UTC)', groups['session'], 'session'));
    children.add(_groupSection(context, 'DIRECTION', groups['direction'], 'direction'));
    children.add(_groupSection(
      context,
      emaMedian is num ? 'EMA SLOPE (steep >= ${_d(emaMedian).toStringAsFixed(3)}%)' : 'EMA SLOPE',
      groups['ema'],
      'ema',
    ));
    children.add(_groupSection(context, 'VOLUME ON SIGNAL CANDLE (surge = 1.5x+)', groups['volume'], 'volume'));

    if (ctxTrades < sample) {
      children.add(_notice(
        context,
        'Zone / EMA / volume ka data sirf $ctxTrades/$sample trades ka hai - ye naye trades se banna shuru hota hai.',
        context.palette.textMuted,
      ));
    }

    children.addAll(_minerWidgets(context, data['miner']));
    children.addAll(_mlWidgets(context, data['ml']));

    final mm = (data['mfe_mae'] is Map) ? Map<String, dynamic>.from(data['mfe_mae'] as Map) : null;
    if (mm != null) {
      children.add(_sectionTitle(context, 'MFE / MAE (trade band hone se pehle kya dekha)'));
      if (mm['loser'] is Map) {
        final l = Map<String, dynamic>.from(mm['loser'] as Map);
        children.add(_line(
          context,
          'Loss wale trades: best profit ${_signed(_d(l['avg_mfe']))}% tak gaye; '
          '${_i(l['green_n'])}/${_i(l['n'])} pehle ${_signed(_d(l['thr']))}%+ profit me the.',
        ));
      }
      if (mm['winner'] is Map) {
        final w = Map<String, dynamic>.from(mm['winner'] as Map);
        children.add(_line(
          context,
          'Jeetne wale trades: jeetne se pehle avg dip ${_signed(_d(w['avg_mae']))}%; '
          'peak se avg ${_d(w['giveback']).toStringAsFixed(2)}% wapas diya.',
        ));
      }
    }

    final exits = (data['exits'] is List) ? data['exits'] as List : const [];
    if (exits.isNotEmpty) {
      children.add(_sectionTitle(context, 'EXITS'));
      children.add(Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final e in exits)
            if (e is Map) _chip(context, '${e['reason']} x${_i(e['count'])}  ${_signed(_d(e['pnl']))}', _d(e['pnl'])),
        ],
      ));
    }

    children.addAll(_coinCard(context, data['coins']));

    final weak = (data['weak_coins'] is List) ? data['weak_coins'] as List : const [];
    if (weak.isNotEmpty) {
      children.add(_sectionTitle(context, 'KAMZOR COINS (3+ trades)'));
      children.add(Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final w in weak)
            if (w is Map) _chip(context, '${w['symbol']}  ${_signed(_d(w['pnl']))}', _d(w['pnl'])),
        ],
      ));
    }

    children.add(const SizedBox(height: 10));
    children.add(Text(
      'Ye numbers code ne gine hain, AI ne nahi. AI Assistant se poochho: "kab loss hoti hai?"',
      style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 11),
    ));

    final p = context.palette;
    head.add(const SizedBox(height: 10));
    head.add(OutlinedButton.icon(
      onPressed: () {
        AppHaptics.light();
        setState(() => _showAll = !_showAll);
      },
      icon: Icon(_showAll ? Icons.expand_less_rounded : Icons.expand_more_rounded, size: 18, color: p.accent),
      label: Text(
        _showAll ? 'Details chhupao' : 'Aur details dekho (SD zone, session, slope, ML...)',
        style: TextStyle(color: p.accent, fontWeight: FontWeight.w700, fontSize: 12.5),
      ),
      style: OutlinedButton.styleFrom(
        minimumSize: const Size.fromHeight(40),
        side: BorderSide(color: p.accent.withOpacity(0.5)),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(AppSpacing.radiusMedium)),
      ),
    ));
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ...head,
        if (_showAll) ...children,
      ],
    );
  }

  List<Widget> _mlWidgets(BuildContext context, dynamic raw) {
    if (raw is! Map) return const [];
    final m = Map<String, dynamic>.from(raw);
    final out = <Widget>[];
    out.add(_sectionTitle(context, 'ML MODEL (purane trades par seekha, naye par graded)'));
    if (m['ready'] != true) {
      out.add(_notice(
        context,
        'Abhi ${_i(m['n'])} trades hain, ${_i(m['min_trades'])} chahiye. Tab tak model train nahi hota.',
        context.palette.textMuted,
      ));
      return out;
    }
    final targets = (m['targets'] is List) ? m['targets'] as List : const [];
    for (final t in targets) {
      if (t is! Map) continue;
      final learned = t['verdict'] == 'LEARNED';
      final color = learned ? context.palette.profit : context.palette.textMuted;
      final auc = (t['auc'] is num) ? _d(t['auc']).toStringAsFixed(2) : '-';
      final luck = (t['luck_auc95'] is num) ? _d(t['luck_auc95']).toStringAsFixed(2) : '-';
      final facs = (t['factors'] is List) ? t['factors'] as List : const [];
      final facTxt = facs.map((f) => (f is Map) ? '${f['name']} ${f['dir']}' : '').where((x) => x.isNotEmpty).join(', ');
      out.add(_notice(
        context,
        '${t['name']}: ${t['verdict']}  |  naye trades par AUC $auc (luck ~$luck)'
        '${facTxt.isNotEmpty ? '\nSeekha: $facTxt' : ''}',
        color,
      ));
    }
    return out;
  }

  List<Widget> _minerWidgets(BuildContext context, dynamic raw) {
    if (raw is! Map) return const [];
    final m = Map<String, dynamic>.from(raw);
    final out = <Widget>[];
    out.add(_sectionTitle(context, 'AI KHUD SEEKHA (purane trades se mila, naye trades par dobara test)'));
    if (m['ready'] != true) {
      out.add(_notice(
        context,
        'Abhi ${_i(m['n'])} trades hain, ${_i(m['min_total'])} chahiye. Tab tak AI koi pattern nahi banayega.',
        context.palette.textMuted,
      ));
      return out;
    }
    out.add(_line(
      context,
      '${_i(m['tested'])} combo test hue | purane ${_i(m['n_old'])} trades par mile, '
      'naye ${_i(m['n_new'])} par check hue | luck-check: nakli data par ~${_d(m['noise_confirmed']).toStringAsFixed(1)} confirm hue.',
    ));

    Widget row(Map p, Color color) {
      final tag = p['stable'] == true ? 'STABLE' : '${p['verdict']}';
      final newTxt = (p['avg_new'] is num)
          ? 'naye ${_i(p['n_new'])} trade avg ${_signed(_d(p['avg_new']), digits: 1)}%'
          : 'naye trades abhi kam';
      return Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Container(
          width: double.infinity,
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: color.withOpacity(0.10),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Text(
            '${p['label']}\n${_i(p['n'])} trades, win ${_d(p['win_rate']).toStringAsFixed(0)}%, '
            'avg ${_signed(_d(p['avg_roi']), digits: 1)}% | purane ${_signed(_d(p['avg_old']), digits: 1)}%, $newTxt | $tag',
            style: AppTypography.metadata.copyWith(color: color, fontSize: 11.5),
          ),
        ),
      );
    }

    final take = (m['take'] is List) ? m['take'] as List : const [];
    final avoid = (m['avoid'] is List) ? m['avoid'] as List : const [];
    final untested = (m['untested'] is List) ? m['untested'] as List : const [];
    if (take.isEmpty && avoid.isEmpty) {
      out.add(_notice(context, 'Abhi koi pattern naye trades par pakka nahi hua.', context.palette.textMuted));
    }
    if (take.isNotEmpty) {
      out.add(_sectionTitle(context, 'ISME STRATEGY CHALTI HAI (naye trades par bhi tiki)'));
      for (final p in take) {
        if (p is Map) out.add(row(p, context.palette.profit));
      }
    }
    if (avoid.isNotEmpty) {
      out.add(_sectionTitle(context, 'ISME STRATEGY HARTI HAI (naye trades par bhi)'));
      for (final p in avoid) {
        if (p is Map) out.add(row(p, context.palette.loss));
      }
    }
    if (untested.isNotEmpty) {
      out.add(_sectionTitle(context, 'KAMZOR HINT (naye trades abhi kam)'));
      for (final p in untested) {
        if (p is Map) out.add(row(p, context.palette.textMuted));
      }
    }
    if (_i(m['failed_n']) > 0) {
      out.add(_line(context, '${_i(m['failed_n'])} pattern naye trades par fail hue - wo luck tha.'));
    }

    final la = (m['loss_anatomy'] is Map) ? Map<String, dynamic>.from(m['loss_anatomy'] as Map) : null;
    final types = (la != null && la['types'] is List) ? la['types'] as List : const [];
    if (types.isNotEmpty) {
      out.add(_sectionTitle(context, 'LOSS KAISE HOTA HAI (postmortem)'));
      for (final t in types) {
        if (t is! Map) continue;
        out.add(_line(
          context,
          '${t['type']}: ${_i(t['n'])} trades (${_d(t['share']).toStringAsFixed(0)}%), ${_signed(_d(t['pnl']))} USDT',
        ));
        final spots = (t['spots'] is List) ? t['spots'] as List : const [];
        for (final sp in spots) {
          if (sp is Map) out.add(_line(context, '    zyada: ${sp['label']} (${_i(sp['n'])} trades)'));
        }
      }
    }

    final ho = (m['hold'] is Map) ? Map<String, dynamic>.from(m['hold'] as Map) : null;
    if (ho != null) {
      out.add(_sectionTitle(context, 'KITNA WAIT KARNA HAI (hold / TP timing)'));
      final lad = (ho['ladder'] is List) ? ho['ladder'] as List : const [];
      for (final g in lad) {
        if (g is Map) {
          out.add(_line(context, 'TP${_i(g['level'])}: aam taur par ~${fmtMins(_d(g['p50']))}, 8/10 ~${fmtMins(_d(g['p80']))} me (${_i(g['n'])} trades)'));
        }
      }
      final waits = (ho['waits'] is List) ? ho['waits'] as List : const [];
      for (final w in waits) {
        if (w is Map) {
          out.add(_line(context, 'TP1 ke ${fmtMins(w['wait'])} baad bhi khule: ${_i(w['n'])} -> ${_i(w['tp2_plus'])} TP2+ gaye, ${_i(w['reversed'])} SL/TSL pe band'));
        }
      }
    }

    final er = (m['exit_rules'] is Map) ? Map<String, dynamic>.from(m['exit_rules'] as Map) : null;
    if (er != null) {
      out.add(_sectionTitle(context, 'EXIT KA TEST (andaza, purane vs naye trades)'));
      if (er['trail'] is Map) {
        final t = Map<String, dynamic>.from(er['trail'] as Map);
        out.add(_line(
          context,
          'Trail: ${_i(t['act'])}% profit ke baad peak se ${_i(t['trail'])}% girne par nikalo -> '
          'purane ${_signed(_d(t['gain_old']), digits: 0)}, naye ${_signed(_d(t['gain_new']), digits: 0)} ROI-points',
        ));
      }
      if (er['cap'] is Map) {
        final c = Map<String, dynamic>.from(er['cap'] as Map);
        out.add(_line(
          context,
          'Max-loss ${_i(c['cap'])}% -> purane ${_signed(_d(c['gain_old']), digits: 0)}, naye ${_signed(_d(c['gain_new']), digits: 0)}',
        ));
      }
    }

    final sr = (m['skip_report'] is Map) ? Map<String, dynamic>.from(m['skip_report'] as Map) : null;
    if (sr != null) {
      out.add(_sectionTitle(context, 'AGAR SKIP KARTE TO (sirf salah, bot ab bhi har signal leta hai)'));
      if (_i(sr['patterns']) == 0) {
        out.add(_notice(context, 'Abhi koi AVOID pattern pakka nahi hua, isliye skip karne ki salah nahi.', context.palette.textMuted));
      } else {
        final a = Map<String, dynamic>.from(sr['all'] as Map);
        final o = Map<String, dynamic>.from(sr['old'] as Map);
        final nw = Map<String, dynamic>.from(sr['new'] as Map);
        final labels = (sr['labels'] is List) ? (sr['labels'] as List).join(' | ') : '';
        out.add(_line(context, 'AVOID patterns: $labels'));
        final change = -_d(a['pnl']);
        out.add(_notice(
          context,
          '${_i(a['n'])} / ${_i(sr['total_n'])} trades skip hote. Unka net P&L ${_signed(_d(a['pnl']))} USDT, '
          'to skip se total ${_signed(change)} USDT badalta. ${_i(a['wins'])} jeetne wale (${_signed(_d(a['win_pnl']))}) chhoot jaate. '
          'Margin ${_d(a['margin_hours']).toStringAsFixed(1)} USDT-ghante khali rehta.',
          change >= 0 ? context.palette.profit : context.palette.loss,
        ));
        out.add(_line(
          context,
          'Purane ${_i(o['n'])} trades: ${_signed(_d(o['pnl']))} | NAYE ${_i(nw['n'])} trades: ${_signed(_d(nw['pnl']))}. '
          'Bharosa tabhi jab naye trades par bhi ye negative ho.',
        ));
      }
    }

    if (sr != null && sr['curve'] is Map) {
      out.add(_sectionTitle(context, 'AI NE KITNA SEEKHA (asli vs "agar skip karta" P&L, sab kuch kat ke)'));
      out.add(_LearnCurve(curve: Map<String, dynamic>.from(sr['curve'] as Map), hasAvoid: _i(sr['patterns']) > 0));
    }

    final ps = (m['path_study'] is Map) ? Map<String, dynamic>.from(m['path_study'] as Map) : null;
    if (ps != null) {
      out.add(_sectionTitle(context, 'ASLI PRICE PATH REPLAY (har trade ka poora raasta, andaza nahi)'));
      if (ps['ready'] != true) {
        out.add(_notice(
          context,
          'Path record ab shuru hua hai: ${_i(ps['n_paths'])} trades ka raasta save hai, '
          '${_i(ps['n_used'])} kaam ke hain, ${_i(ps['need'])} chahiye. Tab tak AI trail/hold ke naye number nahi dega.',
          context.palette.textMuted,
        ));
      } else {
        final err = ps['replay_err'];
        out.add(_line(
          context,
          '${_i(ps['n_used'])} trades | purane ${_i(ps['n_old'])} par rule dhunda, naye ${_i(ps['n_new'])} par dobara check'
          '${err != null ? ' | aaj ke rules ka replay asli result se ~${_d(err).toStringAsFixed(1)} ROI-points door' : ''}',
        ));
        final rules = (ps['rules'] is List) ? ps['rules'] as List : const [];
        for (final r in rules) {
          if (r is! Map) continue;
          final held = r['held'] == true;
          final helps = r['helps_old'] == true;
          final tag = held ? 'NAYE PAR BHI TIKA' : (helps ? 'sirf purane par, pakka nahi' : 'fayda nahi');
          out.add(_line(
            context,
            '${r['name']} (${r['param']}): purane ${_signed(_d(r['gain_old']), digits: 0)}, '
            'naye ${_signed(_d(r['gain_new']), digits: 0)} -> $tag',
          ));
        }
        if (ps['combo'] is Map) {
          final c = Map<String, dynamic>.from(ps['combo'] as Map);
          out.add(_line(
            context,
            'Tike hue rules saath me: purane ${_signed(_d(c['gain_old']), digits: 0)}, naye ${_signed(_d(c['gain_new']), digits: 0)}',
          ));
        }
        final tm = (ps['tp_time'] is Map) ? Map<String, dynamic>.from(ps['tp_time'] as Map) : const <String, dynamic>{};
        final keys = tm.keys.toList()..sort();
        for (final k in keys) {
          final g = tm[k];
          if (g is Map) {
            out.add(_line(context, 'TP$k pehli baar: ~${fmtMins(_d(g['p50']))} me, 8/10 ~${fmtMins(_d(g['p80']))} me (${_i(g['n'])} trades)'));
          }
        }
        final nw = (ps['no_tp1_wait'] is List) ? ps['no_tp1_wait'] as List : const [];
        for (final w in nw) {
          if (w is Map) {
            out.add(_line(
              context,
              '${fmtMins(w['after'])} tak TP1 nahi aaya (${_i(w['n'])} trades): ${_i(w['later_tp1'])} ne baad me TP1 chhua, '
              '${_i(w['won'])} profit me band, avg ${_signed(_d(w['avg_roi']), digits: 1)}%',
            ));
          }
        }
        if (ps['winner_dip_first'] is Map) {
          final w = Map<String, dynamic>.from(ps['winner_dip_first'] as Map);
          out.add(_line(
            context,
            'Jeetne wale trades TP1 se PEHLE kitna gire: aam ${_d(w['p50']).toStringAsFixed(1)}%, 80% ke liye <= ${_d(w['p80']).toStringAsFixed(1)}%, '
            '95% ke liye <= ${_d(w['p95']).toStringAsFixed(1)}% ROI (${_i(w['n'])} trades). Isse tight SL inko kaat deta.',
          ));
        }
      }
    }
    final sds = (ps != null && ps['sd_study'] is Map) ? Map<String, dynamic>.from(ps['sd_study'] as Map) : null;
    if (sds != null) {
      out.add(_sectionTitle(context, 'SD KA SIZE AUR SHAPE (trade ke dauraan)'));
      if (sds['ready'] != true) {
        out.add(_notice(
          context,
          'SD bars ${_i(sds['n_sd'])} trades ke save hue hain, ${_i(sds['need'])} chahiye. Tab tak AI SD shape par kuch nahi bolega.',
          context.palette.textMuted,
        ));
      } else {
        out.add(_line(
          context,
          'Sab in trades ka avg net ROI ${_signed(_d(sds['overall_avg']))}%. Har group ka avg isse upar ya neeche, aur purane/naye par same taraf ho to "tika".',
        ));
        final groups = (sds['groups'] is Map) ? Map<String, dynamic>.from(sds['groups'] as Map) : const <String, dynamic>{};
        for (final e in groups.entries) {
          final list = (e.value is List) ? e.value as List : const [];
          for (final g in list) {
            if (g is! Map) continue;
            final o = g['old'] == null ? 'n/a' : _signed(_d(g['old']));
            final nw = g['new'] == null ? 'n/a' : _signed(_d(g['new']));
            out.add(_line(
              context,
              '${g['name']}: ${_i(g['n'])} trades, avg ${_signed(_d(g['avg']))}%, TP1 ${_d(g['tp1']).toStringAsFixed(0)}%, '
              'TP2 ${_d(g['tp2']).toStringAsFixed(0)}% | purane $o, naye $nw -> ${g['steady'] == true ? 'TIKA' : 'pakka nahi'}',
            ));
          }
        }
      }
    }
    out.addAll(_slopeWidgets(context, ps == null ? null : ps['slope_study']));
    return out;
  }

  /// EMA slope while the trade is open (ai_slope_tracker.py saves it every candle).
  /// Slope is "WITH trade" when the EMA moves the trade's way (BUY rising / SELL falling).
  /// A trade that started WITH the slope but flipped AGAINST it before closing is a
  /// possible fake signal. Numbers are the backend's; only NEW trades have this data.
  List<Widget> _slopeWidgets(BuildContext context, dynamic raw) {
    if (raw is! Map) return const [];
    final m = Map<String, dynamic>.from(raw);
    final out = <Widget>[];
    out.add(_sectionTitle(context, 'EMA SLOPE TRADE KE DAURAAN (fake signal pehchaan)'));
    if (m['ready'] != true) {
      out.add(_notice(
        context,
        'Slope bars ${_i(m['n_slope'])} trades ke save hue hain, ${_i(m['need'])} chahiye. '
        'Ye data sirf naye trades se banta hai. Tab tak AI slope par kuch nahi bolega.',
        context.palette.textMuted,
      ));
      return out;
    }
    out.add(_line(
      context,
      'Sab in trades ka avg net ROI ${_signed(_d(m['overall_avg']))}%. Group ka avg isse neeche ho aur '
      'purane/naye dono par same taraf ho to \"tika\".',
    ));
    final fk = (m['fake'] is Map) ? Map<String, dynamic>.from(m['fake'] as Map) : null;
    if (fk != null && _i(fk['losers']) > 0) {
      out.add(_notice(
        context,
        'SL par band ${_i(fk['losers'])} loss trades me se ${_i(fk['flipped'])} me slope band hone se PEHLE '
        'trade ke ULTA palat chuka tha (possible fake signal).',
        context.palette.loss,
      ));
    }
    const titles = {
      'entry': 'Entry par slope',
      'end': 'Trade ke end tak slope',
      'flip': 'Slope palta ya nahi',
      'early': '10 min baad slope',
    };
    final groups = (m['groups'] is Map) ? Map<String, dynamic>.from(m['groups'] as Map) : const <String, dynamic>{};
    for (final e in groups.entries) {
      final list = (e.value is List) ? e.value as List : const [];
      if (list.isEmpty) continue;
      out.add(_line(context, '${titles[e.key] ?? e.key}:'));
      for (final g in list) {
        if (g is! Map) continue;
        final o = g['old'] == null ? 'n/a' : _signed(_d(g['old']));
        final nw = g['new'] == null ? 'n/a' : _signed(_d(g['new']));
        out.add(_line(
          context,
          '  ${g['name']}: ${_i(g['n'])} trades, avg ${_signed(_d(g['avg']))}%, '
          'TP1 ${_d(g['tp1']).toStringAsFixed(0)}% | purane $o, naye $nw -> ${g['steady'] == true ? 'TIKA' : 'pakka nahi'}',
        ));
      }
    }
    return out;
  }

  /// Switch + result box for the what-if mode. Uses only numbers the backend already put on
  /// the group row (pnl, win_pnl, loss_pnl). One group at a time, so nothing is double-counted.
  Widget _whatIfBar(BuildContext context, Map<String, dynamic> groups) {
    final p = context.palette;
    Map<String, dynamic>? row;
    if (_whatIf && _pickKind != null) {
      final list = (groups[_pickKind] is List) ? groups[_pickKind] as List : const [];
      for (final r in list) {
        if (r is Map && '${r['label']}' == _pickLabel) row = Map<String, dynamic>.from(r);
      }
    }
    Widget? result;
    if (_whatIf && row != null) {
      final pnl = _d(row['pnl']);
      final change = -pnl;
      final color = change >= 0 ? p.profit : p.loss;
      result = _notice(
        context,
        '"${row['label']}" skip hota (${_i(row['n'])} trades): total P&L ${_signed(change)} USDT badalta.\n'
        'Jeetne wale ${_signed(_d(row['win_pnl']))} USDT chhoot jaate, loss ${_signed(_d(row['loss_pnl']))} USDT bachte.\n'
        '${_i(row['n']) < _minN ? 'Trades kam hain (PAKKA NAHI) - ise bharosa mat karo. ' : ''}'
        'Ye purana hisab hai, sirf salah. Bot ab bhi har signal leta hai.',
        color,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  'WHAT-IF: group chuno, dekho skip karte to P&L kitna badalta',
                  style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5, fontWeight: FontWeight.w700),
                ),
              ),
              Switch(
                value: _whatIf,
                activeColor: p.accent,
                onChanged: (v) => setState(() {
                  _whatIf = v;
                  if (!v) {
                    _pickKind = null;
                    _pickLabel = null;
                  }
                }),
              ),
            ],
          ),
        ),
        if (_whatIf && row == null)
          Text('Neeche kisi ek row par tap karo (Trade Book jump abhi band hai).',
              style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5)),
        if (result != null) result,
      ],
    );
  }

  /// Coin report card: coins with 3+ trades, worst first. DHYAN SE = 4+ trades and net negative.
  List<Widget> _coinCard(BuildContext context, dynamic raw) {
    final list = (raw is List) ? raw : const [];
    if (list.isEmpty) return const [];
    final p = context.palette;
    final out = <Widget>[_sectionTitle(context, 'COIN REPORT CARD (3+ trades, sabse kharab pehle)')];
    for (final c in list) {
      if (c is! Map) continue;
      final pnl = _d(c['pnl']);
      final caution = c['caution'] == true;
      final color = pnl >= 0 ? p.profit : p.loss;
      out.add(Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(
          children: [
            Expanded(
              child: Text(
                '${c['symbol']}  ·  ${_i(c['n'])} trades  ·  win ${_d(c['win_rate']).toStringAsFixed(0)}%',
                overflow: TextOverflow.ellipsis,
                style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5),
              ),
            ),
            if (caution)
              Container(
                margin: const EdgeInsets.only(right: 6),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: p.warning.withOpacity(0.14),
                  borderRadius: BorderRadius.circular(6),
                  border: Border.all(color: p.warning.withOpacity(0.5), width: 0.75),
                ),
                child: Text('DHYAN SE', style: TextStyle(color: p.warning, fontSize: 9, fontWeight: FontWeight.w800, letterSpacing: 0.4)),
              ),
            Text(_signed(pnl), style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
          ],
        ),
      ));
    }
    out.add(Text('Sirf heads-up hai. Bot kisi coin ko skip nahi karta.',
        style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5)));
    return out;
  }

  Widget _sectionTitle(BuildContext context, String text) {
    return Padding(
      padding: const EdgeInsets.only(top: 12, bottom: 6),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(
          color: context.palette.textMuted,
          fontSize: 10.5,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
        ),
      ),
    );
  }

  Widget _line(BuildContext context, String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(color: context.palette.textSecondary, fontSize: 12),
      ),
    );
  }

  Widget _notice(BuildContext context, String text, Color color) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10, bottom: 4),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withOpacity(0.10),
        borderRadius: BorderRadius.circular(10),
      ),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(color: color, fontSize: 11.5),
      ),
    );
  }

  Widget _metric(BuildContext context, String label, String value, Color color) {
    return Expanded(
      child: Padding(
        padding: const EdgeInsets.only(top: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label, style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 10.5)),
            const SizedBox(height: 2),
            Text(
              value,
              style: AppTypography.secondaryData.copyWith(color: color, fontSize: 14, fontWeight: FontWeight.w700),
            ),
          ],
        ),
      ),
    );
  }

  Widget _chip(BuildContext context, String text, double pnl) {
    final color = pnl >= 0 ? context.palette.profit : context.palette.loss;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withOpacity(0.12),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Text(
        text,
        style: AppTypography.metadata.copyWith(color: color, fontSize: 11, fontWeight: FontWeight.w600),
      ),
    );
  }

  Widget _groupSection(BuildContext context, String title, dynamic rowsRaw, [String? kind]) {
    final rows = (rowsRaw is List) ? rowsRaw : const [];
    if (rows.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionTitle(context, title),
        for (final r in rows)
          if (r is Map) _groupRow(context, Map<String, dynamic>.from(r), kind),
      ],
    );
  }

  /// One group (an SD zone, a session, a direction...) as a bar. The bar is the
  /// win rate; the white tick is the break-even win rate for YOUR payoff (so a
  /// 20% win rate can still be GOOD). Label comes from the net P&L of that
  /// group's trades: GOOD / AVOID, or PAKKA NAHI (and a faded bar) while the
  /// group has fewer than the minimum trades. Numbers are the backend's.
  Widget _groupRow(BuildContext context, Map<String, dynamic> r, [String? kind]) {
    final p = context.palette;
    final wr = _d(r['win_rate']);
    final n = _i(r['n']);
    final pnl = _d(r['pnl']);
    final reliable = n >= _minN;
    final Color color;
    final String verdict;
    if (!reliable) {
      color = p.textMuted;
      verdict = 'PAKKA NAHI';
    } else if (pnl > 0) {
      color = p.profit;
      verdict = 'GOOD';
    } else {
      color = p.loss;
      verdict = 'AVOID';
    }
    final be = _be;
    final jump = widget.onJump;
    final canJump = kind != null && (_whatIf || jump != null);
    final picked = _whatIf && kind != null && _pickKind == kind && _pickLabel == '${r['label']}';
    final row = Opacity(
      opacity: reliable ? 1.0 : 0.55,
      child: Padding(
        padding: const EdgeInsets.only(bottom: 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${r['label']}',
                    overflow: TextOverflow.ellipsis,
                    style: AppTypography.secondaryData.copyWith(
                      color: p.textPrimary,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: color.withOpacity(0.14),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(color: color.withOpacity(0.5), width: 0.75),
                  ),
                  child: Text(
                    verdict,
                    style: TextStyle(color: color, fontSize: 9.5, fontWeight: FontWeight.w800, letterSpacing: 0.4),
                  ),
                ),
                if (canJump) ...[
                  const SizedBox(width: 4),
                  Icon(_whatIf ? (picked ? Icons.check_circle_rounded : Icons.radio_button_unchecked_rounded) : Icons.chevron_right_rounded,
                      size: 16, color: picked ? p.accent : p.textMuted),
                ],
              ],
            ),
            const SizedBox(height: 5),
            LayoutBuilder(builder: (_, c) {
              final w = c.maxWidth;
              final fill = (w * (wr / 100.0)).clamp(0.0, w).toDouble();
              final tick = be == null ? null : (w * (be / 100.0)).clamp(0.0, w - 2).toDouble();
              return SizedBox(
                height: 12,
                child: Stack(
                  children: [
                    Positioned(
                      top: 3,
                      left: 0,
                      right: 0,
                      child: Container(
                        height: 6,
                        decoration: BoxDecoration(
                          color: p.textMuted.withOpacity(0.18),
                          borderRadius: BorderRadius.circular(3),
                        ),
                      ),
                    ),
                    Positioned(
                      top: 3,
                      left: 0,
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 500),
                        curve: Curves.easeOutCubic,
                        width: fill,
                        height: 6,
                        decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(3)),
                      ),
                    ),
                    if (tick != null)
                      Positioned(left: tick, top: 0, child: Container(width: 2, height: 12, color: p.textPrimary.withOpacity(0.85))),
                  ],
                ),
              );
            }),
            const SizedBox(height: 3),
            Text(
              'win ${wr.toStringAsFixed(0)}%'
              '${be != null ? ' (break-even ${be.toStringAsFixed(0)}%)' : ''}'
              '  ·  $n trades  ·  net ${_signed(pnl)} USDT',
              style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 10.5),
            ),
          ],
        ),
      ),
    );
    if (!canJump) return row;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: () {
        AppHaptics.light();
        if (_whatIf) {
          setState(() {
            final same = _pickKind == kind && _pickLabel == '${r['label']}';
            _pickKind = same ? null : kind;
            _pickLabel = same ? null : '${r['label']}';
          });
        } else {
          jump!('$kind', '${r['label']}');
        }
      },
      child: picked
          ? Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: p.accent.withOpacity(0.6), width: 1),
              ),
              padding: const EdgeInsets.fromLTRB(6, 6, 6, 0),
              child: row,
            )
          : row,
    );
  }
}


// ------------------------------------------------------------ learning curve --

/// "AI ne kitna seekha": running total P&L trade by trade - what the bot REALLY made vs
/// what it would have made had it skipped trades matching a CONFIRMED AVOID pattern.
/// One P&L line per case (real result). The dashed line marks where
/// the NEWER trades start (not used to find the patterns = the honest test). All numbers
/// come from the backend (ai_miner._learn_curve); this widget only draws them.
class _LearnCurve extends StatefulWidget {
  final Map<String, dynamic> curve;
  final bool hasAvoid;
  const _LearnCurve({required this.curve, required this.hasAvoid});

  @override
  State<_LearnCurve> createState() => _LearnCurveState();
}

class _LearnCurveState extends State<_LearnCurve> {
  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static String _sg(double v) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}';

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final raw = (widget.curve['pts'] is List) ? widget.curve['pts'] as List : const [];
    final a = <double>[];
    final k = <double>[];
    for (final r in raw) {
      if (r is List && r.length >= 4) {
        a.add(_n(r[0]));   // real P&L
        k.add(_n(r[1]));
      }
    }
    if (a.length < 2) {
      return Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Text('Graph ke liye abhi trades kam hain.',
            style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11.5)),
      );
    }
    final cut = (widget.curve['cut'] is num) ? (widget.curve['cut'] as num).toInt() : 0;
    final diff = k.last - a.last;
    // Only the NEWER part (after the dashed line): did skipping help there too?
    double? newDiff;
    if (cut > 0 && cut < a.length) {
      newDiff = (k.last - k[cut - 1]) - (a.last - a[cut - 1]);
    }
    final skipColor = p.profit;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: 130,
          width: double.infinity,
          child: CustomPaint(
            painter: _LearnCurvePainter(
              actual: a,
              skip: k,
              cut: cut,
              actualColor: p.accent,
              skipColor: skipColor,
              axis: p.border,
              cutColor: p.textMuted,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Wrap(spacing: 14, runSpacing: 4, children: [
          _legend(context, p.accent, 'Bot ne asli: ${_sg(a.last)}'),
          if (widget.hasAvoid) _legend(context, skipColor, 'Skip karta to: ${_sg(k.last)}'),
          _legend(context, p.textMuted, 'Dashed line = yahan se naye trades'),
        ]),
        const SizedBox(height: 6),
        Text(
          widget.hasAvoid
              ? 'Skip se total ${_sg(diff)} USDT badalta.'
                  '${newDiff != null ? ' Sirf naye hisse me: ${_sg(newDiff)} USDT (yahi asli test hai).' : ''}'
              : 'Abhi koi AVOID pattern pakka nahi hua, isliye dono line same hain - AI ne abhi kuch skip karne layak nahi seekha.',
          style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5),
        ),
      ],
    );
  }

  Widget _legend(BuildContext context, Color c, String t) => Row(mainAxisSize: MainAxisSize.min, children: [
        Container(width: 14, height: 3, decoration: BoxDecoration(color: c, borderRadius: BorderRadius.circular(2))),
        const SizedBox(width: 5),
        Text(t, style: AppTypography.metadata.copyWith(fontSize: 10.5)),
      ]);
}

class _LearnCurvePainter extends CustomPainter {
  final List<double> actual;
  final List<double> skip;
  final int cut;
  final Color actualColor;
  final Color skipColor;
  final Color axis;
  final Color cutColor;
  _LearnCurvePainter({
    required this.actual,
    required this.skip,
    required this.cut,
    required this.actualColor,
    required this.skipColor,
    required this.axis,
    required this.cutColor,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final n = actual.length;
    if (n < 2 || skip.length != n) return;
    var lo = 0.0;
    var hi = 0.0;
    for (var i = 0; i < n; i++) {
      if (actual[i] < lo) lo = actual[i];
      if (skip[i] < lo) lo = skip[i];
      if (actual[i] > hi) hi = actual[i];
      if (skip[i] > hi) hi = skip[i];
    }
    if (hi - lo < 1e-9) hi = lo + 1;
    const padY = 6.0;
    final h = size.height - padY * 2;
    double x(int i) => i * size.width / (n - 1);
    double y(double v) => padY + (hi - v) / (hi - lo) * h;

    canvas.drawLine(Offset(0, y(0)), Offset(size.width, y(0)), Paint()..color = axis..strokeWidth = 1);

    if (cut > 0 && cut < n - 1) {
      final cx = x(cut);
      final dash = Paint()..color = cutColor.withOpacity(0.7)..strokeWidth = 1;
      for (double yy = 0; yy < size.height; yy += 8) {
        canvas.drawLine(Offset(cx, yy), Offset(cx, (yy + 4).clamp(0.0, size.height).toDouble()), dash);
      }
    }

    Path line(List<double> v) {
      final path = Path()..moveTo(x(0), y(v[0]));
      for (var i = 1; i < n; i++) {
        path.lineTo(x(i), y(v[i]));
      }
      return path;
    }

    Paint stroke(Color c, double w) => Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = w
      ..strokeJoin = StrokeJoin.round
      ..color = c;
    canvas.drawPath(line(skip), stroke(skipColor, 1.8));
    canvas.drawPath(line(actual), stroke(actualColor, 2.0));
    canvas.drawCircle(Offset(x(n - 1), y(actual[n - 1])), 3, Paint()..color = actualColor);
    canvas.drawCircle(Offset(x(n - 1), y(skip[n - 1])), 3, Paint()..color = skipColor);
  }

  @override
  bool shouldRepaint(covariant _LearnCurvePainter old) =>
      old.actual != actual || old.skip != skip || old.cut != cut || old.actualColor != actualColor;
}
