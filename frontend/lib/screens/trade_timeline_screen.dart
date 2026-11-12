import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';

/// Part 12B: the TRADES screen. One clear card per trade: SIGNAL seen -> OPENED -> TP1 BANKED -> CLOSED (why, net). Open trades first, then the last 3 days closed.
/// Main bot and Sniper trades share one paper book, so a Main / Sniper switch at the top shows them APART (default Main); totals are never added together.
/// Reads GET /api/v2/trades every 15 s while open (read only). A NEW signal or a NEW trade since the screen opened shows a banner at the bottom (the alert).
/// Times are shown in IST. Paper money only. Dart NOT compiled here (the GitHub APK build is the proof).
class TradeTimelineScreen extends StatefulWidget {
  const TradeTimelineScreen({super.key});

  @override
  State<TradeTimelineScreen> createState() => _TradeTimelineScreenState();
}

class _TradeTimelineScreenState extends State<TradeTimelineScreen> {
  static Map<String, dynamic> _cache = {};
  Map<String, dynamic> _data = Map<String, dynamic>.from(_cache);
  String _problem = '';
  String _filter = 'ALL'; // ALL | OPEN | WIN | LOSS (inside the chosen group)
  String _group = 'MAIN'; // MAIN | SNIPER: the two share one paper book, so they are shown apart and NEVER added together
  bool _busy = false;
  String _seen = '';
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(seconds: 15), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  List<Map<String, dynamic>> _list(dynamic v) => v is List ? v.whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList() : <Map<String, dynamic>>[];

  /// A key of the newest signal and the newest open trade; when it changes after the first answer, the alert shows.
  String _key(Map<String, dynamic> d) {
    final sg = _list(d['signals']);
    final op = _list(d['open']).where((t) => '${t['g'] ?? 'MAIN'}' == 'MAIN').toList(); // the alert is for the Main bot
    return '${sg.isNotEmpty ? '${sg.first['t']}|${sg.first['sym']}' : ''}#${op.isNotEmpty ? '${op.first['id']}' : ''}';
  }

  Future<void> _poll() async {
    if (_busy || !mounted) return;
    _busy = true;
    try {
      final r = await context.read<AppProvider>().fetchTrades();
      if (!mounted) return;
      if (r['state'] != null || r['error'] != null) {
        setState(() => _problem = r['error'] != null
            ? 'The backend says: ${r['error']}'
            : (r['state'] == 'off'
                ? 'The V2 data API is off. Make the file v2_api_enabled (containing 1) in the owl_data folder.'
                : (r['state'] == 'old' ? 'This backend does not have the Trades route yet. Install the newest zip and restart the backend.' : 'Cannot reach the backend right now. It will try again.')));
        return;
      }
      final k = _key(r);
      final changed = _seen.isNotEmpty && k != _seen;
      _cache = r;
      setState(() {
        _data = r;
        _problem = '';
        _seen = k;
      });
      if (changed) {
        final sg = _list(r['signals']);
        final s = sg.isNotEmpty ? sg.first : <String, dynamic>{};
        final msg = s.isNotEmpty ? 'New signal: ${s['sym']} ${s['side']} ${s['tf']}' : 'New trade opened';
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 6)));
      }
    } catch (_) {
      if (mounted) setState(() => _problem = 'Cannot reach the backend right now. It will try again.');
    } finally {
      _busy = false;
    }
  }

  /// Unix seconds (UTC) -> "dd Mon HH:mm" in IST (UTC + 5:30).
  String _ist(dynamic ts) {
    if (ts is! num) return '-';
    final d = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round(), isUtc: true).add(const Duration(hours: 5, minutes: 30));
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    String two(int v) => v < 10 ? '0$v' : '$v';
    return '${two(d.day)} ${m[d.month - 1]} ${two(d.hour)}:${two(d.minute)}';
  }

  Color _netColor(num? n) => n == null ? Colors.grey : (n > 0 ? Colors.green.shade600 : (n < 0 ? Colors.red.shade600 : Colors.grey));

  Color _evColor(String label) {
    switch (label) {
      case 'SIGNAL':
        return Colors.blue.shade600;
      case 'OPENED':
        return Colors.orange.shade700;
      case 'TP1 BANKED':
        return Colors.green.shade600;
      default:
        return Colors.grey.shade700;
    }
  }

  Widget _card(Map<String, dynamic> t) {
    final open = t['state'] == 'OPEN';
    final net = t['net'] is num ? t['net'] as num : null;
    final events = _list(t['events']);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 6),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(child: Text('${t['sym']}  ${t['side']}  ${t['tf'] ?? ''}', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700))),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(color: (open ? Colors.orange : _netColor(net)).withOpacity(0.15), borderRadius: BorderRadius.circular(8)),
              child: Text(open ? 'OPEN' : (net == null ? 'CLOSED' : '${net >= 0 ? '+' : ''}${net.toStringAsFixed(2)} USDT'),
                  style: TextStyle(fontWeight: FontWeight.w700, color: open ? Colors.orange.shade800 : _netColor(net))),
            ),
          ]),
          const SizedBox(height: 8),
          for (final e in events)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Icon(Icons.circle, size: 10, color: _evColor('${e['label']}')),
                const SizedBox(width: 8),
                SizedBox(width: 92, child: Text(_ist(e['t']), style: const TextStyle(fontSize: 12))),
                Expanded(child: Text('${e['label']}${'${e['note']}'.isEmpty ? '' : '  -  ${e['note']}'}', style: const TextStyle(fontSize: 12.5))),
              ]),
            ),
          if (open && t['peak_roi'] is num) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Best so far ${(t['peak_roi'] as num).toStringAsFixed(1)}%  |  worst ${(t['worst_roi'] is num ? (t['worst_roi'] as num).toStringAsFixed(1) : '-')}%', style: const TextStyle(fontSize: 12))),
        ]),
      ),
    );
  }

  Widget _chip(String name) => Padding(
        padding: const EdgeInsets.only(right: 6),
        child: ChoiceChip(label: Text(name), selected: _filter == name, onSelected: (_) => setState(() => _filter = name)),
      );

  @override
  Widget build(BuildContext context) {
    bool inGroup(Map<String, dynamic> t) => ('${t['g'] ?? 'MAIN'}') == _group;
    final open = _list(_data['open']).where(inGroup).toList();
    var closed = _list(_data['closed']).where(inGroup).toList();
    if (_filter == 'WIN') closed = closed.where((t) => (t['net'] is num) && (t['net'] as num) > 0).toList();
    if (_filter == 'LOSS') closed = closed.where((t) => (t['net'] is num) && (t['net'] as num) <= 0).toList();
    final showOpen = _filter == 'ALL' || _filter == 'OPEN';
    if (_filter == 'OPEN') closed = <Map<String, dynamic>>[];
    final tot = closed.fold<double>(0, (a, t) => a + (t['net'] is num ? (t['net'] as num).toDouble() : 0));
    return RefreshIndicator(
      onRefresh: _poll,
      child: ListView(padding: const EdgeInsets.all(12), children: [
        if (_problem.isNotEmpty) Padding(padding: const EdgeInsets.only(bottom: 8), child: Text(_problem, style: TextStyle(color: Colors.red.shade700))),
        Row(children: [
          for (final g in const ['MAIN', 'SNIPER'])
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(label: Text(g == 'MAIN' ? 'Main bot' : 'Sniper'), selected: _group == g, onSelected: (_) => setState(() => _group = g)),
            ),
        ]),
        SingleChildScrollView(scrollDirection: Axis.horizontal, child: Row(children: [_chip('ALL'), _chip('OPEN'), _chip('WIN'), _chip('LOSS')])),
        const SizedBox(height: 6),
        Text('${_group == 'MAIN' ? 'MAIN BOT' : 'SNIPER'} only: ${open.length} open  |  ${closed.length} closed shown  |  net ${tot >= 0 ? '+' : ''}${tot.toStringAsFixed(2)} USDT (last ${_data['days'] ?? 3} days). Paper money only.', style: const TextStyle(fontSize: 12)),
        if (_data.isEmpty && _problem.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
        if (showOpen && open.isNotEmpty) const Padding(padding: EdgeInsets.only(top: 10), child: Text('OPEN NOW', style: TextStyle(fontWeight: FontWeight.w800))),
        if (showOpen) for (final t in open) _card(t),
        if (closed.isNotEmpty) const Padding(padding: EdgeInsets.only(top: 10), child: Text('CLOSED (newest first)', style: TextStyle(fontWeight: FontWeight.w800))),
        for (final t in closed) _card(t),
        if (_data.isNotEmpty && open.isEmpty && closed.isEmpty) const Padding(padding: EdgeInsets.all(24), child: Text('No trades to show for this filter yet.')),
        if (_data['note'] != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text('${_data['note']}', style: const TextStyle(fontSize: 11.5))),
      ]),
    );
  }
}
