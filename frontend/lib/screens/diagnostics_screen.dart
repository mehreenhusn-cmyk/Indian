import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../models/diag_history.dart';
import '../models/diag_status.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/diagnostics_card.dart' show buildDiagStatus;

/// Part 25 (Diagnostics 3 of 4): detail page of the 6 health checks + history of their changes.
/// Opened by tapping the health strip on the Dashboard Diagnostics card.
/// Layout rule (README4 9.1): the 6 checks stay PINNED at the top, only the history below scrolls.
/// It reads the same buildDiagStatus() as the strip, so the two can never disagree.
/// Read-only: no trading call, no setting is changed here.
class DiagnosticsScreen extends StatefulWidget {
  const DiagnosticsScreen({super.key});

  @override
  State<DiagnosticsScreen> createState() => _DiagnosticsScreenState();
}

class _DiagnosticsScreenState extends State<DiagnosticsScreen> {
  final ScrollController _scroll = ScrollController();
  Timer? _tick;
  String? _filter; // null = all, 'errors' = exchange errors, else a check key
  List<DiagEvent> _frozen = const [];
  int _frozenTotal = 0;
  bool _reading = false; // true while the user is scrolled away from the top

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    // "5 min ago" labels move on by themselves, no provider needed.
    _tick = Timer.periodic(const Duration(seconds: 5), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    final away = _scroll.hasClients && _scroll.offset > 40;
    if (away == _reading) return;
    if (away) {
      // Freeze the list so it does not jump under his finger while he reads old events.
      _frozen = DiagHistory.instance.events;
      _frozenTotal = DiagHistory.instance.total;
    }
    setState(() => _reading = away);
  }

  void _jumpToLatest() {
    if (_scroll.hasClients) {
      _scroll.animateTo(0, duration: AppMotion.base, curve: AppMotion.standard);
    }
  }

  static String _ago(DateTime? t) {
    if (t == null) return '--';
    final s = DateTime.now().difference(t).inSeconds;
    if (s < 5) return 'just now';
    if (s < 60) return '$s s';
    if (s < 3600) return '${s ~/ 60} min';
    if (s < 86400) return '${s ~/ 3600} h ${(s % 3600) ~/ 60} min';
    return '${s ~/ 86400} d';
  }

  Color _color(BuildContext context, DiagLevel? l) {
    switch (l) {
      case DiagLevel.ok:
        return context.palette.profit;
      case DiagLevel.warn:
        return context.palette.warning;
      case DiagLevel.bad:
        return context.palette.loss;
      default:
        return context.palette.textMuted;
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Consumer<AppProvider>(
      builder: (context, provider, child) {
        final diag = buildDiagStatus(provider);
        final hist = DiagHistory.instance;
        hist.record(diag); // adds only when a level changed
        final live = _filter == 'errors' ? const <DiagEvent>[] : hist.forKey(_filter);
        final shown = _reading
            ? (_filter == null || _filter == 'errors' ? _frozen : _frozen.where((e) => e.key == _filter).toList())
            : live;
        final pending = _reading ? hist.total - _frozenTotal : 0;
        final errors = provider.recentApiErrors;

        return Scaffold(
          backgroundColor: p.bg,
          appBar: AppBar(
            backgroundColor: p.bg,
            elevation: 0,
            title: Text('Diagnostics', style: AppTypography.sectionHeading.copyWith(color: p.textPrimary)),
            actions: [
              IconButton(
                tooltip: 'Copy history',
                icon: const Icon(Icons.copy_all_outlined),
                onPressed: () {
                  AppHaptics.light();
                  Clipboard.setData(ClipboardData(text: hist.asText(key: _filter == 'errors' ? null : _filter)));
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('History copied')));
                },
              ),
            ],
          ),
          body: Column(
            children: [
              // PINNED: overall line + the 6 checks. Never scrolls away.
              Padding(
                padding: const EdgeInsets.fromLTRB(AppSpacing.screenPad, 0, AppSpacing.screenPad, AppSpacing.s),
                child: _pinned(context, diag, hist),
              ),
              _chips(context),
              Expanded(
                child: Stack(
                  children: [
                    _list(context, shown, errors),
                    if (pending > 0)
                      Positioned(
                        top: 6,
                        left: 0,
                        right: 0,
                        child: Center(
                          child: ActionChip(
                            backgroundColor: p.accent.withOpacity(0.16),
                            label: Text('$pending new - Jump to latest',
                                style: AppTypography.metadata.copyWith(color: p.accent, fontWeight: FontWeight.w700)),
                            onPressed: _jumpToLatest,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _pinned(BuildContext context, DiagStatus diag, DiagHistory hist) {
    final p = context.palette;
    final over = diag.overall;
    final overText = over == DiagLevel.ok
        ? 'All 6 checks OK'
        : '${diag.count(DiagLevel.bad)} bad, ${diag.count(DiagLevel.warn)} warn, ${diag.count(DiagLevel.unknown)} unknown';
    return Container(
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(color: _color(context, over).withOpacity(0.55), width: 1),
      ),
      child: Column(
        children: [
          Row(
            children: [
              Container(width: 10, height: 10, decoration: BoxDecoration(color: _color(context, over), shape: BoxShape.circle)),
              const SizedBox(width: 8),
              Text(overText, style: AppTypography.secondaryData.copyWith(color: p.textPrimary, fontWeight: FontWeight.w700, fontSize: 13)),
            ],
          ),
          const SizedBox(height: 8),
          for (final i in diag.items)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Container(width: 8, height: 8, decoration: BoxDecoration(color: _color(context, i.level), shape: BoxShape.circle)),
                  const SizedBox(width: 8),
                  SizedBox(
                    width: 92,
                    child: Text(i.title, style: AppTypography.metadata.copyWith(color: p.textPrimary, fontSize: 12, fontWeight: FontWeight.w600)),
                  ),
                  Expanded(
                    child: Text(i.detail, overflow: TextOverflow.ellipsis, style: AppTypography.metadata.copyWith(color: _color(context, i.level), fontSize: 12)),
                  ),
                  Text(_ago(hist.since(i.key)), style: AppTypography.metadata.copyWith(color: p.textMuted, fontSize: 11)),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _chips(BuildContext context) {
    final p = context.palette;
    final items = <MapEntry<String?, String>>[
      const MapEntry(null, 'All'),
      const MapEntry('backend', 'Backend'),
      const MapEntry('ws', 'Socket'),
      const MapEntry('market_data', 'Data'),
      const MapEntry('scanner', 'Scan'),
      const MapEntry('strategy', 'Strategy'),
      const MapEntry('execution', 'Orders'),
      const MapEntry('errors', 'Exchange errors'),
    ];
    return SizedBox(
      height: 40,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenPad),
        children: [
          for (final e in items)
            Padding(
              padding: const EdgeInsets.only(right: 6),
              child: ChoiceChip(
                label: Text(e.value, style: AppTypography.metadata.copyWith(fontSize: 12, color: _filter == e.key ? p.accent : p.textSecondary)),
                selected: _filter == e.key,
                selectedColor: p.accent.withOpacity(0.16),
                onSelected: (_) {
                  AppHaptics.light();
                  setState(() {
                    _filter = e.key;
                    _reading = false;
                  });
                  if (_scroll.hasClients) _scroll.jumpTo(0);
                },
              ),
            ),
        ],
      ),
    );
  }

  Widget _list(BuildContext context, List<DiagEvent> shown, List<Map<String, dynamic>> errors) {
    final p = context.palette;
    if (_filter == 'errors') {
      if (errors.isEmpty) return _empty(context, 'No exchange errors reported by the backend.');
      return ListView.builder(
        controller: _scroll,
        padding: const EdgeInsets.all(AppSpacing.screenPad),
        itemCount: errors.length,
        itemBuilder: (context, n) {
          final e = errors[n];
          final code = (e['code'] as num?)?.toInt();
          final sym = e['symbol']?.toString();
          final time = e['time']?.toString();
          return _row(context, p.warning, 'Binance error ${code ?? '?'}${sym != null ? ' ($sym)' : ''}', time ?? '--');
        },
      );
    }
    if (shown.isEmpty) {
      return _empty(context, 'No change yet. A line is added only when a check changes level (history is kept while the app is open, up to ${DiagHistory.instance.maxEvents} lines).');
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(AppSpacing.screenPad),
      itemCount: shown.length,
      itemBuilder: (context, n) {
        final e = shown[n];
        return _row(context, _color(context, e.to), '${e.title}: ${diagLevelWord(e.from)} -> ${diagLevelWord(e.to)}', '${e.clock}  ${e.detail}');
      },
    );
  }

  Widget _row(BuildContext context, Color dot, String head, String sub) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Container(width: 8, height: 8, decoration: BoxDecoration(color: dot, shape: BoxShape.circle)),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(head, style: AppTypography.metadata.copyWith(color: p.textPrimary, fontSize: 12.5, fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(sub, style: AppTypography.metadata.copyWith(color: p.textSecondary, fontSize: 11.5)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _empty(BuildContext context, String text) {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.xxl),
      child: Text(text, textAlign: TextAlign.center, style: AppTypography.metadata.copyWith(color: context.palette.textMuted, fontSize: 12.5)),
    );
  }
}
