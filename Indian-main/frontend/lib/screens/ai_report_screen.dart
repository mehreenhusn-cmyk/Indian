import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:provider/provider.dart';
import 'package:share_plus/share_plus.dart';

import '../providers/app_provider.dart';
import '../theme/app_motion.dart';
import '../theme/app_theme.dart';

/// AI Report - runs the Filter Lab tests (3m, 5m, 15m) and gives ONE text file with everything an AI needs to find the leaks.
/// Read-only: nothing here touches the bot. The backend builds the file (ai_report.py); the phone only starts, saves and shares it.
class AiReportScreen extends StatefulWidget {
  const AiReportScreen({super.key});

  @override
  State<AiReportScreen> createState() => _AiReportScreenState();
}

class _AiReportScreenState extends State<AiReportScreen> {
  Map<String, dynamic>? _lab;
  Timer? _timer;
  bool _starting = false;
  bool _busy = false;
  String _msg = '';
  bool _msgOk = true;
  String _savedPath = '';

  String get _base => context.read<AppProvider>().baseUrl;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _poll());
    _timer = Timer.periodic(const Duration(seconds: 4), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<Map<String, dynamic>> _getJson(String path, {int seconds = 15}) async {
    final res = await http.get(Uri.parse('$_base$path')).timeout(Duration(seconds: seconds));
    if (res.statusCode != 200) throw 'The backend answered HTTP ${res.statusCode}';
    final m = jsonDecode(utf8.decode(res.bodyBytes));
    if (m is! Map) throw 'The backend sent an unexpected reply';
    return Map<String, dynamic>.from(m);
  }

  Future<void> _poll() async {
    if (!mounted) return;
    try {
      final m = await _getJson('/api/filter_lab_all');
      if (mounted) setState(() => _lab = m);
    } catch (_) {
      // a missed poll is fine, the next one retries
    }
  }

  void _say(String text, {bool ok = true}) {
    if (!mounted) return;
    setState(() {
      _msg = text;
      _msgOk = ok;
    });
  }

  Future<void> _startTests() async {
    AppHaptics.light();
    setState(() => _starting = true);
    try {
      final m = await _getJson('/api/filter_lab_all?start=1&restart=1');
      if (mounted) setState(() => _lab = m);
      _say('Tests started. This takes a few minutes. You can leave this screen and come back.');
    } catch (e) {
      _say('Could not start the tests: $e', ok: false);
    }
    if (mounted) setState(() => _starting = false);
  }

  Future<void> _download() async {
    AppHaptics.light();
    setState(() {
      _busy = true;
      _savedPath = '';
    });
    try {
      final r = await _getJson('/api/report/save', seconds: 90);
      final ok = r['ok'] == true;
      if (ok) {
        _savedPath = '${r['path']}';
        _say('Saved to your phone Download folder. Send this file to any AI.');
      } else {
        _say('${r['hint'] ?? 'Could not save the file.'}', ok: false);
      }
    } catch (e) {
      _say('Could not save the report: $e', ok: false);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<http.Response> _fetchReport() async {
    final res = await http.get(Uri.parse('$_base/api/report')).timeout(const Duration(seconds: 90));
    if (res.statusCode != 200) throw 'The backend answered HTTP ${res.statusCode}';
    return res;
  }

  Future<void> _share() async {
    AppHaptics.light();
    setState(() => _busy = true);
    try {
      final res = await _fetchReport();
      final dir = await getTemporaryDirectory();
      final file = File('${dir.path}/owl_report.txt');
      await file.writeAsBytes(res.bodyBytes);
      await Share.shareXFiles([XFile(file.path, mimeType: 'text/plain')], subject: 'Owl bot report');
    } catch (e) {
      _say('Could not share the report: $e', ok: false);
    }
    if (mounted) setState(() => _busy = false);
  }

  Future<void> _copy() async {
    AppHaptics.light();
    setState(() => _busy = true);
    try {
      final res = await _fetchReport();
      await Clipboard.setData(ClipboardData(text: utf8.decode(res.bodyBytes)));
      _say('Report text copied. Paste it into any AI chat.');
    } catch (e) {
      _say('Could not copy the report: $e', ok: false);
    }
    if (mounted) setState(() => _busy = false);
  }

  Widget _card(BuildContext context, {required String title, required List<Widget> children}) {
    final p = context.palette;
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: p.border),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        ...children,
      ]),
    );
  }

  String _stateText(String s) {
    switch (s) {
      case 'done':
        return 'Done';
      case 'running':
        return 'Running...';
      case 'queued':
        return 'Waiting';
      case 'error':
        return 'Error (see report)';
      default:
        return 'Not run yet';
    }
  }

  Widget _tfRow(BuildContext context, String tf) {
    final p = context.palette;
    final tfs = (_lab?['tfs'] is Map) ? Map<String, dynamic>.from(_lab!['tfs'] as Map) : <String, dynamic>{};
    final j = (tfs[tf] is Map) ? Map<String, dynamic>.from(tfs[tf] as Map) : <String, dynamic>{};
    final s = '${j['state'] ?? 'not run'}';
    final col = s == 'done' ? p.profit : (s == 'error' ? p.loss : (s == 'running' ? p.accent : p.textMuted));
    final prog = s == 'running' ? '${j['progress'] ?? ''}' : '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(width: 44, child: Text(tf, style: context.type.primary.copyWith(fontWeight: FontWeight.w600))),
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_stateText(s), style: context.type.secondary.copyWith(color: col)),
            if (prog.isNotEmpty) Text(prog, style: context.type.metadata, maxLines: 2, overflow: TextOverflow.ellipsis),
          ]),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final running = _lab?['running'] == true;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text('AI Report', style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            _card(context, title: '1. Run the tests', children: [
              Text(
                'Replays your strategy on Binance candles for 3m, 5m and 15m and tests wider stop-losses, Bollinger Band filters and the Z-score / TSI rules. '
                'It takes a few minutes and does not touch your bot.',
                style: context.type.secondary,
              ),
              const SizedBox(height: 10),
              _tfRow(context, '3m'),
              _tfRow(context, '5m'),
              _tfRow(context, '15m'),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: (running || _starting) ? null : _startTests,
                  icon: const Icon(Icons.play_arrow_rounded),
                  label: Text(running ? 'Tests are running...' : 'Run tests'),
                ),
              ),
            ]),
            _card(context, title: '2. Get the report file', children: [
              Text(
                'One text file with your strategy, a leakage summary, the Doctor, the test results and every closed trade. Any AI can read it.',
                style: context.type.secondary,
              ),
              const SizedBox(height: 10),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: _busy ? null : _download,
                  icon: const Icon(Icons.download_rounded),
                  label: const Text('Download to phone'),
                ),
              ),
              const SizedBox(height: 8),
              Row(children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _busy ? null : _share,
                    icon: const Icon(Icons.ios_share_rounded),
                    label: const Text('Share'),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _busy ? null : _copy,
                    icon: const Icon(Icons.copy_rounded),
                    label: const Text('Copy text'),
                  ),
                ),
              ]),
              if (_busy) ...[
                const SizedBox(height: 10),
                const LinearProgressIndicator(minHeight: 3),
              ],
              if (_msg.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(_msg, style: context.type.secondary.copyWith(color: _msgOk ? p.profit : p.warning)),
              ],
              if (_savedPath.isNotEmpty) ...[
                const SizedBox(height: 4),
                SelectableText(_savedPath, style: context.type.metadata),
              ],
            ]),
            _card(context, title: '3. Ask the AI', children: [
              Text(
                'Send the file to any AI and ask:\n"Read this report. Where does my strategy lose money, and which 3 changes should I test first?"',
                style: context.type.secondary,
              ),
              const SizedBox(height: 6),
              Text('Run the tests first, so the report has the stop-loss and Bollinger results.', style: context.type.metadata),
            ]),
          ],
        ),
      ),
    );
  }
}
