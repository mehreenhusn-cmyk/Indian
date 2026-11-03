import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/load_state.dart';
import '../widgets/owl_card.dart';

/// Part 48 (FILE 57): APP PROBLEMS page. ONE place where everything that fails or does not perform is listed, so the owner can take a screenshot
/// or press Copy / Copy all and send it to Claude to fix. Read only: it asks GET /api/v2/app_problems (Part 47) and shows what the backend says,
/// plus the app's OWN failed or slow fetches (AppErrorLog in the provider: wrong answer, API off, old backend, not reachable, 8 s or slower).
/// Layout: ONE summary on top (headline, counts, Copy all), then red and yellow backend problems, then the app's own fetch problems, then the notes (INFO) in a closed fold.
/// Every item is a plain block: what failed, where, the fix in one line, the time. Backend time is UTC, app time is the phone's local time.
/// Nothing here changes anything. LoadSpinner (Part 1): 12 s then Retry. Opened from Settings and tools. Dart NOT compiled (the APK build is the proof).

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<Map<String, dynamic>> _l(Object? v) => v is List ? [for (final e in v) _m(e)] : <Map<String, dynamic>>[];
int _i(Object? v) => v is num ? v.toInt() : 0;
String _s(Object? v) => v == null ? '' : '$v';

const _months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

String _time(DateTime t) {
  String two(int x) => x < 10 ? '0$x' : '$x';
  return '${t.day} ${_months[t.month - 1]} ${two(t.hour)}:${two(t.minute)}';
}

class AppProblemsScreen extends StatefulWidget {
  const AppProblemsScreen({super.key});

  @override
  State<AppProblemsScreen> createState() => _AppProblemsScreenState();
}

class _AppProblemsScreenState extends State<AppProblemsScreen> {
  Map<String, dynamic>? _data;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() => _data = null);
    final d = await context.read<AppProvider>().fetchAppProblems();
    if (!mounted) return;
    setState(() => _data = d);
  }

  Future<void> _copy(String text, String msg) async {
    await Clipboard.setData(ClipboardData(text: text));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg), duration: const Duration(seconds: 2)));
  }

  bool _reachable(Map<String, dynamic> d) => '${d['state']}' == 'OK' || '${d['state']}' == 'PROBLEMS';

  /// Plain line for a backend answer that is not the list itself (off / old / error / busy); '' when the list was read.
  String _stateLine(Map<String, dynamic> d) {
    switch ('${d['state']}') {
      case 'off':
        return 'The V2 data API is off, so the backend problem list cannot be read (file v2_api_enabled is missing or not 1).';
      case 'old':
        return 'This backend has no app problems route (old backend, or the route is not mounted). Install the newest backend zip and restart the backend.';
      case 'error':
        return 'The backend could not be reached. Check that it is running and that the phone is on the same network.';
      case 'busy':
        return _s(d['headline']).isEmpty ? 'The problem list is being made. Press refresh in a few seconds.' : _s(d['headline']);
      default:
        return '';
    }
  }

  String _itemText(Map<String, dynamic> e) => '[${_s(e['sev'])}] ${_s(e['area'])} | ${_s(e['where'])} | ${_s(e['text'])} | Fix: ${_s(e['fix'])} | ${_s(e['when'])}';

  String _appText(AppErrorEntry e) => '[APP] ${e.path} | ${e.what} | ${_time(e.at)} (phone time)';

  String _allText(Map<String, dynamic> d) {
    final out = <String>['OWL APP PROBLEMS (phone time ${_time(DateTime.now())})'];
    if (_reachable(d)) {
      out.add(_s(d['copy_text']));
    } else {
      out.add('[BAD] Backend | /api/v2/app_problems | ${_stateLine(d)}');
    }
    for (final e in AppErrorLog.items) {
      out.add(_appText(e));
    }
    return out.join('\n');
  }

  Color _sc(AppPalette p, String sev) => sev == 'BAD' ? p.loss : (sev == 'WARN' ? p.warning : p.textMuted);

  Widget _chip(String text, Color c) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: c.withOpacity(0.15), borderRadius: BorderRadius.circular(20)),
        child: Text(text, style: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w800, color: c)),
      );

  Widget _line(AppPalette p, String t, {Color? c, double size = 12, FontWeight? w}) =>
      Padding(padding: const EdgeInsets.only(top: 5), child: Text(t, style: TextStyle(fontSize: size, fontWeight: w, color: c ?? p.textSecondary)));

  Widget _block(AppPalette p, {required String sev, required String head, required String text, String fix = '', required String when, required String copy}) {
    final c = _sc(p, sev);
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: OWLCard(
        edge: c,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            _chip(sev == 'BAD' ? 'RED' : (sev == 'WARN' ? 'YELLOW' : 'NOTE'), c),
            const SizedBox(width: 8),
            Expanded(child: Text(head, style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w800, color: p.textPrimary))),
          ]),
          _line(p, text, c: p.textPrimary, size: 12.5),
          if (fix.isNotEmpty) _line(p, 'Fix: $fix', size: 11.5),
          Row(children: [
            Expanded(child: Text(when, style: TextStyle(fontSize: 10.5, color: p.textMuted))),
            TextButton.icon(
              onPressed: () => _copy(copy, 'Copied'),
              icon: const Icon(Icons.copy_rounded, size: 15),
              label: const Text('Copy', style: TextStyle(fontSize: 12)),
            ),
          ]),
        ]),
      ),
    );
  }

  Widget _head(AppPalette p, String t) => Padding(
        padding: const EdgeInsets.only(top: 18),
        child: Text(t, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, letterSpacing: 0.6, color: p.textMuted)),
      );

  Widget _summary(AppPalette p, Map<String, dynamic> d, int bad, int warn, int app) {
    final reach = _reachable(d);
    final fine = reach && bad == 0 && warn == 0 && app == 0;
    final head = !reach ? 'The backend list could not be read' : (fine ? 'No problems found' : '$bad red, $warn yellow on the backend, $app in the app');
    return OWLCard(
      edge: fine ? p.profit : (bad > 0 || !reach ? p.loss : p.warning),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text('App Problems', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: p.textPrimary))),
          if (reach) _chip('${_i(_m(d['counts'])['INFO'])} notes', p.textMuted),
        ]),
        const SizedBox(height: 8),
        Text(head, style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: p.textPrimary)),
        _line(p, 'Take a screenshot of this page, or press Copy all and paste it to Claude. Read only: nothing here changes anything.', size: 11.5),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.icon(
            onPressed: () => _copy(_allText(d), 'Copied all problems'),
            icon: const Icon(Icons.copy_all_rounded, size: 16),
            label: const Text('Copy all'),
          ),
        ),
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final d = _data;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: AppBar(
        backgroundColor: p.bg,
        elevation: 0,
        title: Text('App Problems', style: context.type.section.copyWith(fontWeight: FontWeight.w700)),
        actions: [IconButton(onPressed: _load, icon: const Icon(Icons.refresh_rounded))],
      ),
      body: d == null ? LoadSpinner(onRetry: _load) : _body(p, d),
    );
  }

  Widget _body(AppPalette p, Map<String, dynamic> d) {
    final reach = _reachable(d);
    final items = reach ? _l(d['items']) : <Map<String, dynamic>>[];
    final problems = [for (final e in items) if ('${e['sev']}' != 'INFO') e];
    final notes = [for (final e in items) if ('${e['sev']}' == 'INFO') e];
    final appList = AppErrorLog.items;
    final bad = problems.where((e) => '${e['sev']}' == 'BAD').length;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 32),
      children: [
        _summary(p, d, bad, problems.length - bad, appList.length),
        if (!reach)
          _block(p, sev: 'BAD', head: 'Backend | /api/v2/app_problems', text: _stateLine(d), when: _time(DateTime.now()) + ' (phone time)', copy: '[BAD] Backend | /api/v2/app_problems | ${_stateLine(d)}'),
        if (problems.isNotEmpty) _head(p, 'ON THE BACKEND (${problems.length})'),
        for (final e in problems)
          _block(p, sev: _s(e['sev']), head: '${_s(e['area'])} | ${_s(e['where'])}', text: _s(e['text']), fix: _s(e['fix']), when: _s(e['when']), copy: _itemText(e)),
        if (appList.isNotEmpty) _head(p, 'IN THE APP: FAILED OR SLOW FETCHES (${appList.length})'),
        for (final e in appList)
          _block(p, sev: e.slow ? 'WARN' : 'BAD', head: e.path, text: e.what, when: '${_time(e.at)} (phone time)', copy: _appText(e)),
        if (appList.isNotEmpty)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () {
                AppErrorLog.clear();
                setState(() {});
              },
              child: const Text('Clear the app list'),
            ),
          ),
        if (notes.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Theme(
              data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
              child: ExpansionTile(
                tilePadding: EdgeInsets.zero,
                childrenPadding: EdgeInsets.zero,
                title: Text('Notes (${notes.length}): not problems, just good to know', style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: p.textSecondary)),
                expandedCrossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final e in notes)
                    _block(p, sev: 'INFO', head: '${_s(e['area'])} | ${_s(e['where'])}', text: _s(e['text']), fix: _s(e['fix']), when: _s(e['when']), copy: _itemText(e)),
                ],
              ),
            ),
          ),
        _line(p, 'The backend does not time its routes, so a slow route is not listed on the backend side. The app lists every fetch that took 8 seconds or more. The app list is kept in memory only and is empty again after the app restarts.', size: 11, c: p.textMuted),
      ],
    );
  }
}
