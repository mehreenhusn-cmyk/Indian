import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../services/india_api.dart';
import '../services/india_ticks.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import '../widgets/special_master.dart';
import '../widgets/special_master_settings.dart';

/// TradingView-style chart for the India terminal (white background):
///  * candles + SD bands (zones), EMA30/EMA50 with cloud, buy/sell markers, trade levels
///  * your Special Master (TSI + Z-score) panes underneath - the exact same drawing as the crypto chart
///  * candles that cross EMA50 keep their green/red border and get a BLACK body; right-edge price-axis drag scales the price like TradingView; the same chart opens for any option from the chain
///  * 1m / 3m / 5m / 15m buttons for the chart, separate "Trade TF" for the bot
///  * every indicator can be hidden / shown (remembered)
///  * drag = scroll back / forward (you can scroll into empty space on the right),
///    pinch = zoom, long-press = crosshair, double-tap = jump to latest
/// All times come from the backend as IST text - nothing is converted on the phone.
class IndiaChartScreen extends StatefulWidget {
  final IndiaApi api;
  final String underlying;

  /// Set to open the chart of ONE OPTION (key comes from the option chain) instead of the index.
  final String? optionKey;
  final String optionTitle;
  const IndiaChartScreen({super.key, required this.api, required this.underlying, this.optionKey, this.optionTitle = ''});

  @override
  State<IndiaChartScreen> createState() => _IndiaChartScreenState();
}

const _kPrefKey = 'india_chart_on';
const _kAllInd = ['sd', 'ema', 'sig', 'lv'];
const _kIndNames = {
  'sd': 'SD bands (±1 / 2 / 3)',
  'ema': 'EMA 30 / 50 + cloud',
  'sig': 'Buy / sell signals',
  'lv': 'Trade levels (entry, SL, TP)',
};

class _IndiaChartScreenState extends State<IndiaChartScreen> {
  late String _u = widget.underlying;
  Timer? _timer;
  bool _busy = false, _loaded = false, _live = false;
  String _error = '';
  List<_C> _c = [];
  _Ser _s = _Ser();
  List<Map<String, dynamic>> _levels = [];
  List<int> _tfChoices = const [1, 3, 5, 15];
  int _tf = 0; // chart timeframe (0 = not known yet -> backend default = bot timeframe)
  int _botTf = 5;
  Set<String> _on = {..._kAllInd};
  SmSettings _sm = SmSettings.defaults(); // your Special Master (TSI + Z-score) settings, same as the crypto chart
  SpecialMasterData? _smData;
  List<_C>? _smFor;
  String _smKey = '';
  String _source = '', _optErr = '', _feedMode = '', _note = '';
  double? _livePx; // last pushed price (about once a second) - the newest candle follows it between full reloads
  bool _pxUp = true;
  DateTime? _lastReload;
  bool _again = false; // a reload was asked while one was running (index / timeframe switched)
  bool get _isOpt => widget.optionKey != null;

  int _visible = 80; // candles on screen
  double _shift = 0; // candles scrolled back from the newest (negative = empty space on the right)
  double _startVisible = 80;
  int? _cross; // crosshair candle index (into _c)
  double? _crossY;
  double _yZoom = 1; // price scale: 1 = auto-fit, >1 = stretched (drag the right price axis up/down)
  double _yPan = 0; // price scroll (fraction of the visible range), drag up/down on the chart
  bool _axisDrag = false;
  Offset? _tapPos;
  DateTime? _updated; // last time the backend answered
  Timer? _clock;

  @override
  void initState() {
    super.initState();
    _loadPrefs();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _load());
    if (!_isOpt) {
      IndiaTicks.instance.start(widget.api);
      IndiaTicks.instance.data.addListener(_onTick);
    }
    _clock = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted && _live && !_isOpt) setState(() {}); // candle-close countdown + stale check
    });
  }

  @override
  void dispose() {
    if (!_isOpt) {
      IndiaTicks.instance.data.removeListener(_onTick);
      IndiaTicks.instance.stop();
    }
    _timer?.cancel();
    _clock?.cancel();
    super.dispose();
  }

  void _showSpeed() {
    final d = IndiaTicks.instance.data.value;
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('India data speed'),
        content: SingleChildScrollView(child: Text('${d['speed']}', style: const TextStyle(fontSize: 12))),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('OK'))],
      ),
    );
  }

  /// A fresh price arrived (about once a second): move the newest candle with it, like a broker app. When the price already belongs to
  /// the NEXT candle, ask the backend for a full reload (it builds the new candle and the indicators).
  void _onTick() {
    if (!mounted || _isOpt || !_live || _c.isEmpty || _tf <= 0) return;
    final sp = IndiaTicks.instance.data.value['spots'];
    if (sp is! Map) return;
    final s = sp[_u];
    if (s is! Map) return;
    final px = nd(s['lp']);
    final at = nd(s['at']).toInt();
    if (px <= 0) return;
    final last = _c.last;
    if (at >= last.ts + _tf * 60) {
      final now = DateTime.now();
      if (_lastReload == null || now.difference(_lastReload!).inMilliseconds > 2000) {
        _lastReload = now;
        _load();
      }
      return;
    }
    if (_livePx == px) return;
    setState(() {
      _pxUp = _livePx == null ? true : px >= _livePx!;
      _livePx = px;
      _updated = DateTime.now();
      _c[_c.length - 1] = _C(last.ts, last.lbl, last.day, last.date, last.o, math.max(last.h, px), math.min(last.l, px), px, last.x50);
    });
  }

  Future<void> _loadPrefs() async {
    try {
      final sp = await SharedPreferences.getInstance();
      final l = sp.getStringList(_kPrefKey);
      final sm = SmSettings.fromJson(sp.getString(SmSettings.prefsKey));
      if (mounted) {
        setState(() {
          if (l != null) _on = l.toSet().intersection(_kAllInd.toSet());
          _sm = sm;
        });
      }
    } catch (_) {}
  }

  Future<void> _savePrefs() async {
    try {
      final sp = await SharedPreferences.getInstance();
      await sp.setStringList(_kPrefKey, _on.toList());
      await sp.setString(SmSettings.prefsKey, _sm.toJson());
    } catch (_) {}
  }

  Future<void> _load() async {
    if (!mounted) return;
    if (_busy) {
      _again = true; // run once more right after this one (index / timeframe may have changed)
      return;
    }
    _busy = true;
    final reqU = _u, reqTf = _tf;
    try {
      final tfq = reqTf > 0 ? '&tf=$reqTf' : '';
      final q = _isOpt
          ? '/option_candles?key=${Uri.encodeQueryComponent(widget.optionKey!)}&limit=600$tfq'
          : '/candles?underlying=$reqU&limit=600$tfq';
      // the first load of an index downloads several days of history: allow more time than a normal refresh
      final d = Map<String, dynamic>.from(await widget.api.get(q, _loaded ? null : const Duration(seconds: 25)) as Map);
      if (!mounted) return;
      if (reqU != _u || (reqTf != _tf && reqTf != 0)) return; // the answer is for the index / timeframe you just left: drop it
      final cs = ((d['candles'] as List?) ?? []).map((e) => _C.from(Map<String, dynamic>.from(e as Map))).toList();
      final ser = _Ser.from(Map<String, dynamic>.from((d['indicators'] as Map?) ?? {}));
      if (!mounted) return;
      setState(() {
        final grew = cs.length - _c.length;
        if (_shift > 0.5 && grew > 0 && _c.isNotEmpty) _shift += grew; // keep the view still while you look back
        _c = cs;
        _s = ser;
        _levels = ((d['levels'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)).toList();
        _tf = nd(d['tf']).toInt();
        _botTf = nd(d['bot_tf']).toInt();
        final ch = ((d['tf_choices'] as List?) ?? []).map((e) => nd(e).toInt()).toList();
        if (ch.isNotEmpty) _tfChoices = ch;
        _live = d['live'] == true;
        _source = '${d['source'] ?? ''}';
        _optErr = '${d['error'] ?? ''}';
        _note = '${d['note'] ?? ''}';
        if (_c.isNotEmpty) _livePx = _c.last.c;
        _feedMode = '${d['feed_mode'] ?? ''}';
        _updated = DateTime.now();
        _error = '';
        _loaded = true;
      });
    } catch (e) {
      if (mounted) setState(() {
        _error = 'Could not load candles: ${friendlyError(e)} (showing last candles)';
        _loaded = true;
      });
    } finally {
      _busy = false;
      if (_again && mounted) {
        _again = false;
        _load();
      }
    }
  }

  void _pickIndex(String u) {
    setState(() {
      _u = u;
      _livePx = null;
      _c = [];
      _s = _Ser();
      _loaded = false;
      _shift = 0;
      _cross = null;
    });
    _load();
  }

  void _pickTf(int m) {
    setState(() {
      _tf = m;
      _livePx = null;
      _c = [];
      _s = _Ser();
      _loaded = false;
      _shift = 0;
      _cross = null;
    });
    _load();
  }

  Future<void> _pickBotTf() async {
    final m = await showModalBottomSheet<int>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Bot trades on', style: IT.h(ctx)),
            const SizedBox(height: 4),
            Text('Only the bot changes. The chart keeps the timeframe you are viewing.', style: IT.small(ctx)),
            const SizedBox(height: 12),
            Wrap(spacing: 8, children: [
              for (final m in _tfChoices) IChip('${m}m', selected: m == _botTf, onTap: () => Navigator.pop(ctx, m)),
            ]),
          ]),
        ),
      ),
    );
    if (m == null || m == _botTf) return;
    try {
      await widget.api.post('/settings', {'tf': m});
      if (mounted) setState(() => _botTf = m);
    } catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _indicators() async {
    await showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => SafeArea(
          child: ListView(shrinkWrap: true, padding: const EdgeInsets.all(16), children: [
            Text('Indicators', style: IT.h(ctx)),
            const SizedBox(height: 6),
            for (final k in _kAllInd)
              SwitchListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(_kIndNames[k]!, style: IT.body(ctx)),
                value: _on.contains(k),
                onChanged: (v) {
                  setState(() => v ? _on.add(k) : _on.remove(k));
                  setSheet(() {});
                  _savePrefs();
                },
              ),
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('TSI pane (Special Master)', style: IT.body(ctx)),
              value: _sm.tsiOn,
              onChanged: (v) {
                setState(() => _sm = _sm.set('tsiOn', v));
                setSheet(() {});
                _savePrefs();
              },
            ),
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text('Z-score pane (Special Master)', style: IT.body(ctx)),
              value: _sm.zOn,
              onChanged: (v) {
                setState(() => _sm = _sm.set('zOn', v));
                setSheet(() {});
                _savePrefs();
              },
            ),
          ]),
        ),
      ),
    );
  }

  Future<void> _smSettings() async {
    final res = await showSmSettingsSheet(context, _sm);
    if (res != null && mounted) {
      setState(() => _sm = res);
      _savePrefs();
    }
  }

  SpecialMasterData? _smCompute() {
    if (_c.length < 60 || (!_sm.tsiOn && !_sm.zOn)) return null;
    final key = _sm.computeKey;
    if (!identical(_smFor, _c) || _smKey != key || _smData == null) {
      _smData = SpecialMasterData.compute(_c.map((e) => e.c).toList(),
          st: _sm, o: _c.map((e) => e.o).toList(), h: _c.map((e) => e.h).toList(), l: _c.map((e) => e.l).toList());
      _smFor = _c;
      _smKey = key;
    }
    return _smData;
  }

  bool get _stale => _live && _updated != null && DateTime.now().difference(_updated!).inSeconds > 20;

  // ---------------------------------------------------------------- build ---
  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return MediaQuery(
      data: MediaQuery.of(context).copyWith(textScaler: const TextScaler.linear(0.9)),
      child: Scaffold(
        appBar: AppBar(
          titleSpacing: 0,
          title: Text('${_isOpt ? widget.optionTitle : _u}  ${_tf > 0 ? '${_tf}m' : ''}', style: IT.h(context).copyWith(fontSize: 16)),
          bottom: PreferredSize(
            preferredSize: const Size.fromHeight(18),
            child: Padding(
              padding: const EdgeInsets.only(left: 12, right: 12, bottom: 2),
              child: Align(alignment: Alignment.centerLeft, child: IndiaSpeedLine(onTap: _showSpeed)),
            ),
          ),
          actions: [
            if (!_isOpt && _live && _livePx != null)
              Center(
                child: Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Text(_livePx!.toStringAsFixed(2),
                      style: IT.h(context).copyWith(fontSize: 14, fontWeight: FontWeight.w800, color: _pxUp ? p.profit : p.loss)),
                ),
              ),
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Center(child: IPill(_isOpt && _source.isNotEmpty ? _source : (_live ? '${_stale ? 'STALE' : 'LIVE'}${_feedMode == 'WEBSOCKET' ? ' WS' : (_feedMode == 'REST' ? ' REST' : '')}' : 'DEMO'), _live && !_stale ? p.profit : p.warning)),
            ),
          ],
        ),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(10, 0, 10, 8),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (!_isOpt) ...[
                Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                  for (final u in kChartIndices) IChip(u, selected: u == _u, onTap: () => _pickIndex(u)),
                ]),
                const SizedBox(height: 6),
              ],
              Wrap(spacing: 6, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                for (final m in _tfChoices) IChip('${m}m', selected: m == _tf, onTap: () => _pickTf(m)),
                IChip('Indicators', selected: false, icon: Icons.tune, onTap: _indicators),
                if (_yZoom != 1 || _yPan != 0) IChip('Auto scale', selected: true, icon: Icons.height, onTap: () => setState(() {
                      _yZoom = 1;
                      _yPan = 0;
                    })),
                if (_shift != 0) IChip('Latest', selected: true, icon: Icons.last_page, onTap: () => setState(() {
                      _shift = 0;
                      _cross = null;
                    })),
                IChip('TSI / Z settings', selected: false, icon: Icons.settings_outlined, onTap: _smSettings),
                if (!_isOpt) IChip('Trade TF ${_botTf}m', selected: false, icon: Icons.smart_toy_outlined, onTap: _pickBotTf),
              ]),
              const SizedBox(height: 6),
              _readout(context),
              const SizedBox(height: 4),
              Expanded(child: _chart(context)),
              const SizedBox(height: 4),
              _legend(context),
              if (_isOpt && _source == 'MODEL')
                Padding(padding: const EdgeInsets.only(top: 4), child: Text('Premium is a model price here (broker has no option candles). Connect Fyers for real option candles.', style: IT.small(context))),
              if (_optErr.isNotEmpty)
                Padding(padding: const EdgeInsets.only(top: 4), child: Text(_optErr, style: IT.small(context).copyWith(color: p.warning))),
              if (_error.isNotEmpty)
                Padding(padding: const EdgeInsets.only(top: 4), child: SelectableText(_error, style: IT.small(context).copyWith(color: p.loss))),
              if (!_isOpt && _note.isNotEmpty)
                Padding(padding: const EdgeInsets.only(top: 4), child: Text(_note, style: IT.small(context))),
            ]),
          ),
        ),
      ),
    );
  }

  Widget _readout(BuildContext context) {
    final p = context.palette;
    if (_c.isEmpty) return const SizedBox(height: 32);
    final i = (_cross != null && _cross! >= 0 && _cross! < _c.length) ? _cross! : _c.length - 1;
    final k = _c[i];
    // change vs the previous trading day's close (TradingView style); falls back to the previous candle
    double? ref;
    for (var j = i - 1; j >= 0; j--) {
      if (_c[j].date != k.date) {
        ref = _c[j].c;
        break;
      }
    }
    ref ??= i > 0 ? _c[i - 1].c : null;
    final chg = (ref != null && ref != 0) ? (k.c - ref) / ref * 100 : null;
    final col = chg == null ? p.textPrimary : pnlColor(p, chg);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(num2(k.c), style: IT.big(context).copyWith(fontSize: 20)),
        const SizedBox(width: 8),
        if (chg != null) Text('${chg >= 0 ? '+' : ''}${chg.toStringAsFixed(2)}%', style: IT.body(context).copyWith(color: col, fontWeight: FontWeight.w700)),
        const Spacer(),
        Text('${k.day}  ${k.lbl}', style: IT.small(context)),
      ]),
      Text('O ${num2(k.o)}   H ${num2(k.h)}   L ${num2(k.l)}   C ${num2(k.c)}', style: IT.small(context)),
    ]);
  }

  Widget _legend(BuildContext context) {
    final p = context.palette;
    Widget item(Color c, String s) => Padding(
          padding: const EdgeInsets.only(right: 12),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Container(width: 10, height: 3, color: c),
            const SizedBox(width: 4),
            Text(s, style: IT.small(context).copyWith(fontSize: 10)),
          ]),
        );
    return Wrap(runSpacing: 2, children: [
      if (_on.contains('ema')) item(_Pt.emaFast, 'EMA${_s.fastLen}'),
      if (_on.contains('ema')) item(_Pt.emaSlow, 'EMA${_s.slowLen}'),
      if (_on.contains('sd')) item(_Pt.mean, 'SD mean'),
      Padding(
        padding: const EdgeInsets.only(right: 12),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 10, height: 10, decoration: BoxDecoration(color: Colors.black, border: Border.all(color: _Pt.up, width: 1.6))),
          const SizedBox(width: 4),
          Text('Crossed EMA50 (black body)', style: IT.small(context).copyWith(fontSize: 10)),
        ]),
      ),
      if (_on.contains('sig')) item(_Pt.up, 'Buy'),
      if (_on.contains('sig')) item(_Pt.down, 'Sell'),
      if (_on.contains('lv')) item(p.warning, 'SL / TP'),
    ]);
  }

  Widget _chart(BuildContext context) {
    final t = context.type;
    if (!_loaded) {
      return Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const CircularProgressIndicator(),
          const SizedBox(height: 12),
          Text('Loading ${_isOpt ? 'option' : _u} candles... the first open of an index can take a few seconds.',
              textAlign: TextAlign.center, style: IT.small(context)),
        ]),
      );
    }
    if (_c.length < 2) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.l),
          child: Text(
            _live
                ? 'No candles yet. With a live broker, candles are built from prices received after Connect - keep the backend running during market hours.'
                : 'No candles yet. Press Start on the Dashboard.',
            textAlign: TextAlign.center,
            style: t.secondary,
          ),
        ),
      );
    }
    final sm = _smCompute();
    return Container(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE1E4EA)),
      ),
      clipBehavior: Clip.antiAlias,
      child: LayoutBuilder(builder: (ctx, box) {
        final plotW = box.maxWidth - _Pt.rightPad;
        final cw = plotW / _visible;
        int? mark;
        if (_cross != null) mark = _cross!.clamp(0, _c.length - 1).toInt();
        return GestureDetector(
          behavior: HitTestBehavior.opaque,
          onDoubleTapDown: (d) => _tapPos = d.localPosition,
          onDoubleTap: () => setState(() {
            final onAxis = (_tapPos?.dx ?? 0) > plotW; // double-tap on the price axis = auto scale only
            _yZoom = 1;
            _yPan = 0;
            if (!onAxis) {
              _shift = 0;
              _cross = null;
            }
          }),
          onScaleStart: (d) {
            _startVisible = _visible.toDouble();
            final topH = sm == null ? box.maxHeight : box.maxHeight * 3 / 5;
            // one finger on the right price axis = TradingView-style price scaling
            _axisDrag = d.pointerCount == 1 && d.localFocalPoint.dx > plotW && d.localFocalPoint.dy < topH - _Pt.axisH;
          },
          onScaleUpdate: (d) => setState(() {
            final topH = sm == null ? box.maxHeight : box.maxHeight * 3 / 5;
            final priceH = math.max(40.0, topH - _Pt.axisH);
            final dx = d.focalPointDelta.dx, dy = d.focalPointDelta.dy;
            if (_axisDrag) {
              _yZoom = (_yZoom * math.exp(-dy * 0.006)).clamp(0.2, 12.0).toDouble(); // drag up = taller candles
              return;
            }
            if (d.pointerCount > 1) {
              _visible = (_startVisible / d.scale).round().clamp(15, math.min(250, math.max(15, _c.length)));
            }
            final vertical = dy.abs() > dx.abs() * 1.2 && d.pointerCount == 1;
            if (vertical) {
              _yPan = (_yPan + dy / priceH).clamp(-3.0, 3.0).toDouble(); // scroll the price up / down
            } else {
              _shift += dx / cw; // drag right = older candles
              _shift = _shift.clamp(-_visible * 0.5, math.max(0, _c.length - 10).toDouble());
            }
          }),
          onScaleEnd: (_) => _axisDrag = false,
          onLongPressStart: (d) => setState(() => _setCross(d.localPosition, box.maxWidth)),
          onLongPressMoveUpdate: (d) => setState(() => _setCross(d.localPosition, box.maxWidth)),
          onLongPressEnd: (_) => setState(() {
            _cross = null;
            _crossY = null;
          }),
          child: Column(children: [
            Expanded(
              flex: sm == null ? 1 : 3,
              child: CustomPaint(
                size: Size.infinite,
                painter: _ChartPainter(
                  cs: _c,
                  s: _s,
                  levels: _levels,
                  on: _on,
                  visible: _visible,
                  shift: _shift,
                  cross: _cross,
                  crossY: _crossY,
                  yZoom: _yZoom,
                  yPan: _yPan,
                  live: _live && !_isOpt,
                  tf: _tf > 0 ? _tf : _botTf,
                  nowSec: DateTime.now().millisecondsSinceEpoch ~/ 1000,
                ),
              ),
            ),
            if (sm != null) ...[
              const Divider(height: 1, thickness: 1, color: Color(0xFFD1D5DB)),
              Expanded(
                flex: 2,
                child: ClipRect(
                  child: CustomPaint(
                    size: Size.infinite,
                    painter: SpecialMasterPainter(
                      sm,
                      st: _sm,
                      slot: cw,
                      rightBlank: -_shift.roundToDouble(), // same x-position as the candles above
                      plotW: plotW,
                      light: true,
                      markIdx: mark,
                    ),
                  ),
                ),
              ),
            ],
          ]),
        );
      }),
    );
  }

  void _setCross(Offset pos, double width) {
    final cw = (width - _Pt.rightPad) / _visible;
    final end = _c.length - _shift.round();
    final start = end - _visible;
    final idx = start + (pos.dx / cw).floor();
    _cross = (idx >= 0 && idx < _c.length) ? idx : null;
    _crossY = pos.dy;
  }
}

const kChartIndices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];

// ------------------------------------------------------------------ data ---
class _C {
  final int ts;
  final String lbl, day, date;
  final double o, h, l, c;
  final bool x50; // candle crossed EMA50 -> painted black
  _C(this.ts, this.lbl, this.day, this.date, this.o, this.h, this.l, this.c, this.x50);
  factory _C.from(Map<String, dynamic> m) => _C(nd(m['ts']).toInt(), '${m['lbl']}', '${m['day']}', '${m['date']}', nd(m['o']),
      nd(m['h']), nd(m['l']), nd(m['c']), nd(m['x50']) > 0);
}

List<double?> _arr(dynamic v) => ((v as List?) ?? []).map<double?>((e) => e == null ? null : nd(e)).toList();

class _Mk {
  final int i;
  final bool buy;
  _Mk(this.i, this.buy);
}

class _Ser {
  List<double?> mean = [], p1 = [], p2 = [], p3 = [], m1 = [], m2 = [], m3 = [];
  List<double?> fast = [], slow = [], tsi = [], tsiSig = [], z = [], zSma = [];
  List<_Mk> marks = [];
  int fastLen = 30, slowLen = 50;
  _Ser();
  factory _Ser.from(Map<String, dynamic> d) {
    final s = _Ser();
    final sd = Map<String, dynamic>.from((d['sd'] as Map?) ?? {});
    s.mean = _arr(sd['mean']);
    s.p1 = _arr(sd['p1']);
    s.p2 = _arr(sd['p2']);
    s.p3 = _arr(sd['p3']);
    s.m1 = _arr(sd['m1']);
    s.m2 = _arr(sd['m2']);
    s.m3 = _arr(sd['m3']);
    final e = Map<String, dynamic>.from((d['ema'] as Map?) ?? {});
    s.fast = _arr(e['fast']);
    s.slow = _arr(e['slow']);
    s.fastLen = e['fast_len'] == null ? 30 : nd(e['fast_len']).toInt();
    s.slowLen = e['slow_len'] == null ? 50 : nd(e['slow_len']).toInt();
    final t = Map<String, dynamic>.from((d['tsi'] as Map?) ?? {});
    s.tsi = _arr(t['tsi']);
    s.tsiSig = _arr(t['signal']);
    final z = Map<String, dynamic>.from((d['z'] as Map?) ?? {});
    s.z = _arr(z['z']);
    s.zSma = _arr(z['sma']);
    s.marks = ((d['markers'] as List?) ?? [])
        .map((e) => _Mk(nd((e as Map)['i']).toInt(), '${e['side']}' == 'BUY'))
        .toList();
    return s;
  }
}

// -------------------------------------------------------------- painting ---
class _Pt {
  static const rightPad = 54.0;
  static const axisH = 18.0;
  static const up = Color(0xFF26A69A);
  static const down = Color(0xFFEF5350);
  static const grid = Color(0xFFEDEFF3);
  static const text = Color(0xFF5B6472);
  static const mean = Color(0xFF6B7280);
  static const band = Color(0xFFB8BCA9);
  static const zoneOuter = Color(0x66FFF1A8);
  static const zoneInner = Color(0x59A5D6A7);
  static const emaFast = Color(0xFF2E7D32);
  static const emaSlow = Color(0xFFC62828);
  static const cloudUp = Color(0x4D66BB6A);
  static const cloudDn = Color(0x4DF48FB1);
}

class _ChartPainter extends CustomPainter {
  final List<_C> cs;
  final _Ser s;
  final List<Map<String, dynamic>> levels;
  final Set<String> on;
  final int visible;
  final double shift;
  final int? cross;
  final double? crossY;
  final double yZoom, yPan;
  final bool live;
  final int tf, nowSec;
  _ChartPainter({
    required this.cs,
    required this.s,
    required this.levels,
    required this.on,
    required this.visible,
    required this.shift,
    required this.cross,
    required this.crossY,
    this.yZoom = 1,
    this.yPan = 0,
    this.live = false,
    this.tf = 5,
    this.nowSec = 0,
  });

  void _text(Canvas c, String t, Offset o,
      {Color color = _Pt.text, double size = 10, bool right = false, bool bold = false, bool center = false}) {
    final tp = TextPainter(
      text: TextSpan(text: t, style: TextStyle(color: color, fontSize: size, fontWeight: bold ? FontWeight.w700 : FontWeight.w500)),
      textDirection: TextDirection.ltr,
    )..layout();
    final dx = right ? o.dx - tp.width : (center ? o.dx - tp.width / 2 : o.dx);
    tp.paint(c, Offset(dx, o.dy - tp.height / 2));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final plotW = size.width - _Pt.rightPad;
    final bodyH = size.height - _Pt.axisH;
    final priceH = bodyH; // TSI / Z-score are drawn by SpecialMasterPainter in their own panes below
    final end = cs.length - shift.round();
    final start = end - visible;
    final cw = plotW / visible;
    double x(int i) => (i + 0.5) * cw;
    bool ok(int i) => start + i >= 0 && start + i < cs.length;
    int idx(int i) => start + i;

    // ---------- price range (candles in view + nearby trade levels) ----------
    double hi = -1e18, lo = 1e18;
    for (var i = 0; i < visible; i++) {
      if (!ok(i)) continue;
      hi = math.max(hi, cs[idx(i)].h);
      lo = math.min(lo, cs[idx(i)].l);
    }
    if (hi < lo) return;
    final span0 = math.max(hi - lo, 0.01);
    if (on.contains('lv')) {
      for (final lv in levels) {
        final all = <double>[nd(lv['entry']), nd(lv['sl']), ...((lv['tps'] as List?) ?? []).map((e) => nd(e))];
        for (final v in all) {
          if (v > 0 && v < hi + span0 * 0.6 && v > lo - span0 * 0.6) {
            hi = math.max(hi, v);
            lo = math.min(lo, v);
          }
        }
      }
    }
    final pad = (hi - lo) * 0.07 + 0.01;
    hi += pad;
    lo -= pad;
    if (yZoom != 1 || yPan != 0) { // manual scale: zoom around the middle, pan by a fraction of the range
      final base = hi - lo;
      final mid = (hi + lo) / 2 + yPan * base;
      final half = base / 2 / yZoom;
      hi = mid + half;
      lo = mid - half;
    }
    double py(double v) => (hi - v) / (hi - lo) * priceH;

    final grid = Paint()..color = _Pt.grid..strokeWidth = 1;

    // ---------- price panel ----------
    canvas.save();
    canvas.clipRect(Rect.fromLTWH(0, 0, plotW, priceH));
    for (var i = 0; i <= 4; i++) {
      final v = lo + (hi - lo) * i / 4;
      canvas.drawLine(Offset(0, py(v)), Offset(plotW, py(v)), grid);
    }
    _dayLines(canvas, start, visible, cw, priceH, grid);

    if (on.contains('sd')) {
      _band(canvas, s.p3, s.p2, start, visible, x, py, Paint()..color = _Pt.zoneOuter);
      _band(canvas, s.m2, s.m3, start, visible, x, py, Paint()..color = _Pt.zoneOuter);
      _band(canvas, s.p2, s.p1, start, visible, x, py, Paint()..color = _Pt.zoneInner);
      _band(canvas, s.m1, s.m2, start, visible, x, py, Paint()..color = _Pt.zoneInner);
      final lp = Paint()..color = _Pt.band..style = PaintingStyle.stroke..strokeWidth = 1;
      for (final l in [s.p3, s.p2, s.p1, s.m1, s.m2, s.m3]) {
        _line(canvas, l, start, visible, x, py, lp);
      }
      _line(canvas, s.mean, start, visible, x, py, Paint()..color = _Pt.mean..style = PaintingStyle.stroke..strokeWidth = 1.4);
    }
    if (on.contains('ema')) {
      for (var i = 1; i < visible; i++) {
        final a = start + i - 1, b = start + i;
        if (a < 0 || b >= cs.length || b >= s.fast.length || b >= s.slow.length) continue;
        final f0 = s.fast[a], f1 = s.fast[b], s0 = s.slow[a], s1 = s.slow[b];
        if (f0 == null || f1 == null || s0 == null || s1 == null) continue;
        final path = Path()
          ..moveTo(x(i - 1), py(f0))
          ..lineTo(x(i), py(f1))
          ..lineTo(x(i), py(s1))
          ..lineTo(x(i - 1), py(s0))
          ..close();
        canvas.drawPath(path, Paint()..color = f1 >= s1 ? _Pt.cloudUp : _Pt.cloudDn);
      }
      _line(canvas, s.fast, start, visible, x, py, Paint()..color = _Pt.emaFast..style = PaintingStyle.stroke..strokeWidth = 1.2);
      _line(canvas, s.slow, start, visible, x, py, Paint()..color = _Pt.emaSlow..style = PaintingStyle.stroke..strokeWidth = 1.2);
    }

    // candles
    for (var i = 0; i < visible; i++) {
      if (!ok(i)) continue;
      final k = cs[idx(i)];
      final dir = k.c >= k.o ? _Pt.up : _Pt.down;
      canvas.drawLine(Offset(x(i), py(k.h)), Offset(x(i), py(k.l)), Paint()..color = dir..strokeWidth = 1);
      final top = py(math.max(k.o, k.c)), bot = py(math.min(k.o, k.c));
      final body = Rect.fromLTRB(x(i) - cw * 0.36, top, x(i) + cw * 0.36, math.max(bot, top + 1));
      if (k.x50) {
        // crossed EMA50: coloured border (green up / red down) with a BLACK body inside
        canvas.drawRect(body, Paint()..color = Colors.black);
        if (body.width > 3) {
          canvas.drawRect(body.deflate(0.6), Paint()..color = dir..style = PaintingStyle.stroke..strokeWidth = math.min(1.8, math.max(1.0, body.width / 5)));
        }
      } else {
        canvas.drawRect(body, Paint()..color = dir);
      }
    }

    // buy / sell markers
    if (on.contains('sig') && cw > 2.5) {
      for (final m in s.marks) {
        final i = m.i - start;
        if (i < 0 || i >= visible || !ok(i)) continue;
        final k = cs[m.i];
        final col = m.buy ? _Pt.up : _Pt.down;
        final y0 = m.buy ? py(k.l) + 4 : py(k.h) - 4;
        final dir = m.buy ? 1.0 : -1.0; // below the candle for buy, above for sell
        final tri = Path()
          ..moveTo(x(i), y0)
          ..lineTo(x(i) - 4, y0 + 5 * dir)
          ..lineTo(x(i) + 4, y0 + 5 * dir)
          ..close();
        canvas.drawPath(tri, Paint()..color = col);
        final r = Rect.fromCenter(center: Offset(x(i), y0 + 12 * dir), width: 26, height: 14);
        canvas.drawRRect(RRect.fromRectAndRadius(r, const Radius.circular(3)), Paint()..color = col);
        _text(canvas, m.buy ? 'BUY' : 'SELL', r.center, color: Colors.white, size: 8, bold: true, center: true);
      }
    }

    // open-trade levels
    if (on.contains('lv')) {
      for (final lv in levels) {
        void lvl(double v, Color col, String label) {
          if (v <= lo || v >= hi) return;
          for (var xx = 0.0; xx < plotW; xx += 8) {
            canvas.drawLine(Offset(xx, py(v)), Offset(math.min(xx + 4, plotW), py(v)), Paint()..color = col..strokeWidth = 1);
          }
          _text(canvas, '$label ${v.toStringAsFixed(1)}', Offset(4, py(v) - 6), color: col, size: 9, bold: true);
        }
        lvl(nd(lv['entry']), const Color(0xFF374151), '${lv['action'] == 'LONG' ? 'BUY' : 'SELL'} entry');
        lvl(nd(lv['sl']), _Pt.down, 'SL');
        final tps = (lv['tps'] as List?) ?? [];
        for (var i = 0; i < tps.length; i++) {
          lvl(nd(tps[i]), const Color(0xFFF59E0B), 'TP${i + 1}');
        }
      }
    }
    canvas.restore();

    // right scale + last price tag
    for (var i = 0; i <= 4; i++) {
      final v = lo + (hi - lo) * i / 4;
      _text(canvas, v.toStringAsFixed(1), Offset(size.width - 4, py(v)), right: true);
    }
    final last = cs.last;
    if (last.c > lo && last.c < hi) {
      final yy = py(last.c);
      final lc = last.c >= last.o ? _Pt.up : _Pt.down;
      if (live) { // live price line across the chart
        for (var xx = 0.0; xx < plotW; xx += 6) {
          canvas.drawLine(Offset(xx, yy), Offset(math.min(xx + 3, plotW), yy), Paint()..color = lc..strokeWidth = 1);
        }
      }
      canvas.drawRect(Rect.fromLTWH(plotW, yy - 8, _Pt.rightPad, 16), Paint()..color = lc);
      _text(canvas, last.c.toStringAsFixed(1), Offset(size.width - 4, yy), color: Colors.white, size: 10, right: true, bold: true);
      final left = last.ts + tf * 60 - nowSec; // seconds until this candle closes
      if (live && left > 0 && left <= tf * 60) {
        final mm = (left ~/ 60).toString().padLeft(2, '0'), ss = (left % 60).toString().padLeft(2, '0');
        canvas.drawRect(Rect.fromLTWH(plotW, yy + 8, _Pt.rightPad, 14), Paint()..color = const Color(0xFF374151));
        _text(canvas, '$mm:$ss', Offset(size.width - 4, yy + 15), color: Colors.white, size: 9, right: true, bold: true);
      }
    }

    // ---------- time axis (IST text from the backend) ----------
    var lastDate = '';
    for (var i = 0; i < visible; i++) {
      if (!ok(i)) continue;
      final k = cs[idx(i)];
      final newDay = lastDate.isNotEmpty && k.date != lastDate;
      lastDate = k.date;
      final every = math.max(1, (visible / 5).round());
      if (newDay) {
        _text(canvas, k.day, Offset(x(i), size.height - 9), color: const Color(0xFF111827), size: 10, bold: true, center: true);
      } else if (idx(i) % every == 0) {
        final near = i > 0 && ok(i - 1) && cs[idx(i - 1)].date != k.date;
        if (!near) _text(canvas, k.lbl, Offset(x(i), size.height - 9), size: 9, center: true);
      }
    }

    // ---------- crosshair ----------
    if (cross != null) {
      final i = cross! - start;
      if (i >= 0 && i < visible) {
        final cp = Paint()..color = const Color(0xFF9CA3AF)..strokeWidth = 1;
        canvas.drawLine(Offset(x(i), 0), Offset(x(i), bodyH), cp);
        if (crossY != null && crossY! >= 0 && crossY! <= priceH) {
          canvas.drawLine(Offset(0, crossY!), Offset(plotW, crossY!), cp);
          final v = hi - crossY! / priceH * (hi - lo);
          canvas.drawRect(Rect.fromLTWH(plotW, crossY! - 8, _Pt.rightPad, 16), Paint()..color = const Color(0xFF374151));
          _text(canvas, v.toStringAsFixed(1), Offset(size.width - 4, crossY!), color: Colors.white, size: 10, right: true, bold: true);
        }
      }
    }
  }

  // contiguous runs where a value exists -> polyline
  void _line(Canvas c, List<double?> v, int start, int visible, double Function(int) x, double Function(double) y, Paint paint) {
    Path? path;
    for (var i = 0; i < visible; i++) {
      final k = start + i;
      final val = (k >= 0 && k < v.length && k < cs.length) ? v[k] : null;
      if (val == null) {
        if (path != null) c.drawPath(path, paint);
        path = null;
        continue;
      }
      if (path == null) {
        path = Path()..moveTo(x(i), y(val));
      } else {
        path.lineTo(x(i), y(val));
      }
    }
    if (path != null) c.drawPath(path, paint);
  }

  // fill between two series
  void _band(Canvas c, List<double?> a, List<double?> b, int start, int visible, double Function(int) x, double Function(double) y, Paint paint) {
    final run = <int>[];
    void flush() {
      if (run.length >= 2) {
        final path = Path()..moveTo(x(run.first), y(a[start + run.first]!));
        for (final i in run.skip(1)) {
          path.lineTo(x(i), y(a[start + i]!));
        }
        for (final i in run.reversed) {
          path.lineTo(x(i), y(b[start + i]!));
        }
        path.close();
        c.drawPath(path, paint);
      }
      run.clear();
    }

    for (var i = 0; i < visible; i++) {
      final k = start + i;
      final good = k >= 0 && k < cs.length && k < a.length && k < b.length && a[k] != null && b[k] != null;
      good ? run.add(i) : flush();
    }
    flush();
  }

  void _dayLines(Canvas c, int start, int visible, double cw, double h, Paint grid) {
    for (var i = 1; i < visible; i++) {
      final k = start + i;
      if (k <= 0 || k >= cs.length) continue;
      if (cs[k].date != cs[k - 1].date) {
        final xx = i * cw;
        c.drawLine(Offset(xx, 0), Offset(xx, h), grid);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _ChartPainter o) => true;
}
