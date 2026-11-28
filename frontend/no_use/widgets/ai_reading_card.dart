import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// "Reading" tab. Everything comes from the backend (GET /api/ai/reading, ai_reading.py - Shadow Lab
/// replay, net ROI after fee). Nothing is calculated on the phone and nothing here opens, blocks or
/// closes a trade. It answers: when a signal came, what did the MAIN chart, Z-score and TSI say, and
/// what happened next? Which of those readings are habits that lose money, which ones pay, and which
/// exit (scalp at TP1 or hold) the AI found best there.
class AiReadingCard extends StatefulWidget {
  const AiReadingCard({super.key});

  @override
  State<AiReadingCard> createState() => _AiReadingCardState();
}

class _AiReadingCardState extends State<AiReadingCard> {
  Map<String, dynamic>? _d;
  bool _failed = false;
  bool _busy = false;
  String _tf = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 120), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy) return;
    _busy = true;
    final r = await context.read<AppProvider>().fetchAiReading(tf: _tf);
    _busy = false;
    if (!mounted) return;
    setState(() {
      if (r != null) {
        _d = r;
        _failed = false;
        if (_tf.isEmpty) _tf = (r['tf'] ?? '3m').toString();
      } else if (_d == null) {
        _failed = true;
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];
  static String _sg(double v, {int d = 1}) => '${v >= 0 ? '+' : ''}${v.toStringAsFixed(d)}%';

  Color _vc(AppPalette p, String v) =>
      v == 'GOOD' ? p.profit : (v == 'AVOID' ? p.loss : (v == 'UNSURE' ? p.warning : p.textMuted));

  String _vt(String v, dynamic tier) {
    final t = (tier ?? '').toString();
    switch (v) {
      case 'GOOD':
        return t == 'PAKKA' ? 'ACHHA - PAKKA' : 'ACHHA - SHAYAD';
      case 'AVOID':
        return t == 'PAKKA' ? 'BACHO - PAKKA' : 'BACHO - SHAYAD';
      case 'UNSURE':
        return 'PAKKA NAHI';
      default:
        return 'NORMAL';
    }
  }

  Widget _box(AppPalette p, {required Widget child, Color? border}) => Container(
        width: double.infinity,
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: p.surfaceElevated,
          borderRadius: BorderRadius.circular(AppSpacing.radiusMedium + 2),
          border: Border.all(color: (border ?? p.border).withOpacity(0.7), width: 0.8),
        ),
        child: child,
      );

  Widget _title(BuildContext context, String t, String sub) => Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(t, style: context.type.section.copyWith(fontSize: 13)),
          Text(sub, style: context.type.metadata),
        ]),
      );

  Widget _pill(String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.16), borderRadius: BorderRadius.circular(8)),
        child: Text(t, style: TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _tfRow(BuildContext context) => Row(children: [
        for (final t in const ['3m', '5m', '15m'])
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text(t),
              selected: _tf == t,
              onSelected: (_) {
                setState(() {
                  _tf = t;
                  _d = null;
                  _failed = false;
                });
                _load();
              },
            ),
          ),
        const Spacer(),
        IconButton(
            onPressed: _load,
            icon: Icon(Icons.refresh_rounded, size: 18, color: context.palette.textMuted),
            visualDensity: VisualDensity.compact),
      ]);

  Widget _exitLine(BuildContext context, AppPalette p, Map<String, dynamic> x) {
    if (x.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Text('Exit: ${x['msg'] ?? ''}', style: context.type.metadata.copyWith(color: p.textSecondary)),
    );
  }

  /// One fact / combo row: name, verdict pill, the numbers, and (if present) the exit AI found best.
  Widget _factRow(BuildContext context, AppPalette p, Map<String, dynamic> f) {
    final v = (f['verdict'] ?? 'NORMAL').toString();
    final avg = _n(f['avg']);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Expanded(child: Text((f['label'] ?? '').toString(), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13))),
          const SizedBox(width: 8),
          _pill(_vt(v, f['tier']), _vc(p, v)),
        ]),
        const SizedBox(height: 2),
        Text(
            '${_i(f['n'])} signal (${_n(f['share']).toStringAsFixed(0)}%) | win ${_n(f['win_rate']).toStringAsFixed(0)}% | '
            'avg ${_sg(avg, d: 2)} | SL ${_n(f['sl']).toStringAsFixed(0)}% | TP1 ${_n(f['tp1']).toStringAsFixed(0)}%',
            style: context.type.metadata.copyWith(color: avg >= 0 ? p.profit : p.loss)),
        if (f['exit'] is Map) _exitLine(context, p, _m(f['exit'])),
      ]),
    );
  }

  Widget _indicators(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final gs = _l(d['indicators']);
    return Column(children: [
      for (final g in gs)
        if (_l(g['facts']).isNotEmpty)
          _box(p,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _title(context, (g['title'] ?? '').toString(), 'signal aate waqt ye dikha tha - uske baad ka result'),
                for (final f in _l(g['facts'])) _factRow(context, p, f),
              ])),
    ]);
  }

  Widget _habits(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final hs = _l(d['habits']);
    return _box(p,
        border: hs.isEmpty ? null : p.loss,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(context, 'Kya main galat use kar raha hu?', 'bure + aksar hone wale readings (naye aur purane dono data me)'),
          if (hs.isEmpty)
            Text('Abhi aisi koi aadat pakki nahi nikli. Data badhne par yahan dikhegi.', style: context.type.secondary)
          else
            for (final h in hs)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 4),
                child: Text((h['msg'] ?? '').toString(), style: context.type.secondary),
              ),
        ]));
  }

  Widget _combos(BuildContext context, AppPalette p, String title, String sub, List<Map<String, dynamic>> items, String emptyMsg) {
    return _box(p,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(context, title, sub),
          if (items.isEmpty)
            Text(emptyMsg, style: context.type.secondary)
          else
            for (final f in items) _factRow(context, p, f),
        ]));
  }

  Widget _levels(BuildContext context, AppPalette p, Map<String, dynamic> d) {
    final lv = _m(d['levels']);
    final rows = _l(lv['rows']);
    if (rows.isEmpty) return const SizedBox.shrink();
    return _box(p,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(context, 'Konse level pe indicator kaise react karta hai', 'SD zone jaha signal aaya: Z aur TSI aksar kya bole, result kya raha'),
          for (final r in rows) ...[
            const Divider(height: 16),
            Row(children: [
              Expanded(child: Text((r['zone'] ?? '').toString(), style: context.type.primary.copyWith(fontWeight: FontWeight.w700, fontSize: 13))),
              Text('${_i(r['n'])} | win ${_n(r['win_rate']).toStringAsFixed(0)}% | ${_sg(_n(r['avg']), d: 2)}',
                  style: context.type.metadata.copyWith(color: _n(r['avg']) >= 0 ? p.profit : p.loss)),
            ]),
            if (r['z_usual'] is Map)
              Text('Z aksar: ${_m(r['z_usual'])['label']} (${_n(_m(r['z_usual'])['share']).toStringAsFixed(0)}%)', style: context.type.metadata),
            if (r['tsi_usual'] is Map)
              Text('TSI aksar: ${_m(r['tsi_usual'])['label']} (${_n(_m(r['tsi_usual'])['share']).toStringAsFixed(0)}%)', style: context.type.metadata),
            for (final e in _m(r['cells']).entries)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Row(children: [
                  Expanded(child: Text(e.key.toString(), style: context.type.secondary.copyWith(fontSize: 12))),
                  Text('${_i(_m(e.value)['n'])} | win ${_n(_m(e.value)['win_rate']).toStringAsFixed(0)}% | ${_sg(_n(_m(e.value)['avg']), d: 2)}',
                      style: context.type.secondary.copyWith(
                          fontSize: 12, fontWeight: FontWeight.w700, color: _n(_m(e.value)['avg']) >= 0 ? p.profit : p.loss)),
                ]),
              ),
          ],
        ]));
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    return ListView(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, 96),
      children: [
        _tfRow(context),
        if (d == null || d['error'] != null)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: Column(children: [
              Text(
                  d != null
                      ? 'Backend me error aaya:\n${d['error']}'
                      : (_failed
                          ? 'Reading nahi mili.\n${context.read<AppProvider>().aiLastError ?? ''}'
                          : 'Load ho raha hai...\npehli baar 20-40 second lag sakte hain, ruk ja.'),
                  textAlign: TextAlign.center,
                  style: context.type.secondary.copyWith(color: p.textMuted)),
              if (d != null || _failed) ...[
                const SizedBox(height: 12),
                OutlinedButton(
                  onPressed: () {
                    setState(() {
                      _d = null;
                      _failed = false;
                    });
                    _load();
                  },
                  child: const Text('Retry'),
                ),
              ],
            ]),
          )
        else ...[
          _box(p,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                _title(context, 'Signal ke time dono indicator kya bolte hain',
                    '${_i(d['signals'])} signal ka replay, fee ke baad. Sirf dekhna hai - bot ka kuch nahi badla.'),
                Text((d['headline'] ?? '').toString(), style: context.type.primary),
                if (_m(d['overall']).isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text(
                      'Bot ka average: ${_sg(_n(_m(d['overall'])['avg']), d: 2)} | win ${_n(_m(d['overall'])['win_rate']).toStringAsFixed(0)}% | SL ${_n(_m(d['overall'])['sl']).toStringAsFixed(0)}%',
                      style: context.type.metadata),
                ],
                const SizedBox(height: 6),
                Text((d['scalp_note'] ?? '').toString(), style: context.type.metadata),
              ])),
          _habits(context, p, d),
          _combos(context, p, 'Ye combination achha raha', 'do indicator ke readings milke - purane aur naye dono data me', _l(d['best']),
              'Abhi koi combination dono hisso me pakka achha nahi nikla.'),
          _combos(context, p, 'Ye combination se bacho', 'milke nuksaan - skip ya wait karne layak', _l(d['avoid']),
              'Abhi koi combination dono hisso me pakka bura nahi nikla.'),
          _indicators(context, p, d),
          _levels(context, p, d),
          for (final c in (d['caveats'] is List ? (d['caveats'] as List) : const []))
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text('• $c', style: context.type.metadata),
            ),
        ],
      ],
    );
  }
}
