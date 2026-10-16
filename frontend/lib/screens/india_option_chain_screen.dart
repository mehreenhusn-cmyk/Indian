import 'dart:async';

import 'package:flutter/material.dart';

import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import 'india_chart_screen.dart';

/// Option chain: CALL | strike | PUT, with ITM shading, ATM marker and tick-to-pin.
///  * tap a CE/PE cell  -> the NEXT trade on that side buys that strike (tap again to unpin)
///  * long-press a cell -> pin by TARGET PREMIUM instead (closest strike to that price)
///  * ITM / ATM / OTM chips -> default for all next trades today (resets to ITM next day)
class IndiaChainTab extends StatefulWidget {
  final IndiaApi api;
  final List<String> unders;
  final VoidCallback onChanged;
  const IndiaChainTab({super.key, required this.api, required this.unders, required this.onChanged});

  @override
  State<IndiaChainTab> createState() => _IndiaChainTabState();
}

class _IndiaChainTabState extends State<IndiaChainTab> {
  Timer? _timer;
  bool _busy = false;
  String? _error;
  bool _stale = false; // Fyers limit: the chain on screen is the last good one
  String _note = '';
  String? _u;
  String? _expiry; // null = automatic (nearest tradable)
  Map<String, dynamic>? _ch;
  final ScrollController _scroll = ScrollController();
  final GlobalKey _atmKey = GlobalKey();
  bool _centered = false; // scrolled to the ATM row once per index / expiry

  @override
  void initState() {
    super.initState();
    _u = widget.unders.isNotEmpty ? widget.unders.first : 'NIFTY';
    _load();
    _timer = Timer.periodic(const Duration(seconds: 2), (_) => _load());
  }

  @override
  void dispose() {
    _scroll.dispose();
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    if (_busy || !mounted) return;
    _busy = true;
    try {
      final q = '/chain?underlying=$_u&width=12${_expiry != null ? '&expiry=$_expiry' : ''}';
      final ch = Map<String, dynamic>.from(await widget.api.get(q) as Map);
      if (mounted) {
        setState(() {
          _ch = ch;
          _error = null;
          _stale = ch['stale'] == true;
          _note = '${ch['error'] ?? ''}';
        });
        if (!_centered) _centerOnSpot();
      }
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    } finally {
      _busy = false;
    }
  }

  /// Scroll so the ATM (spot) row sits in the middle of the screen.
  void _centerOnSpot({int tries = 0}) {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final ctx = _atmKey.currentContext;
      if (ctx != null) {
        _centered = true;
        Scrollable.ensureVisible(ctx, alignment: 0.4, duration: const Duration(milliseconds: 300), curve: Curves.easeOut);
        return;
      }
      // the ATM row is not built yet (list is lazy): jump close to it first, then fine-tune next frame
      final rows = (_ch?['rows'] as List?) ?? [];
      final i = rows.indexWhere((r) => (r as Map)['atm'] == true);
      if (i >= 0 && tries < 3 && _scroll.hasClients) {
        final target = i * 58.0 - 150.0;
        _scroll.jumpTo(target.clamp(0.0, _scroll.position.maxScrollExtent));
        _centerOnSpot(tries: tries + 1);
      }
    });
  }

  Future<void> _post(String path, Map<String, dynamic> body) async {
    AppHaptics.light();
    try {
      await widget.api.post(path, body);
    } catch (e) {
      if (mounted) setState(() => _error = friendlyError(e));
    }
    await _load();
    widget.onChanged();
  }

  Future<void> _pickExpiry(Map<String, dynamic> ch) async {
    final list = ((ch['expiries'] as List?) ?? []).map((e) => '$e').toList();
    final tradeExp = '${ch['trade_expiry'] ?? ''}';
    final chosen = await showModalBottomSheet<String>(
      context: context,
      builder: (ctx) => SafeArea(
        child: ListView(shrinkWrap: true, children: [
          const Padding(padding: EdgeInsets.all(16), child: Text('Expiry', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 18))),
          ...list.map((e) => ListTile(
                title: Text(dmy(e)),
                subtitle: e == tradeExp ? const Text('Trades use this expiry') : null,
                trailing: Icon(e == '${ch['expiry']}' ? Icons.radio_button_checked : Icons.radio_button_off),
                onTap: () => Navigator.pop(ctx, e),
              )),
        ]),
      ),
    );
    if (chosen != null) {
      setState(() => _expiry = chosen);
      _load();
    }
  }

  Future<void> _askPremium(String side) async {
    final ctl = TextEditingController(text: '100');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Target premium for next $side'),
        content: TextField(
          controller: ctl,
          keyboardType: const TextInputType.numberWithOptions(decimal: true),
          decoration: const InputDecoration(prefixText: '₹ ', helperText: 'Buys the strike whose premium is closest'),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Pin')),
        ],
      ),
    );
    final v = double.tryParse(ctl.text.trim());
    if (ok == true && v != null && v > 0) {
      _post('/pin', {'underlying': _u, 'side': side, 'type': 'premium', 'target': v});
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final ch = _ch;
    final parts = ch == null ? null : _content(p, t, ch);
    // Index chips, spot and the CALL | expiry | PUT bar stay pinned; only the strikes scroll.
    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, AppSpacing.s, AppSpacing.l, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: IChoice<String>(
                values: widget.unders,
                current: _u,
                label: (v) => v,
                onPick: (v) {
                  setState(() {
                    _u = v;
                    _expiry = null;
                    _ch = null;
                    _centered = false;
                  });
                  _load();
                },
              ),
            ),
            IChip('Spot', selected: false, icon: Icons.my_location, onTap: () {
              _centered = false;
              _centerOnSpot();
            }),
          ]),
          const SizedBox(height: 6),
          if (_error != null) Text(_error!, style: t.secondary.copyWith(color: p.loss)),
          if (_stale)
            Text(
                ((ch?['rows'] as List?) ?? []).isEmpty
                    ? 'Option prices are not ready yet${_note.isNotEmpty ? ' - ${friendlyError(_note)}' : ''}. Retrying...'
                    : 'Slow down - showing last data${_note.isNotEmpty ? ' (${friendlyError(_note)})' : ''}',
                style: t.secondary.copyWith(color: p.warning)),
          if (parts != null) ...parts[0],
        ]),
      ),
      Expanded(
        child: ListView(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.l),
          children: [
            if (ch == null && _error == null) const Center(child: Padding(padding: EdgeInsets.all(24), child: CircularProgressIndicator())),
            if (parts != null) ...parts[1],
          ],
        ),
      ),
    ]);
  }

  List<List<Widget>> _content(AppPalette p, AppText t, Map<String, dynamic> ch) {
    final rows = ((ch['rows'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    final hasOi = ch['has_oi'] == true;
    final pins = ((ch['pins'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
    final dm = ch['day_mode'] == null ? null : Map<String, dynamic>.from(ch['day_mode'] as Map);
    final def = Map<String, dynamic>.from((ch['default_mode'] as Map?) ?? {'mode': 'ITM', 'depth': 1});
    final curMode = '${(dm ?? def)['mode']}';
    final curDepth = ((dm ?? def)['depth'] as num?)?.toInt() ?? 1;
    final tradeExp = '${ch['trade_expiry'] ?? ''}';
    final exp = '${ch['expiry'] ?? ''}';

    return [
      [
      // spot header (one compact block)
      Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
        Text(inr(nd(ch['spot'])).replaceFirst('₹', ''), style: IT.big(context)),
        const SizedBox(width: 8),
        IPill('${ch['status']}', '${ch['status']}' == 'OPEN' ? p.profit : p.textSecondary),
        const Spacer(),
        Text('Lot ${ch['lot']}  ·  ${inr(nd(ch['budget']), dp: 0)}', style: IT.small(context)),
      ]),
      Text('As on ${dayTime(ch['as_on'])} IST', style: IT.small(context)),
      const SizedBox(height: 6),
      // CALL | expiry | PUT header
      Row(children: [
        Expanded(child: Container(padding: const EdgeInsets.symmetric(vertical: 9), color: p.profit.withOpacity(0.14), child: Center(child: Text('CALL', style: TextStyle(color: p.profit, fontWeight: FontWeight.w700, fontSize: 12))))),
        GestureDetector(
          onTap: () => _pickExpiry(ch),
          child: Container(
            width: 112,
            padding: const EdgeInsets.symmetric(vertical: 9),
            color: p.surfaceHigher,
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              Text(dmy(exp), style: IT.small(context).copyWith(color: p.textPrimary, fontWeight: FontWeight.w700)),
              Icon(Icons.keyboard_arrow_down, color: p.textSecondary, size: 16),
            ]),
          ),
        ),
        Expanded(child: Container(padding: const EdgeInsets.symmetric(vertical: 9), color: p.loss.withOpacity(0.14), child: Center(child: Text('PUT', style: TextStyle(color: p.loss, fontWeight: FontWeight.w700, fontSize: 12))))),
      ]),
      if (tradeExp.isNotEmpty && tradeExp != exp)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text('Bot trades use ${dmy(tradeExp)}, not this expiry.', style: IT.small(context).copyWith(color: p.warning)),
        ),
        const SizedBox(height: 2),
      ],
      [
        ...rows.map((r) => _row(p, t, r, false)),
        const SizedBox(height: AppSpacing.m),
      // default mode for next trades
      IHeading('NEXT TRADES BUY', trailing: dm == null ? null : TextButton(onPressed: () => _post('/day_mode', {'mode': null}), child: const Text('Reset'))),
      IChoice<String>(
        values: const ['ITM', 'ATM', 'OTM'],
        current: curMode,
        label: (v) => v,
        onPick: (v) => _post('/day_mode', {'mode': v, 'depth': v == 'ATM' ? 1 : curDepth}),
      ),
      if (curMode != 'ATM') ...[
        const SizedBox(height: 6),
        Row(children: [
          Text('Depth', style: IT.small(context)),
          const SizedBox(width: 8),
          IChoice<int>(
            values: const [1, 2, 3],
            current: curDepth,
            label: (v) => '$v',
            onPick: (v) => _post('/day_mode', {'mode': curMode, 'depth': v}),
          ),
        ]),
      ],
      const SizedBox(height: 4),
      Text(dm == null ? 'Default ITM. Pick a mode to change it for today only.' : 'Set for today. Goes back to ITM tomorrow.', style: IT.small(context)),
      const SizedBox(height: AppSpacing.m),

      if (pins.isNotEmpty) ...[
        Wrap(spacing: 8, runSpacing: 4, children: pins.map((pn) {
          final label = pn['type'] == 'strike'
              ? '${pn['side']} ${pn['strike']}'
              : (pn['type'] == 'premium' ? '${pn['side']} ~₹${nd(pn['target']).toStringAsFixed(0)}' : '${pn['side']} ${pn['mode']}${pn['depth']}');
          return InputChip(
            label: Text('Pinned $label'),
            onDeleted: () => _post('/pin/clear', {'underlying': _u, 'side': pn['side']}),
          );
        }).toList()),
        const SizedBox(height: AppSpacing.m),
      ],

        Text('Tap a premium = next trade on that side buys that strike (tap again to unpin).  Long-press = pin by target premium.  Tap the chart icon = chart of that option.  Greyed = costs more than your budget.',
            style: IT.small(context)),
        const SizedBox(height: AppSpacing.huge),
      ],
    ];
  }

  Widget _row(AppPalette p, AppText t, Map<String, dynamic> r, bool hasOi) {
    final atm = r['atm'] == true;
    return Container(
      key: atm ? _atmKey : null,
      decoration: BoxDecoration(border: Border(bottom: BorderSide(color: p.border.withOpacity(0.6)))),
      child: Row(children: [
        Expanded(child: _cell(p, t, r, 'CE', hasOi)),
        Container(
          width: 112,
          padding: const EdgeInsets.symmetric(vertical: 12),
          color: atm ? p.accent.withOpacity(0.18) : null,
          child: Column(children: [
            Text(inr(nd(r['strike']), dp: 0).replaceFirst('₹', ''), style: IT.h(context).copyWith(color: p.accent)),
            if (atm) Text('ATM · spot', style: IT.small(context).copyWith(color: p.accent, fontWeight: FontWeight.w700, fontSize: 10)),
          ]),
        ),
        Expanded(child: _cell(p, t, r, 'PE', hasOi)),
      ]),
    );
  }

  Widget _cell(AppPalette p, AppText t, Map<String, dynamic> r, String side, bool hasOi) {
    final raw = r[side];
    if (raw == null) return const SizedBox(height: 56);
    final c = Map<String, dynamic>.from(raw as Map);
    final itm = c['itm'] == true;
    final pinned = c['pinned'] == true;
    final afford = c['affordable'] == true;
    final chg = c['chg'] == null ? null : nd(c['chg']);
    final align = side == 'CE' ? CrossAxisAlignment.start : CrossAxisAlignment.end;
    return InkWell(
      onTap: () {
        if (pinned) {
          _post('/pin/clear', {'underlying': _u, 'side': side});
        } else {
          _post('/pin', {'underlying': _u, 'side': side, 'type': 'strike', 'strike': r['strike']});
        }
      },
      onLongPress: () => _askPremium(side),
      child: Opacity(
        opacity: afford ? 1 : 0.45,
        child: Stack(children: [
        Container(
          width: double.infinity,
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 8),
          decoration: BoxDecoration(
            color: itm ? p.accent.withOpacity(0.07) : null,
            border: pinned ? Border.all(color: p.accent, width: 2) : null,
          ),
          child: Column(crossAxisAlignment: align, children: [
            Row(mainAxisSize: MainAxisSize.min, children: [
              if (pinned && side == 'CE') Icon(Icons.push_pin, size: 12, color: p.accent),
              Text(c['ltp'] == null ? '—' : num2(nd(c['ltp'])), style: IT.h(context)),
              if (pinned && side == 'PE') Icon(Icons.push_pin, size: 12, color: p.accent),
            ]),
            Text(
              chg == null ? '' : '${chg >= 0 ? '+' : ''}${num2(chg)} (${num2(nd(c['chg_pct']))}%)',
              style: IT.small(context).copyWith(fontSize: 10, color: pnlColor(p, chg ?? 0)),
            ),
            Text(c['cost'] == null ? '' : inr(nd(c['cost']), dp: 0), style: IT.small(context).copyWith(fontSize: 10)),
          ]),
        ),
        Positioned(
          top: 0,
          left: side == 'CE' ? null : 0,
          right: side == 'CE' ? 0 : null,
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => IndiaChartScreen(
                api: widget.api,
                underlying: _u ?? 'NIFTY',
                optionKey: '${c['key']}',
                optionTitle: '${_u ?? ''} ${inr(nd(r['strike']), dp: 0).replaceFirst('₹', '')} $side',
              ),
            )),
            child: Padding(padding: const EdgeInsets.all(8), child: Icon(Icons.candlestick_chart_outlined, size: 17, color: p.accent)),
          ),
        ),
        ]),
      ),
    );
  }
}
