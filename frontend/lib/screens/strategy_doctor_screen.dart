import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../theme/app_motion.dart';
import '../widgets/owl_route.dart';
import '../widgets/doctor_verdict_card.dart';
import 'ai_report_screen.dart';

/// Own short request for the Doctor (20 s, one try, utf-8 body). It no longer shares the AI-tab request queue, so a busy or
/// stuck AI request can never keep this screen on an endless spinner; a failure carries a readable reason.
Future<Map<String, dynamic>> _doctorFetch(String base) async {
  final res = await http.get(Uri.parse('$base/api/ai/doctor')).timeout(const Duration(seconds: 20));
  if (res.statusCode != 200) throw 'The backend answered HTTP ${res.statusCode}';
  final m = jsonDecode(utf8.decode(res.bodyBytes));
  if (m is! Map) throw 'The backend sent an unexpected reply';
  return Map<String, dynamic>.from(m);
}

double _d(dynamic v) => (v is num) ? v.toDouble() : 0.0;
int _i(dynamic v) => (v is num) ? v.toInt() : 0;
List<Map<String, dynamic>> _list(dynamic v) =>
    (v is List) ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
Map<String, dynamic> _map(dynamic v) => (v is Map) ? Map<String, dynamic>.from(v) : <String, dynamic>{};
String _sg(double v, [int digits = 1]) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(digits)}';

Color _pnlColor(BuildContext c, double v) =>
    v > 0 ? c.palette.profit : (v < 0 ? c.palette.loss : c.palette.textMuted);

/// Strategy Doctor - reads closed trades and says which entries lose / win.
/// Everything is computed on the backend (strategy_doctor.py); the phone only draws it.
/// Rules here are suggestions only: nothing on this screen changes the bot.
class StrategyDoctorScreen extends StatefulWidget {
  /// true = read the India paper trades (/api/india/doctor, amounts in Rs); false = crypto (amounts in USDT).
  final bool india;
  const StrategyDoctorScreen({super.key, this.india = false});

  @override
  State<StrategyDoctorScreen> createState() => _StrategyDoctorScreenState();
}

class _StrategyDoctorScreenState extends State<StrategyDoctorScreen> {
  Map<String, dynamic>? _data;
  String _unit = 'USDT';
  String _buyName = 'BUY';
  String _sellName = 'SELL';
  bool _loading = true;
  bool _failed = false;
  String _err = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 60), (_) => _load(silent: true));
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load({bool silent = false}) async {
    if (!silent && mounted) setState(() => _loading = _data == null);
    Map<String, dynamic>? r;
    if (widget.india) {
      try {
        r = Map<String, dynamic>.from(await IndiaApi(context.read<AppProvider>().baseUrl).get('/doctor') as Map);
      } catch (_) {
        r = null;
      }
    } else {
      try {
        r = await _doctorFetch(context.read<AppProvider>().baseUrl);
        _err = '';
      } on TimeoutException {
        r = null;
        _err = 'No answer within 20 seconds.';
      } catch (e) {
        r = null;
        _err = '$e';
      }
    }
    if (!mounted) return;
    setState(() {
      _loading = false;
      if (r != null) {
        _data = r;
        _unit = '${r['unit'] ?? 'USDT'}';
        final sn = _map(r['side_names']);
        _buyName = '${sn['BUY'] ?? 'BUY'}';
        _sellName = '${sn['SELL'] ?? 'SELL'}';
        _failed = false;
      } else {
        _failed = _data == null;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text(widget.india ? 'India Strategy Doctor' : 'Strategy Doctor', style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
        actions: [
          if (!widget.india)
            IconButton(
              icon: const Icon(Icons.description_outlined),
              tooltip: 'AI Report',
              onPressed: () {
                AppHaptics.light();
                Navigator.of(context).push(OwlRoute(builder: (_) => const AiReportScreen()));
              },
            ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: () {
              AppHaptics.light();
              _load();
            },
          ),
        ],
      ),
      body: SafeArea(child: _body(context)),
    );
  }

  Widget _body(BuildContext context) {
    final p = context.palette;
    final d = _data;
    if (d == null) {
      if (_failed) {
        return Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text('Could not load the report.', style: context.type.secondary),
            if (_err.isNotEmpty) Padding(padding: const EdgeInsets.fromLTRB(24, 6, 24, 0), child: Text(_err, textAlign: TextAlign.center, style: context.type.secondary)),
            const SizedBox(height: 12),
            FilledButton(onPressed: _load, child: const Text('Retry')),
          ]),
        );
      }
      return Center(child: CircularProgressIndicator(color: p.accent));
    }
    final sample = _i(d['sample']);
    final enough = d['enough'] == true;
    final headline = (d['headline'] is List) ? (d['headline'] as List).map((e) => '$e').toList() : <String>[];
    final avoid = _list(d['avoid']);
    final take = _list(d['take']);
    final zones = _list(d['sd_zones']);
    final sdRules = _list(d['sd_rules']);
    final mistakes = _list(d['mistakes']);
    final story = _map(d['loss_story']);
    final post = _map(d['post_exit']);
    final ready = _map(d['data_ready']);
    final fin = _map(d['final']);
    final notes = (d['notes'] is List) ? (d['notes'] as List).map((e) => '$e').toList() : <String>[];

    return RefreshIndicator(
      onRefresh: () => _load(silent: true),
      child: ListView(
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, 4, AppSpacing.l, 32),
        children: [
          _card(context, accent: enough ? p.accent : p.warning, children: [
            Row(children: [
              Icon(Icons.medical_services_outlined, size: 18, color: p.accent),
              const SizedBox(width: 8),
              Expanded(child: Text('What the Doctor found', style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
              _chip(context, enough ? '$sample trades' : 'Learning $sample/${_i(d['min_sample'])}', enough ? p.accent : p.warning),
            ]),
            const SizedBox(height: 10),
            for (final h in headline) _bullet(context, h),
          ]),
          if (_map(d['verdict']).isNotEmpty) ...[
            _title(context, 'Doctor Verdict'),
            DoctorVerdictCard(verdict: _map(d['verdict'])),
          ],
          if (sample > 0 && enough) ...[
            _title(context, 'Avoid these entries'),
            if (avoid.isEmpty) _empty(context, 'No avoid rule passed the checks yet.'),
            for (final r in avoid) _ruleTile(context, r, true),
            _title(context, 'Take these entries'),
            if (take.isEmpty) _empty(context, 'No take rule passed the checks yet.'),
            for (final r in take) _ruleTile(context, r, false),
          ],
          if (sample > 0) ...[
            _title(context, 'SD rule test'),
            for (final r in sdRules) _sdRuleTile(context, r),
            _zoneTable(context, zones),
            _title(context, 'Mistake map'),
            for (final m in mistakes) _mistakeTile(context, m),
            _title(context, 'Loss story'),
            _storyCard(context, story),
          ],
          _title(context, 'After the exit'),
          _postCard(context, post),
          if (sample > 0) ...[
            _title(context, 'Data check'),
            _card(context, children: [
              _kv(context, 'ADX saved on', '${_i(ready['adx'])} of ${_i(ready['total'])} trades'),
              _kv(context, 'EMA distance saved on', '${_i(ready['gap'])} of ${_i(ready['total'])} trades'),
              _kv(context, 'Higher-TF trend saved on', '${_i(ready['htf'])} of ${_i(ready['total'])} trades'),
              const SizedBox(height: 4),
              Text('These three are saved only for trades opened after the update. Older trades are left out of those groups.',
                  style: context.type.metadata),
            ]),
            _title(context, 'Bottom line'),
            _finalCard(context, fin),
            const SizedBox(height: 10),
            for (final n in notes) Padding(padding: const EdgeInsets.only(bottom: 4), child: Text('• $n', style: context.type.metadata)),
          ],
        ],
      ),
    );
  }

  // ---------- pieces ----------
  Widget _card(BuildContext context, {required List<Widget> children, Color? accent}) {
    final p = context.palette;
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: (accent ?? p.glassBorder).withOpacity(accent == null ? 1 : 0.55)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
    );
  }

  Widget _title(BuildContext context, String t) => Padding(
        padding: const EdgeInsets.fromLTRB(2, 14, 2, 8),
        child: Text(t.toUpperCase(), style: context.type.label.copyWith(fontWeight: FontWeight.w800, letterSpacing: 1.1)),
      );

  Widget _empty(BuildContext context, String t) => _card(context, children: [Text(t, style: context.type.secondary)]);

  Widget _bullet(BuildContext context, String t) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Padding(
            padding: const EdgeInsets.only(top: 6, right: 8),
            child: Container(width: 5, height: 5, decoration: BoxDecoration(color: context.palette.accent, shape: BoxShape.circle)),
          ),
          Expanded(child: Text(t, style: context.type.secondary.copyWith(color: context.palette.textPrimary, height: 1.35))),
        ]),
      );

  Widget _chip(BuildContext context, String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
        child: Text(t, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
      );

  Widget _kv(BuildContext context, String k, String v, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Row(children: [
          Expanded(child: Text(k, style: context.type.secondary)),
          Text(v, style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w700, color: color)),
        ]),
      );

  Widget _ruleTile(BuildContext context, Map<String, dynamic> r, bool avoid) {
    final p = context.palette;
    final status = '${r['status']}';
    final c = status == 'confirmed' ? p.profit : (status == 'not_sure' ? p.loss : p.warning);
    final txt = status == 'confirmed' ? 'Confirmed' : (status == 'not_sure' ? 'Not sure' : 'Waiting');
    final hasTest = r['avg_test'] != null;
    return _card(context, accent: c, children: [
      Row(children: [
        Expanded(child: Text('${avoid ? 'Avoid' : 'Take'}: ${r['label']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 14))),
        const SizedBox(width: 8),
        _chip(context, txt, c),
      ]),
      const SizedBox(height: 2),
      Text('${r['title']}', style: context.type.metadata),
      const SizedBox(height: 8),
      _kv(context, 'Found on older ${_i(r['n_train'])} trades', 'avg ${_sg(_d(r['avg_train']), 2)}', color: _pnlColor(context, _d(r['avg_train']))),
      _kv(context, hasTest ? 'Re-checked on newest ${_i(r['n_test'])} trades' : 'Newest trades in this group', hasTest ? 'avg ${_sg(_d(r['avg_test']), 2)}' : '${_i(r['n_test'])} so far (need 5)',
          color: hasTest ? _pnlColor(context, _d(r['avg_test'])) : null),
      if (avoid && r['saved_roi'] != null)
        _kv(context, 'If skipped, over all ${_i(r['n_all'])} such trades', '${_sg(_d(r['saved_roi']))} pts  ·  ${_sg(_d(r['saved_usdt']), 2)} $_unit',
            color: _pnlColor(context, _d(r['saved_roi']))),
      if (!avoid) _kv(context, 'All ${_i(r['n_all'])} such trades', 'win ${_d(r['wr_all']).toStringAsFixed(0)}%  ·  avg ${_sg(_d(r['avg_all']), 2)}', color: _pnlColor(context, _d(r['avg_all']))),
    ]);
  }

  Widget _sdRuleTile(BuildContext context, Map<String, dynamic> r) {
    final p = context.palette;
    final b = _map(r['blocked']);
    final k = _map(r['kept']);
    final good = _d(b['sum']) < 0 && _i(b['n']) >= 10;
    final c = _i(b['n']) < 10 ? p.warning : (good ? p.profit : p.loss);
    return _card(context, accent: c, children: [
      Text('${r['label']}', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 14)),
      const SizedBox(height: 6),
      Text('${r['verdict']}', style: context.type.secondary.copyWith(color: p.textPrimary, height: 1.35)),
      const SizedBox(height: 8),
      _kv(context, 'Blocked side', '${_i(b['n'])} trades · win ${_d(b['wr']).toStringAsFixed(0)}% · ${_sg(_d(b['sum']))} pts', color: _pnlColor(context, _d(b['sum']))),
      _kv(context, 'Allowed side', '${_i(k['n'])} trades · win ${_d(k['wr']).toStringAsFixed(0)}% · ${_sg(_d(k['sum']))} pts', color: _pnlColor(context, _d(k['sum']))),
    ]);
  }

  Widget _cell(BuildContext context, Map<String, dynamic> s) {
    final n = _i(s['n']);
    if (n == 0) return Center(child: Text('-', style: context.type.metadata));
    final avg = _d(s['avg']);
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text(_sg(avg, 1), style: TextStyle(color: _pnlColor(context, avg), fontWeight: FontWeight.w800, fontSize: 12.5)),
      Text('${_d(s['wr']).toStringAsFixed(0)}% · $n', style: context.type.metadata.copyWith(fontSize: 10)),
    ]);
  }

  Widget _zoneTable(BuildContext context, List<Map<String, dynamic>> zones) {
    return _card(context, children: [
      Text('Where price sat in the SD bands at entry', style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13)),
      const SizedBox(height: 2),
      Text('Each box: average ROI pts, then win % · trades', style: context.type.metadata),
      const SizedBox(height: 8),
      Row(children: [
        const Expanded(flex: 4, child: SizedBox()),
        Expanded(flex: 3, child: Center(child: Text(_buyName, textAlign: TextAlign.center, style: context.type.label.copyWith(fontWeight: FontWeight.w800)))),
        Expanded(flex: 3, child: Center(child: Text(_sellName, textAlign: TextAlign.center, style: context.type.label.copyWith(fontWeight: FontWeight.w800)))),
      ]),
      const Divider(height: 10),
      for (final z in zones)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(children: [
            Expanded(flex: 4, child: Text('${z['zone']}', style: context.type.secondary.copyWith(fontSize: 12))),
            Expanded(flex: 3, child: _cell(context, _map(z['buy']))),
            Expanded(flex: 3, child: _cell(context, _map(z['sell']))),
          ]),
        ),
    ]);
  }

  Widget _mistakeTile(BuildContext context, Map<String, dynamic> m) {
    final p = context.palette;
    final buckets = _list(m['buckets']);
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: p.glassBorder),
      ),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 14),
          childrenPadding: const EdgeInsets.fromLTRB(14, 0, 14, 12),
          title: Text('${m['title']}', style: context.type.primary.copyWith(fontSize: 13, fontWeight: FontWeight.w700)),
          children: [
            for (final b in buckets)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Row(children: [
                  Expanded(flex: 5, child: Text('${b['label']}', style: context.type.secondary.copyWith(fontSize: 12))),
                  Expanded(
                    flex: 3,
                    child: Text('win ${_d(b['wr']).toStringAsFixed(0)}% · ${_i(b['n'])}', style: context.type.metadata, textAlign: TextAlign.right),
                  ),
                  SizedBox(
                    width: 58,
                    child: Text('${_sg(_d(b['avg']), 2)}', textAlign: TextAlign.right, style: TextStyle(color: _pnlColor(context, _d(b['avg'])), fontWeight: FontWeight.w800, fontSize: 12.5)),
                  ),
                ]),
              ),
          ],
        ),
      ),
    );
  }

  Widget _bar(BuildContext context, String label, int n, int total, Color c) {
    final f = total <= 0 ? 0.0 : (n / total).clamp(0.0, 1.0);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(label, style: context.type.secondary.copyWith(fontSize: 12.5))),
          Text('$n  (${(f * 100).toStringAsFixed(0)}%)', style: TextStyle(color: c, fontWeight: FontWeight.w800, fontSize: 12.5)),
        ]),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(value: f, minHeight: 7, backgroundColor: c.withOpacity(0.12), valueColor: AlwaysStoppedAnimation(c)),
        ),
      ]),
    );
  }

  Widget _storyCard(BuildContext context, Map<String, dynamic> s) {
    final p = context.palette;
    final known = _i(s['known']);
    if (_i(s['losers']) == 0 || known == 0) {
      return _empty(context, 'No losing trades with saved peak data yet.');
    }
    return _card(context, children: [
      _bar(context, 'Never went into profit (entry was wrong)', _i(s['never_green']), known, p.loss),
      _bar(context, 'Was in profit first, then lost (exit / TP problem)', _i(s['green_then_lost']), known, p.warning),
      _bar(context, 'Touched TP1, then still lost', _i(s['hit_tp1_then_lost']), known, p.warning),
      const SizedBox(height: 6),
      if (_i(s['green_then_lost']) > 0)
        _kv(context, 'Average peak before those losses', '${_sg(_d(s['avg_peak_green_losers']), 1)} ROI pts'),
      if (s['winner_captured_pct'] != null)
        _kv(context, 'Winners keep this much of their peak', '${_d(s['winner_captured_pct']).toStringAsFixed(0)}%'),
    ]);
  }

  Widget _postCard(BuildContext context, Map<String, dynamic> post) {
    final lines = (post['lines'] is List) ? (post['lines'] as List).map((e) => '$e').toList() : <String>[];
    return _card(context, children: [
      for (final l in lines) _bullet(context, l),
      if (lines.isEmpty) Text('Collecting data.', style: context.type.secondary),
    ]);
  }

  Widget _finalCard(BuildContext context, Map<String, dynamic> f) {
    final p = context.palette;
    final net = _d(f['net_pnl']);
    final conf = _i(f['confirmed_rules']);
    return _card(context, accent: _pnlColor(context, net), children: [
      _kv(context, 'Net P&L after fee', '${_sg(net, 2)} $_unit', color: _pnlColor(context, net)),
      _kv(context, 'Fee paid in total', '${_d(f['fee_total']).toStringAsFixed(2)} $_unit'),
      const Divider(height: 14),
      if (conf > 0 && f['with_rules_pnl'] != null) ...[
        _kv(context, 'If the $conf confirmed rule${conf == 1 ? '' : 's'} had been on', '${_sg(_d(f['with_rules_pnl']), 2)} $_unit',
            color: _pnlColor(context, _d(f['with_rules_pnl']))),
        _kv(context, 'Trades skipped by them', '${_i(f['trades_avoided'])}'),
        Text('That is ${_sg(_d(f['delta_usdt']), 2)} $_unit versus what the bot did. Past results only - not a promise.', style: context.type.metadata),
      ] else
        Text('No confirmed rule yet, so there is no "rule would have changed" number.', style: context.type.secondary.copyWith(color: p.textSecondary)),
    ]);
  }
}

/// Compact Dashboard card - first headline lines, tap opens the full Strategy Doctor.
class StrategyDoctorCard extends StatefulWidget {
  const StrategyDoctorCard({super.key});

  @override
  State<StrategyDoctorCard> createState() => _StrategyDoctorCardState();
}

class _StrategyDoctorCardState extends State<StrategyDoctorCard> {
  Map<String, dynamic>? _data;
  Timer? _timer;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
    _timer = Timer.periodic(const Duration(seconds: 90), (_) => _load()); // closed trades change slowly
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (!mounted) return;
    Map<String, dynamic>? r;
    try {
      r = await _doctorFetch(context.read<AppProvider>().baseUrl);
    } catch (_) {
      r = null;
    }
    if (!mounted) return;
    setState(() {
      if (r != null) _data = r;
      _failed = r == null && _data == null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    final n = d == null ? 0 : _i(d['sample']);
    final enough = d != null && d['enough'] == true;
    final heads = (d != null && d['headline'] is List) ? (d['headline'] as List).map((e) => '$e').toList() : <String>[];
    final avoidConf = d == null ? 0 : _list(d['avoid']).where((r) => r['status'] == 'confirmed').length;
    final badge = d == null ? (_failed ? 'No answer' : 'Loading') : (n == 0 ? 'No trades yet' : (enough ? (avoidConf > 0 ? '$avoidConf leak${avoidConf == 1 ? '' : 's'} confirmed' : 'No leak confirmed') : 'Learning $n/${_i(d['min_sample'])}'));
    final bc = d == null || n == 0 ? p.textMuted : (enough ? (avoidConf > 0 ? p.warning : p.profit) : p.warning);
    return Container(
      margin: const EdgeInsets.only(bottom: AppSpacing.l),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: p.glassBorder),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        onTap: () {
          AppHaptics.light();
          Navigator.of(context).push(OwlRoute(builder: (_) => const StrategyDoctorScreen()));
        },
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: AppSpacing.m, vertical: AppSpacing.m - 2),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(children: [
              Icon(Icons.medical_services_outlined, size: 16, color: p.accent),
              const SizedBox(width: 8),
              Expanded(child: Text('Strategy Doctor', style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w700))),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: bc.withOpacity(0.16), borderRadius: BorderRadius.circular(8)),
                child: Text(badge, style: TextStyle(color: bc, fontSize: 10.5, fontWeight: FontWeight.w800)),
              ),
              const SizedBox(width: 4),
              Icon(Icons.chevron_right_rounded, size: 18, color: p.textMuted),
            ]),
            const SizedBox(height: 6),
            Text(
              (d == null && _failed)
                  ? 'The backend did not give a report: ${context.read<AppProvider>().aiLastError ?? 'unknown reason'}. Tap to retry.'
                  : (heads.length > 2 ? heads[2] : (heads.isNotEmpty ? heads.first : 'Tap to see which entries lose and which win.')),
              maxLines: 3,
              overflow: TextOverflow.ellipsis,
              style: context.type.metadata.copyWith(height: 1.35),
            ),
          ]),
        ),
      ),
    );
  }
}
