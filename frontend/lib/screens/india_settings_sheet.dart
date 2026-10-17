import 'package:flutter/material.dart';

import '../services/india_api.dart';
import '../theme/app_theme.dart';
import '../widgets/india_ui.dart';
import 'india_broker_card.dart';
import 'india_telegram_card.dart';

const kIndiaIndices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'];
const kIndiaTfs = [1, 3, 5, 15];

/// Which indices the bot trades + which timeframe it trades on.
/// Used on the Dashboard (quick change) and in Settings. Changes apply at once.
class IndiaBotSetup extends StatelessWidget {
  final IndiaApi api;
  final Map<String, dynamic> settings;
  final VoidCallback onChanged;
  const IndiaBotSetup({super.key, required this.api, required this.settings, required this.onChanged});

  Future<void> _set(BuildContext context, Map<String, dynamic> patch) async {
    AppHaptics.light();
    try {
      await api.post('/settings', patch);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
    onChanged();
  }

  @override
  Widget build(BuildContext context) {
    final unders = ((settings['underlyings'] as List?) ?? []).map((e) => '$e').toList();
    final tf = nd(settings['tf']).toInt();
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('Trade these indices', style: IT.small(context)),
      const SizedBox(height: 6),
      Wrap(spacing: 6, runSpacing: 6, children: [
        for (final u in kIndiaIndices)
          IChip(u, selected: unders.contains(u), onTap: () {
            final cur = List<String>.from(unders);
            cur.contains(u) ? cur.remove(u) : cur.add(u);
            if (cur.isEmpty) return; // keep at least one
            _set(context, {'underlyings': cur});
          }),
      ]),
      const SizedBox(height: 12),
      Text('Trade on timeframe', style: IT.small(context)),
      const SizedBox(height: 6),
      Wrap(spacing: 6, runSpacing: 6, children: [
        for (final m in kIndiaTfs) IChip('${m}m', selected: tf == m, onTap: () => _set(context, {'tf': m})),
      ]),
    ]);
  }
}

/// India paper settings, grouped like the crypto settings (tap a title to open / close).
/// Every change is sent to the backend immediately and applies to the NEXT trade.
class IndiaSettingsTab extends StatelessWidget {
  final IndiaApi api;
  final Map<String, dynamic> settings;
  final VoidCallback onChanged;
  const IndiaSettingsTab({super.key, required this.api, required this.settings, required this.onChanged});

  Future<void> _set(BuildContext context, Map<String, dynamic> patch) async {
    AppHaptics.light();
    try {
      await api.post('/settings', patch);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
      }
    }
    onChanged();
  }

  Widget _label(BuildContext context, String s) =>
      Padding(padding: const EdgeInsets.only(top: 12, bottom: 6), child: Text(s, style: IT.small(context)));

  Widget _hint(BuildContext context, String s) =>
      Padding(padding: const EdgeInsets.only(top: 6), child: Text(s, style: IT.small(context)));

  Widget _switch(BuildContext context, String title, String key, String sub) {
    return SwitchListTile(
      contentPadding: EdgeInsets.zero,
      dense: true,
      title: Text(title, style: IT.body(context)),
      subtitle: Text(sub, style: IT.small(context)),
      value: settings[key] == true,
      onChanged: (v) => _set(context, {key: v}),
    );
  }

  double _n(String k) => nd(settings[k]);

  @override
  Widget build(BuildContext context) {
    final unders = ((settings['underlyings'] as List?) ?? []).map((e) => '$e').toList();
    final tf = _n('tf').toInt();
    return ListView(
      padding: const EdgeInsets.all(AppSpacing.l),
      children: [
        IndiaBrokerCard(api: api, onChanged: onChanged),
        IndiaTelegramCard(api: api, onChanged: onChanged),
        ISection(
          title: 'Market & timeframe',
          summary: '${unders.join(' + ')} · ${tf}m',
          initiallyOpen: true,
          children: [
            IndiaBotSetup(api: api, settings: settings, onChanged: onChanged),
            _hint(context, 'The bot only trades the indices you tick, on the timeframe you pick. The chart has its own timeframe buttons, so you can look at 1m while the bot trades on 5m.'),
            _label(context, 'Product for new trades'),
            IChoice<String>(
              values: const ['INTRADAY', 'CARRY'],
              current: '${settings['product']}',
              label: (v) => v == 'INTRADAY' ? 'Intraday (3:15 square-off)' : 'Carry forward',
              onPick: (v) => _set(context, {'product': v}),
            ),
            _hint(context, 'Carry keeps the position overnight (needs 2+ days to expiry) and is always closed on expiry day. Overnight gap and theta risk apply.'),
          ],
        ),
        ISection(
          title: 'Position size',
          summary: '${_n('lots').toInt()} lot · ${inr(_n('capital'), dp: 0)}',
          children: [
            _label(context, 'Lots per trade'),
            IChoice<int>(values: const [1, 2, 3, 5], current: _n('lots').toInt(), label: (v) => '$v', onPick: (v) => _set(context, {'lots': v})),
            _label(context, 'Paper capital (applies after Reset)'),
            IChoice<int>(
              values: const [10000, 25000, 50000, 200000],
              current: _n('capital').toInt(),
              label: (v) => inr(v, dp: 0),
              onPick: (v) => _set(context, {'capital': v.toDouble()}),
            ),
          ],
        ),
        ISection(
          title: 'Strike selection',
          summary: 'ITM ${_n('itm_depth').toInt()}',
          children: [
            _label(context, 'Default ITM depth'),
            IChoice<int>(values: const [1, 2, 3], current: _n('itm_depth').toInt(), label: (v) => 'ITM $v', onPick: (v) => _set(context, {'itm_depth': v})),
            _hint(context, 'A strike you tick, or the ITM/ATM/OTM chip in Chain, overrides this for the day.'),
            _switch(context, 'Fit my balance', 'fit_balance', 'If the strike costs more than your budget, step to a cheaper one.'),
            _label(context, 'Budget per trade (share of cash)'),
            IChoice<double>(
              values: const [0.5, 0.75, 0.95],
              current: _n('budget_pct'),
              label: (v) => '${(v * 100).round()}%',
              onPick: (v) => _set(context, {'budget_pct': v}),
            ),
            _label(context, 'Minimum premium (never buy cheaper)'),
            IChoice<double>(
              values: const [0, 10, 20, 30, 50],
              current: _n('min_premium'),
              label: (v) => v == 0 ? 'Off' : '₹${v.toStringAsFixed(0)}',
              onPick: (v) => _set(context, {'min_premium': v}),
            ),
            _switch(context, 'Fallback if ticked strike is too costly', 'pin_fallback', 'Off = skip the trade instead of buying a different strike.'),
          ],
        ),
        ISection(
          title: 'Exits',
          summary: 'TP${_n('target_level').toInt()} · trail ${settings['trail_mode']} · SL ${settings['sl_type'] ?? 'index'}',
          children: [
            _label(context, 'Stop-loss type'),
            IChoice<String>(
              values: const ['index', 'premium', 'both'],
              current: '${settings['sl_type'] ?? 'index'}',
              label: (v) => v == 'index' ? 'Index (current)' : (v == 'premium' ? 'Premium %' : 'Both'),
              onPick: (v) => _set(context, {'sl_type': v}),
            ),
            if ('${settings['sl_type'] ?? 'index'}' != 'index') ...[
              _label(context, 'Premium stop: exit when premium falls by'),
              IChoice<double>(
                values: const [15, 20, 30, 40],
                current: _n('premium_sl_pct') == 0 ? 30 : _n('premium_sl_pct'),
                label: (v) => '${v.toStringAsFixed(0)}%',
                onPick: (v) => _set(context, {'premium_sl_pct': v}),
              ),
            ],
            _hint(context, 'Index = the strategy\'s own SL on the index (what the bot used so far). Premium % = exit when the option itself loses that much, whatever the index does. Both = whichever comes first. Default stays Index.'),
            _label(context, 'Final target'),
            IChoice<int>(values: const [1, 2, 3, 4], current: _n('target_level').toInt(), label: (v) => 'TP$v', onPick: (v) => _set(context, {'target_level': v})),
            _switch(context, 'TP1 hit -> SL to entry', 'breakeven', 'Applies from the next candle.'),
            _label(context, 'Trail mode'),
            IChoice<String>(
              values: const ['off', 'step1', 'step2'],
              current: '${settings['trail_mode']}',
              label: (v) => v,
              onPick: (v) => _set(context, {'trail_mode': v}),
            ),
            _hint(context, 'step1: SL follows one TP behind (TP1 -> entry, TP2 -> TP1...). step2: slower (TP2 -> entry, TP3 -> TP1).'),
            _hint(context, 'Stop-loss triggers only when a candle CLOSES beyond it, not on a wick. A gap-open beyond SL exits at the open.'),
            _label(context, 'Emergency stop (premium falls by)'),
            IChoice<double>(
              values: const [0, 0.1, 0.2, 0.3],
              current: _n('emergency_pct'),
              label: (v) => v == 0 ? 'Off' : '${(v * 100).round()}%',
              onPick: (v) => _set(context, {'emergency_pct': v}),
            ),
            _hint(context, 'Safety net for close-based SL: exits at once if the option premium drops this much below entry.'),
            _label(context, 'Skip trade if est. loss at SL is above'),
            IChoice<double>(
              values: const [0, 2, 5, 10],
              current: _n('max_loss_pct'),
              label: (v) => v == 0 ? 'Off' : '${v.toStringAsFixed(0)}% of cash',
              onPick: (v) => _set(context, {'max_loss_pct': v}),
            ),
          ],
        ),
        ISection(
          title: 'Demo',
          summary: '${_n('speed_sec')}s per candle',
          children: [
            _label(context, 'Speed (seconds per candle)'),
            IChoice<double>(values: const [0.3, 1.0, 3.0], current: _n('speed_sec'), label: (v) => '${v}s', onPick: (v) => _set(context, {'speed_sec': v})),
            _hint(context, 'Demo replays synthetic candles from the last 30 trading days. Premiums come from a pricing model until a broker feed is connected.'),
          ],
        ),
        const SizedBox(height: AppSpacing.huge),
      ],
    );
  }
}
