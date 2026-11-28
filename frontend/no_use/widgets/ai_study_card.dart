import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// "Exit / Wait" tab (Phase 2 + 3). Everything comes from the backend
/// (GET /api/ai/exit_study and /api/ai/wait_study, Shadow Lab replay). Nothing is calculated on the
/// phone and nothing here opens, blocks or closes a trade.
///  1) Exit: in which condition is "close fully at TP1" better than "hold to TP4" (and when not).
///  2) Wait: coins that keep hitting SL, sideways entries, and the test "enter only when Z + TSI both agree".
class AiStudyCard extends StatefulWidget {
  const AiStudyCard({super.key});

  @override
  State<AiStudyCard> createState() => _AiStudyCardState();
}

class _AiStudyCardState extends State<AiStudyCard> {
  Map<String, dynamic>? _x;
  Map<String, dynamic>? _w;
  bool _failed = false;
  String _tf = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 90), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final pr = context.read<AppProvider>();
    final x = await pr.fetchAiExitStudy(tf: _tf);
    final w = await pr.fetchAiWaitStudy(tf: _tf);
    if (!mounted) return;
    setState(() {
      if (x != null || w != null) {
        _x = x ?? _x;
        _w = w ?? _w;
        _failed = false;
        if (_tf.isEmpty) _tf = ((x ?? w)?['tf'] ?? '3m').toString();
      } else if (_x == null && _w == null) {
        _failed = true;
      }
    });
  }

  static double _n(dynamic v) => (v is num) ? v.toDouble() : 0.0;
  static int _i(dynamic v) => (v is num) ? v.toInt() : 0;
  static Map<String, dynamic> _m(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  static List<Map<String, dynamic>> _l(dynamic v) =>
      v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  Color _vc(AppPalette p, String v) =>
      (v == 'CLEAR') ? p.profit : (v == 'NO' ? p.loss : (v == 'SAME' ? p.textMuted : p.warning));

  String _vt(String v) {
    switch (v) {
      case 'CLEAR':
        return 'PAKKA';
      case 'MAYBE':
        return 'SHAYAD';
      case 'SAME':
        return 'BOT THEEK';
      case 'NO':
        return 'NAHI';
      default:
        return 'KAM DATA';
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

  Widget _pill(AppPalette p, String t, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.16), borderRadius: BorderRadius.circular(8)),
        child: Text(t, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _tfRow(BuildContext context) => Row(children: [
        for (final t in const ['3m', '5m', '15m'])
          Padding(
            padding: const EdgeInsets.only(right: 8),
            child: ChoiceChip(
              label: Text(t),
              selected: _tf == t,
              onSelected: (_) {
                setState(() => _tf = t);
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

  Widget _exit(BuildContext context, AppPalette p) {
    final x = _x;
    if (x == null) return const SizedBox.shrink();
    final nice = _m(x['nice']);
    final scs = _l(x['scenarios']);
    final ov = _m(x['overall']);
    final rules = (x['rules'] is List) ? (x['rules'] as List).map((e) => e.toString()).toList() : <String>[];
    return _box(p,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(context, 'Exit: kab TP1 pe band, kab hold', '${_i(x['signals'])} signals ka replay, fee ke baad'),
          Text((x['headline'] ?? '').toString(), style: context.type.primary),
          if (ov.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text('Sab signals ka average ROI (har exit rule se):', style: context.type.metadata),
            const SizedBox(height: 4),
            for (final r in rules)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(children: [
                  Expanded(child: Text((nice[r] ?? r).toString(), style: context.type.secondary)),
                  Text('${_n(ov[r]) >= 0 ? '+' : ''}${_n(ov[r]).toStringAsFixed(2)}%',
                      style: context.type.secondary.copyWith(
                          fontWeight: FontWeight.w700, color: _n(ov[r]) >= 0 ? p.profit : p.loss)),
                ]),
              ),
          ],
          for (final s in scs) ...[
            const Divider(height: 18),
            Row(children: [
              Expanded(child: Text((s['label'] ?? '').toString(), style: context.type.primary.copyWith(fontWeight: FontWeight.w700))),
              _pill(p, _vt((s['verdict'] ?? '').toString()), _vc(p, (s['verdict'] ?? '').toString())),
            ]),
            const SizedBox(height: 3),
            Text('${_i(s['n'])} signals', style: context.type.metadata),
            const SizedBox(height: 3),
            Text((s['msg'] ?? '').toString(), style: context.type.secondary),
          ],
        ]));
  }

  Widget _wait(BuildContext context, AppPalette p) {
    final w = _w;
    if (w == null) return const SizedBox.shrink();
    final c = _m(w['confirm']);
    final sd = _m(w['sideways']);
    final coins = _l(w['coins']);
    final v = (w['verdict'] ?? 'TOO_FEW').toString();
    return _box(p,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          _title(context, 'Wait: dono confirm tabhi entry', 'Sideways aur ulte signals se bachne ka test'),
          Row(children: [
            Expanded(child: Text((w['headline'] ?? '').toString(), style: context.type.primary)),
            const SizedBox(width: 8),
            _pill(p, _vt(v), _vc(p, v)),
          ]),
          if (c.isNotEmpty) ...[
            const SizedBox(height: 10),
            _kv(context, p, 'Bot abhi (sab signals)', '${_n(c['bot_avg']).toStringAsFixed(2)}%  |  win ${_n(c['bot_wr']).toStringAsFixed(0)}%'),
            _kv(context, p, 'Sirf dono confirm', '${_n(c['keep_avg']).toStringAsFixed(2)}%  |  win ${_n(c['keep_wr']).toStringAsFixed(0)}%  (${_i(c['keep_n'])} trade)'),
            _kv(context, p, 'Skip hue signal', '${_i(c['skip_n'])}'),
            _kv(context, p, 'Bache loss vs gaya profit', '${_n(c['saved_loss']).toStringAsFixed(0)} vs ${_n(c['lost_profit']).toStringAsFixed(0)}'),
          ],
          if (sd.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text('Sideways entry: ${_i(sd['n'])} signal (${_n(sd['share']).toStringAsFixed(0)}%), avg ${_n(sd['avg']).toStringAsFixed(2)}%, win ${_n(sd['win_rate']).toStringAsFixed(0)}%',
                style: context.type.secondary),
          ],
          if (coins.isNotEmpty) ...[
            const Divider(height: 18),
            Text('Baar baar SL wale coin', style: context.type.primary.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            for (final k in coins)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(children: [
                  Expanded(child: Text((k['sym'] ?? '').toString(), style: context.type.secondary)),
                  Text('SL ${_i(k['sl'])}/${_i(k['n'])}  (sideways ${_i(k['side_sl'])})', style: context.type.metadata),
                ]),
              ),
          ],
        ]));
  }

  Widget _kv(BuildContext context, AppPalette p, String k, String v) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [
          Expanded(child: Text(k, style: context.type.secondary)),
          Text(v, style: context.type.secondary.copyWith(fontWeight: FontWeight.w700)),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return ListView(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.s, AppSpacing.m, 96),
      children: [
        if (_x == null && _w == null)
          Padding(
            padding: const EdgeInsets.only(top: 40),
            child: Center(
              child: Text(_failed ? 'Data nahi mila - backend check karo.' : 'Load ho raha hai...',
                  style: context.type.secondary.copyWith(color: p.textMuted)),
            ),
          )
        else ...[
          _tfRow(context),
          const SizedBox(height: 10),
          _exit(context, p),
          _wait(context, p),
          Text('Ye sirf dekhna hai. Bot ka exit ya entry is screen se nahi badalta.', style: context.type.metadata),
        ],
      ],
    );
  }
}
