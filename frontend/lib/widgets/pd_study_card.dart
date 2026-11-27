import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_spacing.dart';
import '../theme/app_theme.dart';
import 'owl_hero_card.dart';
import 'owl_kit_parts.dart';
import 'pd_widgets.dart';

/// Part 7 (Round 4 study C, 28 Nov 2026): the "Indicator study" card at the bottom of the Pump / Dump tab. Data = GET /api/pd/study (backend/pd_study.py).
/// Closed by default: it asks the phone only when opened (no background call). One block per question with the plain verdict lines the backend wrote
/// (TSI above / below 0, TSI signal line, Z length, Z vs ZSM, SD bands, entry timing, far from EMA). Lines with too little data are dimmed and counted.
/// Study only: nothing goes into the bot. Uses the Part 8 kit (OwlHeroCard, OwlStatRow, OwlStatTile). Dart NOT compiled in the sandbox: the GitHub APK build is the first compile.
const List<List<dynamic>> _kGroups = <List<dynamic>>[
  <dynamic>[<String>['tsi_zero'], 'TSI 0 ke upar ya neeche?', 'alert ke 4 ghante baad coin kis taraf gaya'],
  <dynamic>[<String>['tsi_signal'], 'TSI signal line ke upar ya neeche?', 'alert ke 4 ghante baad'],
  <dynamic>[<String>['z_len'], 'Kaunsi Z length sabse saaf?', 'Z 50 / 100 / 200'],
  <dynamic>[<String>['z_zsm'], 'Z, ZSM ke upar ya neeche?', 'alert ke time ki halat'],
  <dynamic>[<String>['zsm_side', 'zsm_cross'], 'ZSM ka role (candle test)', 'Z ke ZSM ke upar / neeche aur cross'],
  <dynamic>[<String>['sd_band', 'sd_best'], 'SD bands support / resistance?', 'price ne line ko kitna maana'],
  <dynamic>[<String>['timing'], 'Entry ka sahi time', 'sabse achhi 3 halat'],
  <dynamic>[<String>['far_ema'], 'EMA50 se door jaakar ulta jata hai?', 'paas vs bahut door'],
];

class PdStudyCard extends StatefulWidget {
  const PdStudyCard({super.key});

  @override
  State<PdStudyCard> createState() => _PdStudyCardState();
}

class _PdStudyCardState extends State<PdStudyCard> {
  bool _open = false;
  bool _busy = false;
  Map<String, dynamic>? _d;
  final Set<String> _all = <String>{}; // groups opened to show every line

  Future<void> _load() async {
    if (_busy) return;
    setState(() => _busy = true);
    final d = await context.read<AppProvider>().fetchPdStudy();
    if (!mounted) return;
    setState(() {
      _d = d;
      _busy = false;
    });
  }

  void _toggle() {
    setState(() => _open = !_open);
    if (_open) _load();
  }

  bool _few(Map v) => '${v['text']}'.contains('data kam hai');

  String _line(Map v) {
    if (v['tf'] == null) return '${v['text']}';
    return '${v['tf']} ${v['side'] == 'pump' ? 'pump' : 'dump'}: ${v['text']}';
  }

  Widget _note(AppPalette p, String t) => Padding(padding: const EdgeInsets.only(top: 6), child: Text(t, style: TextStyle(fontSize: 12, color: p.textSecondary)));

  Widget _group(AppPalette p, List g, List verdicts) {
    final qs = g[0] as List<String>;
    final lines = <Map>[for (final v in verdicts) if (v is Map && qs.contains('${v['q']}')) v];
    if (lines.isEmpty) return const SizedBox.shrink();
    final real = lines.where((v) => !_few(v)).toList();
    final few = lines.length - real.length;
    final key = '${g[1]}';
    final shown = _all.contains(key) ? real : real.take(6).toList();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${g[1]}', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary)),
        Text('${g[2]}', style: TextStyle(fontSize: 11, color: p.textMuted)),
        const SizedBox(height: 4),
        if (real.isEmpty) Text('Abhi data kam hai ($few jawab me 100 se kam alert).', style: TextStyle(fontSize: 12, color: p.textMuted)),
        for (final v in shown) Padding(padding: const EdgeInsets.symmetric(vertical: 2), child: Text(_line(v), style: TextStyle(fontSize: 12, color: p.textPrimary))),
        if (real.length > shown.length)
          GestureDetector(
            onTap: () => setState(() => _all.add(key)),
            behavior: HitTestBehavior.opaque,
            child: Padding(padding: const EdgeInsets.only(top: 4), child: Text('+${real.length - shown.length} aur dikhao', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.accent))),
          ),
        if (real.isNotEmpty && few > 0) Padding(padding: const EdgeInsets.only(top: 2), child: Text('$few aur jawab me abhi data kam hai.', style: TextStyle(fontSize: 11, color: p.textMuted))),
      ]),
    );
  }

  List<Widget> _body(AppPalette p) {
    final d = _d;
    if (d == null || _busy) {
      return [const Padding(padding: EdgeInsets.all(14), child: Center(child: SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))))];
    }
    final st = '${d['state']}';
    if (st != 'ok' && st != 'no_data') {
      return [_note(p, 'Study abhi phone ke backend par nahi hai. Repo update karo, phir owloff, owlon.')];
    }
    final days = pdNum(d['data_days']).toInt();
    final waiting = pdNum(d['waiting_24h']).toInt();
    final job = d['job'] is Map ? d['job'] as Map : <dynamic, dynamic>{};
    if (st == 'no_data') {
      return [
        OwlStatRow(tiles: [
          OwlStatTile(label: 'Data ke din', value: '$days', icon: Icons.calendar_today_outlined),
          OwlStatTile(label: '24 ghante ka intezaar', value: '$waiting', sub: 'alert', icon: Icons.hourglass_bottom),
        ]),
        _note(p, 'Study abhi shuru hui hai. Har alert ka result 24 ghante baad milta hai, isliye pehle jawab 1-2 din baad aayenge. Roz raat 12:10 ke baad study chalti hai.'),
        if (job['running'] == true) _note(p, 'Abhi study chal rahi hai: ${job['left']} candle set baaki.'),
      ];
    }
    final s = d['summary'] is Map ? d['summary'] as Map : <dynamic, dynamic>{};
    final coins = s['coins'] is List ? (s['coins'] as List).length : 0;
    final verdicts = s['verdicts'] is List ? s['verdicts'] as List : const <dynamic>[];
    final minN = pdNum(s['min_n']).toInt();
    return [
      OwlHeroCard(label: 'STUDY  ${s['day'] ?? ''}', value: '${pdNum(s['rows']).toInt()} alert', sub: 'checked alerts ka data, $coins coin ke candle test (${pdNum(s['candle_sets']).toInt()} set)'),
      const SizedBox(height: AppSpacing.s),
      OwlStatRow(tiles: [
        OwlStatTile(label: 'Data ke din', value: '$days'),
        OwlStatTile(label: '24h baaki', value: '$waiting', sub: 'alert'),
        OwlStatTile(label: 'Kam se kam', value: '$minN', sub: 'alert per jawab'),
      ]),
      for (final g in _kGroups) _group(p, g, verdicts),
      const SizedBox(height: 12),
      Text('Ye sirf study hai: bot me kuch nahi gaya. "chale" = coin 4 ghante baad alert ki taraf gaya. $minN se kam alert ho to jawab pe bharosa mat karo.', style: TextStyle(fontSize: 11, color: p.textMuted)),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(AppSpacing.radiusMedium), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        InkWell(
          onTap: _toggle,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Indicator study', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
                  Text('TSI, Z, ZSM, SD bands: kya sach me kaam karte hain', style: TextStyle(fontSize: 11.5, color: p.textMuted)),
                ]),
              ),
              Icon(_open ? Icons.expand_less : Icons.expand_more, color: p.textMuted),
            ]),
          ),
        ),
        if (_open) Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 12), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: _body(p))),
      ]),
    );
  }
}
