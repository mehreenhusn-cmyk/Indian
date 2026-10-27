import 'package:flutter/material.dart';
import '../utils/format.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// AI DATA BACKUP: everything the AI has learned (exit table, coin memory, day plan, Shadow Lab) is zipped once a day on the
/// phone. This card shows the last backup, makes one now, and queues a restore (applied when the backend restarts).
class AiBackupCard extends StatefulWidget {
  const AiBackupCard({super.key});

  @override
  State<AiBackupCard> createState() => _AiBackupCardState();
}

class _AiBackupCardState extends State<AiBackupCard> {
  Map<String, dynamic>? _d;
  bool _busy = false;
  bool _open = false;
  String _msg = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await context.read<AppProvider>().fetchAiBackup();
    if (!mounted) return;
    setState(() => _d = r ?? _d);
  }

  static String _ago(dynamic ts) {
    if (ts is! num) return 'never';
    final s = DateTime.now().millisecondsSinceEpoch / 1000.0 - ts.toDouble();
    if (s < 90) return 'just now';
    return '${fmtSpan(s)} ago';
  }

  Future<void> _backupNow() async {
    setState(() {
      _busy = true;
      _msg = '';
    });
    final r = await context.read<AppProvider>().runAiBackup();
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (r == null) {
        _msg = 'Backup did not finish (phone busy or no answer). Try again.';
      } else if (r['ok'] == true) {
        _msg = 'Saved ${r['name']} (${r['files']} files).';
        if (r['status'] is Map) _d = Map<String, dynamic>.from(r['status'] as Map);
      } else {
        _msg = 'Backup failed: ${r['error']}';
      }
    });
  }

  Future<void> _restore(String name) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Restore this backup?'),
        content: Text('$name will be put back the next time the backend restarts. What the AI learned after that backup is replaced '
            '(a safety copy of the current data is saved first).'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(c, true), child: const Text('Restore')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    setState(() => _busy = true);
    final r = await context.read<AppProvider>().restoreAiBackup(name);
    if (!mounted) return;
    setState(() {
      _busy = false;
      _msg = r == null ? 'Restore did not go through. Try again.' : '${r['msg']}';
      if (r != null && r['status'] is Map) _d = Map<String, dynamic>.from(r['status'] as Map);
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _d;
    final list = d == null || d['backups'] is! List ? <dynamic>[] : d['backups'] as List;
    final err = d == null ? '' : '${d['last_error'] ?? ''}';
    final pending = d != null && d['pending_restore'] == true;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: p.border, width: 0.8),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('AI DATA BACKUP', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)),
        const SizedBox(height: 8),
        Text(
            d == null
                ? 'Loading...'
                : (list.isEmpty ? 'No backup yet. The first one is made automatically, or tap Backup now.' : 'Last backup ${_ago(d['last_ok'])} (${list.length} saved, newest ${d['keep']} days kept).'),
            style: TextStyle(fontSize: 12.5, height: 1.4, fontWeight: FontWeight.w600, color: p.textPrimary)),
        if (err.isNotEmpty) Text('Last error: $err', style: TextStyle(fontSize: 11.5, color: p.loss, fontWeight: FontWeight.w700)),
        if (pending) Text('A restore is waiting. Restart the backend to apply it.', style: TextStyle(fontSize: 11.5, color: p.loss, fontWeight: FontWeight.w800)),
        if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text(_msg, style: TextStyle(fontSize: 11.5, color: p.textMuted))),
        const SizedBox(height: 8),
        Row(children: [
          OutlinedButton(onPressed: _busy ? null : _backupNow, child: Text(_busy ? 'Working...' : 'Backup now')),
          const SizedBox(width: 8),
          if (list.isNotEmpty) TextButton(onPressed: () => setState(() => _open = !_open), child: Text(_open ? 'Hide list' : 'Restore...')),
        ]),
        if (_open)
          for (final b in list)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Row(children: [
                Expanded(child: Text('${b['name']}  ·  ${b['size_kb']} KB', style: TextStyle(fontSize: 11.5, color: p.textPrimary))),
                TextButton(onPressed: _busy ? null : () => _restore('${b['name']}'), child: const Text('Restore')),
              ]),
            ),
      ]),
    );
  }
}
