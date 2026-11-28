import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../screens/ai_assistant_screen.dart';
import '../theme/app_theme.dart';
import 'owl_pressable.dart';

/// Quick "Ask AI" bottom sheet. Same brain and SAME saved conversation as the
/// full AI Assistant screen (both use POST /api/ai/ask + GET /api/ai/history,
/// and the assistant is fed the same ai_stats numbers the AI tab shows), so
/// whatever you ask here is also in the full chat later.
///
/// [preset] is sent as soon as the sheet opens (used by "ask AI about this
/// trade").
Future<void> showAiChatPopup(BuildContext context, {String? preset}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: context.palette.surfaceElevated,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(AppSpacing.radiusLarge + 4)),
    ),
    builder: (_) => _AiPopup(preset: preset),
  );
}

class _Msg {
  final bool user;
  final String text;
  _Msg(this.user, this.text);
}

class _AiPopup extends StatefulWidget {
  final String? preset;
  const _AiPopup({this.preset});

  @override
  State<_AiPopup> createState() => _AiPopupState();
}

class _AiPopupState extends State<_AiPopup> {
  final _msgs = <_Msg>[];
  final _input = TextEditingController();
  final _scroll = ScrollController();
  bool _sending = false;
  bool _loading = true;

  static final RegExp _cardRe = RegExp(r'\s*\[\[OWLCARD (\{.*?\})\]\]');

  static const _quick = [
    'Ab tak ka total hisaab batao',
    'Strategy kahan maar kha rahi hai?',
    'Sabse zyada loss kahan se aa raha hai?',
    'Kaun se trades skip karne chahiye the?',
  ];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final saved = await context.read<AppProvider>().fetchAiHistory();
    if (!mounted) return;
    setState(() {
      // Last few turns only: this is a quick sheet, the full chat has it all.
      final tail = saved.length > 8 ? saved.sublist(saved.length - 8) : saved;
      _msgs.addAll(tail.map((m) => _Msg('${m['role']}' == 'user', '${m['content']}'.replaceAll(_cardRe, '').trim())));
      _loading = false;
    });
    _toEnd();
    final p = widget.preset;
    if (p != null && p.isNotEmpty) _send(p);
  }

  void _toEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent, duration: AppMotion.base, curve: AppMotion.standard);
      }
    });
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _input.text).trim();
    if (text.isEmpty || _sending) return;
    final provider = context.read<AppProvider>();
    if (provider.settings['ai_enabled'] != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('AI Assistant band hai. Settings mein ON karo.')),
      );
      return;
    }
    AppHaptics.light();
    setState(() {
      _msgs.add(_Msg(true, text));
      _input.clear();
      _sending = true;
    });
    _toEnd();
    final history = _msgs.map((m) => {'role': m.user ? 'user' : 'assistant', 'content': m.text}).toList();
    final reply = await provider.askAi(text, history);
    if (!mounted) return;
    setState(() {
      _sending = false;
      _msgs.add(_Msg(false, reply != null ? reply.replaceAll(_cardRe, '').trim() : '⚠️ ${provider.error ?? 'Kuch gadbad hui.'}'));
    });
    _toEnd();
  }

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final kb = MediaQuery.of(context).viewInsets.bottom;
    return AnimatedPadding(
      duration: AppMotion.base,
      padding: EdgeInsets.only(bottom: kb),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.72,
        child: Column(
          children: [
            const SizedBox(height: 8),
            Container(width: 38, height: 4, decoration: BoxDecoration(color: p.border, borderRadius: BorderRadius.circular(4))),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 10, 8, 6),
              child: Row(
                children: [
                  Icon(Icons.auto_awesome_rounded, size: 18, color: p.purple),
                  const SizedBox(width: 8),
                  Expanded(child: Text('Ask OWL AI', style: context.type.section)),
                  TextButton(
                    onPressed: () {
                      Navigator.of(context).pop();
                      Navigator.of(context).push(MaterialPageRoute(builder: (_) => const AiAssistantScreen()));
                    },
                    child: Text('Full chat', style: TextStyle(color: p.accent, fontWeight: FontWeight.w700)),
                  ),
                ],
              ),
            ),
            Divider(height: 1, color: p.border),
            Expanded(child: _body(context, p)),
            _composer(context, p),
          ],
        ),
      ),
    );
  }

  Widget _body(BuildContext context, AppPalette p) {
    if (_loading) return const Center(child: CircularProgressIndicator(strokeWidth: 2));
    if (_msgs.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text('Apne trades ke baare mein kuch bhi pucho. Jawab sirf aapke asli closed trades ke numbers se aata hai.',
              style: context.type.secondary),
          const SizedBox(height: 14),
          Wrap(spacing: 8, runSpacing: 8, children: [for (final q in _quick) _chip(context, p, q)]),
        ],
      );
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 8),
      itemCount: _msgs.length + (_sending ? 1 : 0),
      itemBuilder: (_, i) {
        if (i >= _msgs.length) {
          return Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Row(children: [
              const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2)),
              const SizedBox(width: 10),
              Text('OWL soch raha hai...', style: context.type.metadata),
            ]),
          );
        }
        final m = _msgs[i];
        return Align(
          alignment: m.user ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 9),
            constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.82),
            decoration: BoxDecoration(
              color: m.user ? p.accent.withOpacity(0.14) : p.surfaceHigher,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: m.user ? p.accent.withOpacity(0.35) : p.border, width: 0.6),
            ),
            child: m.user
                ? Text(m.text, style: context.type.primary.copyWith(fontWeight: FontWeight.w500))
                : Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: aiMdBlocks(m.text, context.type.primary.copyWith(fontWeight: FontWeight.w400, height: 1.4), p.accent),
                  ),
          ),
        );
      },
    );
  }

  Widget _chip(BuildContext context, AppPalette p, String q) => OWLPressable(
        pressedScale: 0.96,
        onTap: () => _send(q),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
            color: p.surfaceHigher,
            borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
            border: Border.all(color: p.border, width: 0.6),
          ),
          child: Text(q, style: context.type.secondary.copyWith(fontWeight: FontWeight.w600)),
        ),
      );

  Widget _composer(BuildContext context, AppPalette p) => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 3,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  style: context.type.primary,
                  decoration: InputDecoration(
                    hintText: 'Kuch bhi pucho...',
                    hintStyle: context.type.metadata,
                    isDense: true,
                    filled: true,
                    fillColor: p.surfaceHigher,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                    border: OutlineInputBorder(borderRadius: BorderRadius.circular(22), borderSide: BorderSide(color: p.border)),
                    enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(22), borderSide: BorderSide(color: p.border)),
                    focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(22), borderSide: BorderSide(color: p.accent)),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              OWLPressable(
                enableHaptics: false,
                onTap: _sending ? null : _send,
                child: Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(color: p.accent, shape: BoxShape.circle),
                  child: const Icon(Icons.arrow_upward_rounded, color: Colors.white, size: 20),
                ),
              ),
            ],
          ),
        ),
      );
}
