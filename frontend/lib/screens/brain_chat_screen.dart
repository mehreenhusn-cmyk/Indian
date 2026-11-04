import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_card.dart';

/// Part 77 (Conversational Brain 2 of 2): the chat screen. Read-only: it sends ONE question at a time to /api/v2/brain_chat (Part 76), shows Claude's answer and changes nothing
/// (no setting, no order, no file). The backend gives Claude only saved facts (summary + Ledger, Scalp Lab ledger, the Part 74 check of every coin named); the answer is EVIDENCE first, then a labelled OPINION.
/// No key / quota / offline / too many questions: the backend's plain words are shown in a warning card, never a made-up answer. The chat lives only while this screen is open (nothing is saved on the phone).
/// An answer can take up to about 40 seconds; the Send button waits (one question at a time, so no double Claude call). Dart NOT compiled (the owner's APK build is the proof).
class BrainChatScreen extends StatefulWidget {
  const BrainChatScreen({super.key});

  @override
  State<BrainChatScreen> createState() => _BrainChatScreenState();
}

class _Msg {
  final bool mine;
  final String text;
  final String label;
  final bool warn;
  const _Msg(this.mine, this.text, {this.label = '', this.warn = false});
}

Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};

const _quick = ['What happened on BTC?', 'How are the Brain\'s own trades doing?', 'Which data is still too thin?', 'What did Scalp Lab find so far?'];

class _BrainChatScreenState extends State<BrainChatScreen> {
  final _ctl = TextEditingController();
  final _scroll = ScrollController();
  final List<_Msg> _msgs = [];
  bool _busy = false;

  @override
  void dispose() {
    _ctl.dispose();
    _scroll.dispose();
    super.dispose();
  }

  String _problem(Map<String, dynamic> r) {
    switch (r['state']) {
      case 'off':
        return 'The V2 data API is off. In the owl_data folder make a file named v2_api_enabled that contains 1, then ask again.';
      case 'old':
        return 'This backend does not have the Brain chat route yet. Install the newest zip, restart the backend, then ask again.';
      default:
        return 'Cannot reach the backend right now. Ask again in a moment.';
    }
  }

  void _scrollDown() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      });

  Future<void> _send([String? preset]) async {
    final q = (preset ?? _ctl.text).trim();
    if (q.isEmpty || _busy) return;
    FocusScope.of(context).unfocus();
    _ctl.clear();
    setState(() {
      _msgs.add(_Msg(true, q));
      _busy = true;
    });
    _scrollDown();
    final r = await context.read<AppProvider>().fetchBrainChat(q);
    if (!mounted) return;
    setState(() {
      if (r['ready'] != true) {
        _msgs.add(_Msg(false, r['ready'] == false ? '${r['note'] ?? 'The market store is not ready yet.'}' : _problem(r), warn: true));
      } else if (r['state'] == 'ok') {
        _msgs.add(_Msg(false, '${r['answer'] ?? ''}', label: '${r['label'] ?? ''}'));
      } else {
        _msgs.add(_Msg(false, '${r['note'] ?? 'No answer.'}', warn: true));
      }
      _busy = false;
    });
    _scrollDown();
  }

  Widget _bubble(AppPalette p, _Msg m) {
    if (m.mine) {
      return Align(
        alignment: Alignment.centerRight,
        child: Container(
          constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.8),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(color: p.accent.withOpacity(0.14), borderRadius: BorderRadius.circular(12)),
          child: Text(m.text, style: TextStyle(fontSize: 13.5, color: p.textPrimary)),
        ),
      );
    }
    return OWLCard(
      edge: m.warn ? p.warning : p.purple,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SelectableText(m.text, style: TextStyle(fontSize: 13.5, color: p.textPrimary)),
        if (m.label.isNotEmpty) ...[
          const SizedBox(height: 6),
          Text(m.label, style: TextStyle(fontSize: 11, color: p.textMuted)),
        ],
      ]),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Column(children: [
      Expanded(
        child: _msgs.isEmpty
            ? ListView(padding: const EdgeInsets.all(AppSpacing.l), children: [
                OWLCard(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Ask the Brain', style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: p.textPrimary)),
                    const SizedBox(height: 4),
                    Text('It answers only from your saved data (Ledger, Scalp Lab, the coin\'s saved candles). It gives EVIDENCE first, then its OPINION. It never gives an order and cannot trade. Max 20 questions per hour.',
                        style: TextStyle(fontSize: 12.5, color: p.textSecondary)),
                    const SizedBox(height: 8),
                    Wrap(spacing: 6, runSpacing: 6, children: [for (final q in _quick) ActionChip(label: Text(q, style: const TextStyle(fontSize: 12)), onPressed: () => _send(q))]),
                  ]),
                ),
              ])
            : ListView(
                controller: _scroll,
                padding: const EdgeInsets.all(AppSpacing.l),
                children: [
                  for (final m in _msgs) Padding(padding: const EdgeInsets.only(bottom: AppSpacing.m), child: _bubble(p, m)),
                  if (_busy) const Padding(padding: EdgeInsets.all(12), child: Center(child: CircularProgressIndicator())),
                ],
              ),
      ),
      Padding(
        padding: const EdgeInsets.fromLTRB(AppSpacing.l, 4, AppSpacing.l, AppSpacing.m),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _ctl,
              maxLength: 500,
              minLines: 1,
              maxLines: 3,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: const InputDecoration(hintText: 'Ask about a coin or the Brain', isDense: true, counterText: '', border: OutlineInputBorder()),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(onPressed: _busy ? null : () => _send(), icon: const Icon(Icons.send)),
        ]),
      ),
    ]);
  }
}
