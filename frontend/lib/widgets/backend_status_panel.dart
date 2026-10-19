import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Left-swipe "Backend" panel: one glance tells you if the backend answers, which zip is live,
/// how long it has been up, how often it restarted today, and the last problems from its log.
/// Numbers come from GET /api/ops (backend ops_status.py). It polls every 5 s only while the drawer is open.
/// "Copy report" puts a plain-text summary on the clipboard so it can be pasted into a chat.
class BackendStatusPanel extends StatefulWidget {
  const BackendStatusPanel({super.key});

  @override
  State<BackendStatusPanel> createState() => _BackendStatusPanelState();
}

class _BackendStatusPanelState extends State<BackendStatusPanel> {
  Timer? _timer;
  Map<String, dynamic>? _d;
  bool _failed = false;
  int? _ping;
  bool _wsUp = false;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 5), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    final pr = context.read<AppProvider>();
    final d = await pr.fetchOps();
    if (!mounted) return;
    setState(() {
      _d = d;
      _failed = d == null;
      _ping = pr.wsLatencyMs;
      _wsUp = pr.wsConnected;
    });
  }

  static String _dur(num s) {
    final n = s.toInt();
    if (n < 90) return '${n}s';
    if (n < 5400) return '${(n / 60).round()} min';
    if (n < 172800) return '${(n / 3600).toStringAsFixed(1)} h';
    return '${(n / 86400).toStringAsFixed(1)} d';
  }

  static String _when(num epoch) {
    if (epoch <= 0) return '-';
    final dt = DateTime.fromMillisecondsSinceEpoch(epoch.toInt() * 1000);
    const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    String two(int v) => v < 10 ? '0$v' : '$v';
    return '${dt.day} ${m[dt.month - 1]} ${two(dt.hour)}:${two(dt.minute)}';
  }

  String _report() {
    final d = _d;
    if (d == null) return 'OWL backend: NOT ANSWERING (${DateTime.now()})';
    final z = (d['zip'] is Map) ? d['zip'] as Map : const {};
    final has = (d['has'] is Map) ? d['has'] as Map : const {};
    final probs = (d['problems'] is List) ? (d['problems'] as List).join('\n  ') : '';
    return 'OWL backend report ${DateTime.now()}\n'
        'build: ${d['build']}  up: ${_dur(d['uptime_s'] ?? 0)}  pid: ${d['pid']}\n'
        'zip: ${z['name']}  (deployed ${_when(z['deployed_at'] ?? 0)})\n'
        'features: vision_notebook=${has['vision_notebook']} india_fast_ticks=${has['india_fast_ticks']} free_keys_4=${has['free_keys_4']}\n'
        'restarts today: ${d['restarts_today']}  crash loops: ${d['crash_loops']}\n'
        'data folder: ${d['data_dir']}\n'
        'ping: ${_ping ?? '-'} ms  websocket: ${_wsUp ? 'up' : 'down'}\n'
        'last exits:\n  ${(d['last_exits'] is List) ? (d['last_exits'] as List).join('\n  ') : ''}\n'
        'problems:\n  $probs';
  }

  Widget _row(AppPalette p, AppText t, String label, String value, {Color? color}) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(width: 74, child: Text(label, style: t.metadata.copyWith(color: p.textMuted, fontSize: 11.5))),
          Expanded(child: Text(value, style: t.metadata.copyWith(color: color ?? p.textPrimary, fontSize: 11.5, fontWeight: FontWeight.w600))),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final d = _d;
    final okColor = _failed ? p.loss : p.profit;
    final z = (d != null && d['zip'] is Map) ? d['zip'] as Map : const {};
    final has = (d != null && d['has'] is Map) ? d['has'] as Map : const {};
    final restarts = (d?['restarts_today'] ?? 0) as num;
    final loops = (d?['crash_loops'] ?? 0) as num;
    final probs = (d != null && d['problems'] is List) ? (d['problems'] as List) : const [];
    final slow = (_ping ?? 0) > 800;
    String tick(bool v) => v ? 'yes' : 'NO';

    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: p.border.withOpacity(0.6), width: 0.8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(shape: BoxShape.circle, color: okColor)),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _failed ? 'NOT ANSWERING' : (d == null ? 'checking...' : 'RUNNING · up ${_dur(d['uptime_s'] ?? 0)}'),
                  style: t.metadata.copyWith(color: okColor, fontWeight: FontWeight.w800, fontSize: 12),
                ),
              ),
              InkWell(
                onTap: () {
                  Clipboard.setData(ClipboardData(text: _report()));
                  ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Backend report copied')));
                },
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  child: Text('COPY', style: t.metadata.copyWith(color: p.accent, fontWeight: FontWeight.w800, fontSize: 11.5)),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          if (_failed)
            Text('The app cannot reach the backend. Open Termux and run:  bash ~/owl_auto.sh status',
                style: t.metadata.copyWith(color: p.warning, fontSize: 11.5))
          else if (d != null) ...[
            _row(p, t, 'Code', (z['name'] ?? '').toString().isEmpty ? 'not from owl_auto.sh' : '${z['name']}'),
            _row(p, t, 'Deployed', _when(z['deployed_at'] ?? 0)),
            _row(p, t, 'Features', 'notebook ${tick(has['vision_notebook'] == true)} · India ticks ${tick(has['india_fast_ticks'] == true)} · 4 keys ${tick(has['free_keys_4'] == true)}'),
            _row(p, t, 'Restarts', 'today $restarts' + (loops > 0 ? ' · crash loops $loops' : ''),
                color: loops > 0 || restarts > 3 ? p.loss : (restarts > 0 ? p.warning : null)),
            _row(p, t, 'Speed', !_wsUp ? 'live link DOWN' : (_ping == null ? '-' : (slow ? 'SLOW ${_ping} ms' : '${_ping} ms')),
                color: !_wsUp ? p.loss : (slow ? p.warning : null)),
            const SizedBox(height: 2),
            if (probs.isEmpty)
              Text('No problems in the backend log.', style: t.metadata.copyWith(color: p.textMuted, fontSize: 11.5))
            else
              ...probs.take(4).map((l) => Padding(
                    padding: const EdgeInsets.only(bottom: 2),
                    child: Text('$l', maxLines: 2, overflow: TextOverflow.ellipsis, style: t.metadata.copyWith(color: p.warning, fontSize: 10.5)),
                  )),
          ],
        ],
      ),
    );
  }
}
