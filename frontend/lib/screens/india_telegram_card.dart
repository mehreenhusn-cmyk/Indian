import 'package:flutter/material.dart';

import '../services/india_api.dart';
import '../widgets/india_ui.dart';

/// "Telegram signals" section for India Settings. Only India signals come here (crypto has its own Telegram).
/// The Bot Token and Chat ID are saved on the server only; this screen shows them masked.
/// Signals are made from the live broker feed (Fyers), on the 5m or 15m candle you pick here -
/// independent of the timeframe the bot trades on.
class IndiaTelegramCard extends StatefulWidget {
  final IndiaApi api;
  final VoidCallback onChanged;
  const IndiaTelegramCard({super.key, required this.api, required this.onChanged});

  @override
  State<IndiaTelegramCard> createState() => _IndiaTelegramCardState();
}

class _IndiaTelegramCardState extends State<IndiaTelegramCard> {
  final _token = TextEditingController();
  final _chat = TextEditingController();
  Map<String, dynamic> _info = {};
  bool _busy = false;
  String _msg = '';
  bool _msgOk = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _token.dispose();
    _chat.dispose();
    super.dispose();
  }

  void _take(dynamic j) {
    if (j is Map) _info = Map<String, dynamic>.from(j);
  }

  Future<void> _load() async {
    try {
      final j = await widget.api.get('/telegram');
      if (mounted) setState(() => _take(j));
    } catch (e) {
      if (mounted) setState(() { _msg = friendlyError(e); _msgOk = false; });
    }
  }

  Future<void> _run(Future<dynamic> Function() job, {String? okText}) async {
    FocusScope.of(context).unfocus();
    setState(() { _busy = true; _msg = ''; });
    try {
      final j = await job();
      if (!mounted) return;
      setState(() {
        _take(j);
        if (j is Map && j['ok'] != null) {
          _msgOk = j['ok'] == true;
          _msg = '${j['message'] ?? ''}';
        } else if (okText != null) {
          _msgOk = true;
          _msg = okText;
        }
      });
      widget.onChanged();
    } catch (e) {
      if (mounted) setState(() { _msg = friendlyError(e); _msgOk = false; });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _save() async {
    final body = <String, dynamic>{
      if (_token.text.trim().isNotEmpty) 'bot_token': _token.text.trim(),
      if (_chat.text.trim().isNotEmpty) 'chat_id': _chat.text.trim(),
    };
    if (body.isEmpty) {
      setState(() { _msg = 'Type the Bot Token (and Chat ID) first'; _msgOk = false; });
      return;
    }
    await _run(() => widget.api.post('/telegram', body), okText: 'Saved on the server');
    _token.clear();
    _chat.clear();
  }

  Widget _field(TextEditingController c, String label, String hint, {bool secret = false}) => Padding(
        padding: const EdgeInsets.only(top: 10),
        child: TextField(
          controller: c,
          obscureText: secret,
          autocorrect: false,
          enableSuggestions: false,
          decoration: InputDecoration(labelText: label, hintText: hint, isDense: true, border: const OutlineInputBorder()),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final enabled = _info['enabled'] == true;
    final tf = nd(_info['tf']).toInt() == 0 ? 15 : nd(_info['tf']).toInt();
    final tokenSaved = _info['token_saved'] == true;
    final chat = '${_info['chat_id'] ?? ''}';
    final live = _info['data_live'] == true;
    final last = _info['last'] is Map ? Map<String, dynamic>.from(_info['last'] as Map) : <String, dynamic>{};
    final note = '${_info['note'] ?? ''}';
    final check = _info['token_check'] is Map ? Map<String, dynamic>.from(_info['token_check'] as Map) : <String, dynamic>{};
    final checkText = '${check['text'] ?? ''}';
    return ISection(
      title: 'Telegram signals (India)',
      summary: enabled ? 'On · ${tf}m' : 'Off',
      children: [
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          dense: true,
          title: Text('Send India signals', style: IT.body(context)),
          subtitle: Text('Only India signals. Crypto signals use their own Telegram.', style: IT.small(context)),
          value: enabled,
          onChanged: _busy ? null : (v) => _run(() => widget.api.post('/telegram', {'enabled': v})),
        ),
        Padding(padding: const EdgeInsets.only(top: 8, bottom: 6), child: Text('Signal timeframe', style: IT.small(context))),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final m in const [5, 15])
            IChip('${m}m', selected: tf == m, onTap: _busy ? null : () => _run(() => widget.api.post('/telegram', {'tf': m}))),
        ]),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text(
              'Signals are made from the closed ${tf}m candle of the live broker feed. This is separate from the timeframe the bot trades on. '
              'Nothing is sent in demo mode or when the market is closed.',
              style: IT.small(context)),
        ),
        _field(_token, 'Bot Token', tokenSaved ? 'saved: ${_info['token_masked'] ?? ''}' : '123456:ABC...', secret: true),
        _field(_chat, 'Chat ID', chat.isNotEmpty ? 'saved: $chat' : 'tap "Find Chat ID" after /start'),
        const SizedBox(height: 10),
        Wrap(spacing: 8, runSpacing: 8, children: [
          FilledButton(onPressed: _busy ? null : _save, child: const Text('Save')),
          OutlinedButton(
              onPressed: _busy || !tokenSaved ? null : () => _run(() => widget.api.post('/telegram/find_chat')),
              child: const Text('Find Chat ID')),
          OutlinedButton(
              onPressed: _busy || !tokenSaved || chat.isEmpty ? null : () => _run(() => widget.api.post('/telegram/test', {}, const Duration(seconds: 25))),
              child: const Text('Send test message')),
          OutlinedButton(
              onPressed: _busy || !tokenSaved || chat.isEmpty ? null : () => _run(() => widget.api.post('/telegram/demo', {}, const Duration(seconds: 25))),
              child: const Text('Send demo signal')),
        ]),
        Padding(
          padding: const EdgeInsets.only(top: 6),
          child: Text('Chat ID: open your bot in Telegram, send /start once, then tap "Find Chat ID".', style: IT.small(context)),
        ),
        if (tokenSaved && checkText.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(checkText, style: IT.small(context).copyWith(color: check['ok'] == true ? Colors.green : Colors.redAccent)),
          ),
        if (_busy) const Padding(padding: EdgeInsets.only(top: 8), child: LinearProgressIndicator()),
        if (_msg.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(_msg, style: IT.small(context).copyWith(color: _msgOk ? Colors.green : Colors.redAccent)),
          ),
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text(
              [
                live ? 'Data: live ${_info['data_label'] ?? 'broker'}' : 'Data: demo (connect a broker to get signals)',
                if (note.isNotEmpty) note,
                if (last['at'] != null) 'Last send: ${last['ok'] == true ? 'OK' : 'FAILED'} · ${dayTime(last['at'])}${last['ok'] == true || '${last['error'] ?? ''}'.isEmpty ? '' : ' · ${last['error']}'}',
                'Signals sent so far: ${nd(_info['sent_count']).toInt()}',
              ].join('\n'),
              style: IT.small(context)),
        ),
        if (tokenSaved)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: _busy ? null : () => _run(() => widget.api.post('/telegram/forget'), okText: 'Token and Chat ID removed'),
              child: const Text('Remove saved token'),
            ),
          ),
      ],
    );
  }
}
