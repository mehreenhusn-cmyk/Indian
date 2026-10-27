import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Settings > Download report. One text file about the whole app (what it is, dashboard, signals, alerts, AI Vision / AI Own / Lab,
/// backend health and errors, settings without keys, known problems) to send to any AI. Read-only: nothing here touches the bot.
/// Backend: /api/report/app (text) and /api/report/app_save (writes into the phone Download folder). Built in ai_report.py.
class ReportDownloadCard extends StatefulWidget {
  /// Defaults = the whole-app report. The Ping tab passes its own title / text + save routes.
  final String title;
  final String description;
  final String textPath;
  final String savePath;
  /// Name and type used by the Share button (UI-D: the Trades CSV shares as owl_trades.csv).
  final String fileName;
  final String mimeType;

  const ReportDownloadCard({
    super.key,
    this.title = 'Download report',
    this.description =
        'One text file with what the app is, dashboard, signals, alerts, AI Vision / AI Own, backend health and errors, your settings (no keys) and known problems. Send it to any AI.',
    this.textPath = '/api/report/app',
    this.savePath = '/api/report/app_save',
    this.fileName = 'owl_app_report.txt',
    this.mimeType = 'text/plain',
  });

  @override
  State<ReportDownloadCard> createState() => _ReportDownloadCardState();
}

class _ReportDownloadCardState extends State<ReportDownloadCard> {
  bool _busy = false;
  bool _ok = true;
  String _msg = '';

  String get _base => context.read<AppProvider>().baseUrl;

  void _say(String t, {bool ok = true}) {
    if (!mounted) return;
    setState(() {
      _msg = t;
      _ok = ok;
    });
  }

  Future<http.Response> _fetch() async {
    final res = await http.get(Uri.parse('$_base${widget.textPath}')).timeout(const Duration(seconds: 90));
    if (res.statusCode != 200) throw 'The backend answered HTTP ${res.statusCode}';
    return res;
  }

  Future<void> _run(Future<void> Function() job) async {
    if (_busy) return;
    HapticFeedback.lightImpact();
    setState(() {
      _busy = true;
      _msg = 'Building the report... (up to a minute)';
      _ok = true;
    });
    try {
      await job();
    } catch (e) {
      _say('Could not make the report: $e', ok: false);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _download() => _run(() async {
        final res = await http.get(Uri.parse('$_base${widget.savePath}')).timeout(const Duration(seconds: 90));
        if (res.statusCode != 200) throw 'The backend answered HTTP ${res.statusCode}';
        final r = jsonDecode(utf8.decode(res.bodyBytes));
        if (r is Map && r['ok'] == true) {
          _say('Saved: ${r['path']}');
        } else {
          _say('${r is Map ? (r['hint'] ?? 'Could not save the file.') : 'Could not save the file.'}', ok: false);
        }
      });

  Future<void> _share() => _run(() async {
        final res = await _fetch();
        final dir = await getTemporaryDirectory();
        final file = File('${dir.path}/${widget.fileName}');
        await file.writeAsBytes(res.bodyBytes);
        await Share.shareXFiles([XFile(file.path, mimeType: widget.mimeType)], subject: 'Owl Terminal report');
        _say('Shared.');
      });

  Future<void> _copy() => _run(() async {
        final res = await _fetch();
        await Clipboard.setData(ClipboardData(text: utf8.decode(res.bodyBytes)));
        _say('Copied. Paste it into any AI chat.');
      });

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: p.surface, borderRadius: BorderRadius.circular(14), border: Border.all(color: p.border)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(widget.title, style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 6),
        Text(
          widget.description,
          style: context.type.metadata,
        ),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(
            child: FilledButton(
              onPressed: _busy ? null : _download,
              child: _busy
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Text('Download'),
            ),
          ),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: _busy ? null : _share, child: const Text('Share')),
          const SizedBox(width: 8),
          OutlinedButton(onPressed: _busy ? null : _copy, child: const Text('Copy')),
        ]),
        if (_msg.isNotEmpty) ...[
          const SizedBox(height: 8),
          Text(_msg, style: context.type.secondary.copyWith(color: _ok ? p.profit : p.warning)),
        ],
      ]),
    );
  }
}
