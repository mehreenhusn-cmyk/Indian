import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../providers/app_provider.dart';
import '../theme/app_theme.dart';

/// Settings > AI keys. Paste ANY key: the backend works out whose key it is (Gemini, Groq, Mistral, OpenRouter, OpenAI, Claude)
/// and which model to use, then saves it in the first free slot. Each slot shows its company, model and state.
/// Backend: /api/ai/vkeys (ai_keys_api.py + ai_keyid.py). The Vision AI and the chat use these same slots.
class AiKeysCard extends StatefulWidget {
  const AiKeysCard({super.key});

  @override
  State<AiKeysCard> createState() => _AiKeysCardState();
}

class _AiKeysCardState extends State<AiKeysCard> {
  final TextEditingController _ctl = TextEditingController();
  List<Map<String, dynamic>> _slots = [];
  bool _loaded = false;
  bool _failed = false;
  bool _busy = false;
  bool _needSlot = false;
  bool _msgOk = true;
  String _msg = '';
  final Map<String, String> _slotMsg = {};
  final Set<String> _slotBusy = {};

  @override
  void initState() {
    super.initState();
    _ctl.addListener(() {
      if (mounted) setState(() {});
    });
    _load();
  }

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final d = await context.read<AppProvider>().fetchAiVKeys();
    if (!mounted) return;
    setState(() {
      _loaded = true;
      _failed = d == null;
      if (d != null && d['slots'] is List) {
        _slots = (d['slots'] as List).whereType<Map>().map((e) => Map<String, dynamic>.from(e)).toList();
      }
    });
  }

  /// Same first-letters rule as the backend, only to show "Looks like ..." while typing.
  static String _guess(String k) {
    final s = k.trim();
    if (s.length < 4) return '';
    if (s.startsWith('sk-ant-')) return 'Claude (Anthropic)';
    if (s.startsWith('sk-or-')) return 'OpenRouter';
    if (s.startsWith('AIza')) return 'Google Gemini';
    if (s.startsWith('gsk_')) return 'Groq';
    if (s.startsWith('sk-')) return 'OpenAI';
    if (s.toLowerCase().startsWith('mstr')) return 'Mistral';
    if (RegExp(r'^[A-Za-z0-9]{32}$').hasMatch(s)) return 'Mistral (probably)';
    return '';
  }

  Future<void> _paste() async {
    final data = await Clipboard.getData(Clipboard.kTextPlain);
    final t = (data?.text ?? '').trim();
    if (t.isEmpty || !mounted) return;
    setState(() => _ctl.text = t);
  }

  Future<void> _add({String? slot}) async {
    final key = _ctl.text.trim();
    if (key.isEmpty || _busy) return;
    setState(() {
      _busy = true;
      _msg = 'Checking the key with the AI company...';
      _msgOk = true;
      _needSlot = false;
    });
    final r = await context.read<AppProvider>().postAiVKey('add', {'key': key, if (slot != null) 'slot': slot});
    if (!mounted) return;
    final ok = r?['ok'] == true;
    setState(() {
      _busy = false;
      _msg = (r?['message'] ?? 'No answer from the backend.').toString();
      _msgOk = ok;
      _needSlot = r?['need_slot'] == true;
      if (ok) _ctl.clear();
    });
    await _load();
  }

  Future<void> _slotAction(String slot, String sub) async {
    if (_slotBusy.contains(slot)) return;
    setState(() {
      _slotBusy.add(slot);
      _slotMsg[slot] = sub == 'test' ? 'Testing...' : 'Checking...';
    });
    final r = await context.read<AppProvider>().postAiVKey(sub, {'slot': slot});
    if (!mounted) return;
    setState(() {
      _slotBusy.remove(slot);
      _slotMsg[slot] = (r?['message'] ?? 'No answer.').toString();
    });
    await _load();
  }

  Future<void> _remove(String slot, String label) async {
    final yes = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('Remove $label?'),
        content: const Text('The key is deleted from the backend. You can paste it again later.'),
        actions: [
          TextButton(onPressed: () => Navigator.of(c).pop(false), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.of(c).pop(true), child: const Text('Remove')),
        ],
      ),
    );
    if (yes != true || !mounted) return;
    await _slotAction(slot, 'clear');
    if (mounted) setState(() => _slotMsg.remove(slot));
  }

  String _hhmm(dynamic epoch) {
    final n = (epoch is num) ? epoch.toInt() : 0;
    if (n <= 0) return '';
    final dt = DateTime.fromMillisecondsSinceEpoch(n * 1000);
    return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
  }

  Widget _chip(AppPalette p, String text, Color c) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(color: c.withOpacity(0.12), borderRadius: BorderRadius.circular(8), border: Border.all(color: c.withOpacity(0.5))),
      child: Text(text, style: TextStyle(color: c, fontSize: 10.5, fontWeight: FontWeight.w800)),
    );
  }

  Widget _slotRow(AppPalette p, AppText t, Map<String, dynamic> s) {
    final slot = (s['slot'] ?? '').toString();
    final label = (s['label'] ?? '').toString();
    final filled = s['filled'] == true;
    final busy = _slotBusy.contains(slot);
    final msg = _slotMsg[slot] ?? '';
    Widget head;
    if (!filled) {
      head = Row(children: [
        Expanded(child: Text(label, style: TextStyle(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w800))),
        Text('empty', style: t.metadata.copyWith(color: p.textMuted)),
      ]);
      return Padding(padding: const EdgeInsets.only(bottom: 10), child: head);
    }
    final state = (s['state'] ?? 'ready').toString();
    final Color sc = state == 'ready' ? p.profit : (state == 'paused' ? p.warning : p.loss);
    final String st = state == 'ready' ? 'READY' : (state == 'paused' ? 'OUT OF QUOTA' : 'ERROR');
    final back = state == 'paused' ? _hhmm(s['paused_until']) : '';
    final model = (s['model'] ?? '').toString();
    final err = (s['last_error'] ?? '').toString();
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            Expanded(child: Text(label, style: TextStyle(color: p.textPrimary, fontSize: 13, fontWeight: FontWeight.w800))),
            _chip(p, st, sc),
          ]),
          const SizedBox(height: 3),
          Text('${s['provider_name'] ?? ''}  ·  ${model.isEmpty ? 'model: automatic' : model}', style: t.metadata.copyWith(color: p.textPrimary, fontSize: 11.5)),
          Text('key ${s['masked'] ?? ''}  ·  ${s['calls'] ?? 0} calls, ${s['ok'] ?? 0} worked, ${s['errors'] ?? 0} errors${back.isEmpty ? '' : '  ·  back about $back'}',
              style: t.metadata.copyWith(fontSize: 10.5)),
          if (err.isNotEmpty && state != 'ready') Padding(padding: const EdgeInsets.only(top: 2), child: Text(err, maxLines: 2, overflow: TextOverflow.ellipsis, style: t.metadata.copyWith(color: p.loss, fontSize: 10.5))),
          if (msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2), child: Text(msg, style: t.metadata.copyWith(color: p.accent, fontSize: 11))),
          Row(children: [
            TextButton(onPressed: busy ? null : () => _slotAction(slot, 'test'), child: const Text('Test')),
            TextButton(onPressed: busy ? null : () => _slotAction(slot, 'detect'), child: const Text('Detect again')),
            TextButton(onPressed: busy ? null : () => _remove(slot, label), child: Text('Remove', style: TextStyle(color: p.loss))),
          ]),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final t = context.type;
    final guess = _guess(_ctl.text);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('AI KEYS', style: t.metadata.copyWith(letterSpacing: 1)),
        const SizedBox(height: 4),
        Text('Paste a key. The app finds out whose key it is and picks the model by itself. '
            'Main answers first, the others share the work and take over when one runs out of free calls.',
            style: t.metadata.copyWith(height: 1.35, fontSize: 11.5)),
        const SizedBox(height: 10),
        TextField(
          controller: _ctl,
          minLines: 1,
          maxLines: 2,
          autocorrect: false,
          enableSuggestions: false,
          style: TextStyle(color: p.textPrimary, fontSize: 13),
          decoration: InputDecoration(
            hintText: 'Paste key here (Gemini, Groq, Mistral, OpenRouter...)',
            isDense: true,
            border: OutlineInputBorder(borderRadius: BorderRadius.circular(10)),
            suffixIcon: IconButton(icon: const Icon(Icons.content_paste_rounded, size: 18), tooltip: 'Paste', onPressed: _paste),
          ),
        ),
        if (guess.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 4), child: Text('Looks like: $guess', style: t.metadata.copyWith(color: p.accent, fontSize: 11.5))),
        const SizedBox(height: 8),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: (_busy || _ctl.text.trim().isEmpty) ? null : () => _add(),
            style: ElevatedButton.styleFrom(backgroundColor: p.accent, minimumSize: const Size(double.infinity, 42)),
            child: Text(_busy ? 'Checking...' : 'Detect and save', style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800)),
          ),
        ),
        if (_msg.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 6), child: Text(_msg, style: t.metadata.copyWith(color: _msgOk ? p.profit : p.loss, height: 1.35, fontSize: 11.5))),
        if (_needSlot)
          Wrap(
            spacing: 6,
            children: [
              for (final s in _slots)
                ActionChip(label: Text('Replace ${s['label']}'), onPressed: () => _add(slot: (s['slot'] ?? '').toString())),
            ],
          ),
        const SizedBox(height: 12),
        if (!_loaded)
          const Padding(padding: EdgeInsets.all(8), child: Center(child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))))
        else if (_failed)
          Row(children: [
            Expanded(child: Text('Cannot read the keys. Update the backend zip, then retry.', style: t.metadata.copyWith(color: p.warning))),
            TextButton(onPressed: _load, child: const Text('Retry')),
          ])
        else
          for (final s in _slots) _slotRow(p, t, s),
      ],
    );
  }
}
