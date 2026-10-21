import 'dart:convert';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:image_picker/image_picker.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/owl_ambient_background.dart';
import '../widgets/owl_entrance.dart';
import '../widgets/owl_eye_dot.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_skeleton.dart';

// ---- Minimal markdown for assistant replies --------------------------------
final RegExp _boldRe = RegExp(r'\*\*(.+?)\*\*');
final RegExp _tripleRe = RegExp(r'\*\*\*(.+?)\*\*');
final RegExp _bulletRe = RegExp(r'^\s*[*\-•]\s+(.*)$');

List<TextSpan> _inlineSpans(String raw) {
  final s = raw.replaceAllMapped(_tripleRe, (m) => '**${m.group(1)}**');
  final spans = <TextSpan>[];
  var last = 0;
  for (final m in _boldRe.allMatches(s)) {
    if (m.start > last) spans.add(TextSpan(text: s.substring(last, m.start).replaceAll('**', '')));
    spans.add(TextSpan(text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w700)));
    last = m.end;
  }
  if (last < s.length) spans.add(TextSpan(text: s.substring(last).replaceAll('**', '')));
  return spans;
}

List<Widget> aiMdBlocks(String text, TextStyle base, Color bulletColor) {
  final out = <Widget>[];
  var prevBlank = false;
  for (final raw in text.split('\n')) {
    final line = raw.trimRight();
    if (line.trim().isEmpty) {
      if (!prevBlank && out.isNotEmpty) out.add(const SizedBox(height: 6));
      prevBlank = true;
      continue;
    }
    prevBlank = false;
    final b = _bulletRe.firstMatch(line);
    if (b != null) {
      out.add(Padding(
        padding: const EdgeInsets.only(left: 2, top: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.only(right: 7),
              child: Text('•', style: base.copyWith(color: bulletColor, fontWeight: FontWeight.w700)),
            ),
            Expanded(child: Text.rich(TextSpan(style: base, children: _inlineSpans(b.group(1)!)))),
          ],
        ),
      ));
    } else {
      out.add(Text.rich(TextSpan(
        style: base,
        children: _inlineSpans(line.replaceFirst(RegExp(r'^#+\s*'), '')),
      )));
    }
  }
  return out;
}

class _ChatMessage {
  final String role;
  final String content;
  final Uint8List? imageBytes;
  _ChatMessage(this.role, this.content, {this.imageBytes});
}

/// Multi-chat AI Assistant: hamburger history, modes (Trades / Backend / App & UI / General),
/// photo attach for UI feedback. Talks to POST /api/ai/ask + multi-chat store.
class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key});

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  final List<_ChatMessage> _messages = [];
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  bool _sending = false;
  bool _loadingHistory = true;
  String? _chatId;
  String _mode = 'general';
  List<Map<String, dynamic>> _chats = [];
  Uint8List? _pendingImage;
  String? _pendingImageB64;

  static const _modes = [
    ('general', 'General'),
    ('trades', 'Trades'),
    ('backend', 'Backend & speed'),
    ('app_ui', 'App & UI'),
  ];

  @override
  void initState() {
    super.initState();
    _loadBundle();
  }

  Future<void> _loadBundle({String? chatId}) async {
    final provider = Provider.of<AppProvider>(context, listen: false);
    final data = await provider.fetchAiHistoryBundle(chatId: chatId);
    if (!mounted) return;
    final msgs = (data['messages'] as List?) ?? [];
    setState(() {
      _messages
        ..clear()
        ..addAll(msgs.map((m) {
          final map = Map<String, dynamic>.from(m as Map);
          return _ChatMessage('${map['role']}', '${map['content']}');
        }));
      _chats = List<Map<String, dynamic>>.from(
        ((data['chats'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)),
      );
      _chatId = (data['active'] ?? chatId)?.toString();
      _mode = (data['mode'] ?? 'general').toString();
      _loadingHistory = false;
    });
    _scrollToBottom();
  }

  /// Close the chat drawer only when it is really open. (Before, a mode chip started a new chat and then
  /// popped the whole screen, which threw you back to the Dashboard.)
  void _closeDrawerIfOpen() {
    if (mounted && _scaffoldKey.currentState?.isDrawerOpen == true) Navigator.of(context).pop();
  }

  Future<void> _newChat(String mode) async {
    final provider = Provider.of<AppProvider>(context, listen: false);
    final created = await provider.createAiChat(mode: mode);
    if (created == null || !mounted) return;
    await provider.setActiveAiChat('${created['id']}');
    setState(() {
      _chatId = '${created['id']}';
      _mode = mode;
      _messages.clear();
      _pendingImage = null;
      _pendingImageB64 = null;
    });
    await _loadBundle(chatId: _chatId);
    _closeDrawerIfOpen();
  }

  Future<void> _switchChat(String id) async {
    final provider = Provider.of<AppProvider>(context, listen: false);
    await provider.setActiveAiChat(id);
    setState(() => _loadingHistory = true);
    await _loadBundle(chatId: id);
    _closeDrawerIfOpen();
  }

  Future<void> _deleteChat(String id) async {
    final provider = Provider.of<AppProvider>(context, listen: false);
    await provider.deleteAiChat(id);
    await _loadBundle();
  }

  Future<void> _confirmClearChat() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: ctx.palette.surfaceElevated,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
          side: BorderSide(color: ctx.palette.border, width: 0.5),
        ),
        title: Text('Clear this chat?', style: ctx.type.section),
        content: Text(
          'Deletes messages in the current conversation only. Other chats stay.',
          style: ctx.type.secondary,
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: Text('Clear', style: TextStyle(color: ctx.palette.loss)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final provider = Provider.of<AppProvider>(context, listen: false);
    await provider.clearAiHistory(chatId: _chatId);
    if (!mounted) return;
    setState(() => _messages.clear());
  }

  Future<void> _pickImage() async {
    try {
      final picker = ImagePicker();
      final file = await picker.pickImage(source: ImageSource.gallery, maxWidth: 1280, imageQuality: 75);
      if (file == null) return;
      final bytes = await file.readAsBytes();
      if (bytes.length > 2 * 1024 * 1024) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Image too large (max ~2 MB after compress).')),
        );
        return;
      }
      setState(() {
        _pendingImage = bytes;
        _pendingImageB64 = base64Encode(bytes);
      });
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not pick image: $e')),
      );
    }
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: AppMotion.base,
          curve: AppMotion.standard,
        );
      }
    });
  }

  Future<void> _send([String? preset]) async {
    final text = (preset ?? _inputController.text).trim();
    if ((text.isEmpty && _pendingImageB64 == null) || _sending) return;
    HapticFeedback.lightImpact();
    final provider = Provider.of<AppProvider>(context, listen: false);
    final settings = provider.settings;

    if (settings['ai_enabled'] != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('AI Assistant is off. Turn it on in Settings.')),
      );
      return;
    }

    final display = text.isEmpty ? '[Screenshot attached]' : text;
    final img = _pendingImage;
    final b64 = _pendingImageB64;

    setState(() {
      _messages.add(_ChatMessage('user', display, imageBytes: img));
      _inputController.clear();
      _pendingImage = null;
      _pendingImageB64 = null;
      _sending = true;
    });
    _scrollToBottom();

    final history = _messages
        .where((m) => m.role == 'user' || m.role == 'assistant')
        .map((m) => {'role': m.role, 'content': m.content})
        .toList();
    // drop the message we just added from history payload (server stores after reply)
    if (history.isNotEmpty) history.removeLast();

    final reply = await provider.askAi(
      display,
      history,
      chatId: _chatId,
      mode: _mode,
      imageB64: b64,
    );
    if (!mounted) return;
    setState(() {
      _sending = false;
      if (reply != null) {
        _messages.add(_ChatMessage('assistant', reply));
      } else {
        _messages.add(_ChatMessage(
          'assistant',
          provider.error ?? 'No reply. Check AI key / network in Settings.',
        ));
      }
    });
    _scrollToBottom();
    // refresh chat list titles
    final data = await provider.fetchAiHistoryBundle(chatId: _chatId);
    if (!mounted) return;
    setState(() {
      _chats = List<Map<String, dynamic>>.from(
        ((data['chats'] as List?) ?? []).map((e) => Map<String, dynamic>.from(e as Map)),
      );
      _chatId = (data['active'] ?? _chatId)?.toString();
    });
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: p.bg,
      drawer: _buildDrawer(p),
      body: Stack(
        children: [
        const Positioned.fill(child: OwlAmbientBackground()),
        SafeArea(
          child: Column(
            children: [
              AppBar(
                backgroundColor: Colors.transparent,
                elevation: 0,
                leading: IconButton(
                  icon: const Icon(Icons.menu),
                  onPressed: () => _scaffoldKey.currentState?.openDrawer(),
                  tooltip: 'Chats',
                ),
                title: Row(
                  children: [
                    Text('AI', style: context.type.hero.copyWith(fontSize: 20)),
                    const SizedBox(width: 8),
                    OwlEyeDot(live: !_sending, color: p.owlEye, size: 8),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        _modeLabel(_mode),
                        style: context.type.metadata,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
                actions: [
                  IconButton(
                    icon: const Icon(Icons.delete_outline),
                    onPressed: _messages.isEmpty ? null : _confirmClearChat,
                    tooltip: 'Clear this chat',
                  ),
                ],
              ),
              // Mode chips
              SizedBox(
                height: 40,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  children: [
                    for (final m in _modes)
                      Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: ChoiceChip(
                          label: Text(m.$2, style: TextStyle(fontSize: 12)),
                          selected: _mode == m.$1,
                          onSelected: (_) async {
                            if (_messages.isEmpty) {
                              setState(() => _mode = m.$1);
                            } else {
                              await _newChat(m.$1);
                            }
                          },
                        ),
                      ),
                  ],
                ),
              ),
              Expanded(
                child: _loadingHistory
                    ? const Center(child: CircularProgressIndicator(strokeWidth: 2))
                    : _buildBody(p),
              ),
              if (_pendingImage != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
                  child: Row(
                    children: [
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: Image.memory(_pendingImage!, height: 56, width: 56, fit: BoxFit.cover),
                      ),
                      const SizedBox(width: 8),
                      const Expanded(child: Text('Screenshot attached', style: TextStyle(fontSize: 12))),
                      IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: () => setState(() {
                          _pendingImage = null;
                          _pendingImageB64 = null;
                        }),
                      ),
                    ],
                  ),
                ),
              _buildInputBar(p),
            ],
          ),
        ),
        ],
      ),
    );
  }

  String _modeLabel(String m) {
    for (final x in _modes) {
      if (x.$1 == m) return x.$2;
    }
    return 'General';
  }

  Widget _buildDrawer(AppPalette p) {
    return Drawer(
      backgroundColor: p.surfaceElevated,
      child: SafeArea(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text('Chats', style: context.type.section),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: FilledButton.icon(
                onPressed: () => _newChat(_mode),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('New chat'),
              ),
            ),
            const SizedBox(height: 8),
            Expanded(
              child: ListView.builder(
                itemCount: _chats.length,
                itemBuilder: (ctx, i) {
                  final c = _chats[i];
                  final id = '${c['id']}';
                  final active = id == _chatId || c['active'] == true;
                  return ListTile(
                    selected: active,
                    title: Text('${c['title'] ?? 'Chat'}', maxLines: 1, overflow: TextOverflow.ellipsis),
                    subtitle: Text('${c['mode'] ?? 'general'} · ${c['n_messages'] ?? 0} msgs',
                        style: context.type.metadata.copyWith(fontSize: 11)),
                    onTap: () => _switchChat(id),
                    trailing: IconButton(
                      icon: Icon(Icons.delete_outline, size: 18, color: p.loss),
                      onPressed: () => _deleteChat(id),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildBody(AppPalette p) {
    if (_messages.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Text(
              'Ask about trades, speed, or UI.\nModes keep context focused. Attach a screenshot for App & UI feedback.',
              style: context.type.secondary.copyWith(height: 1.4),
            ),
          ),
          const SizedBox(height: 16),
          for (final q in _suggestionsForMode())
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: OWLPressable(
                onTap: () => _send(q),
                child: Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: context.palette.surfaceElevated,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: context.palette.border.withOpacity(0.5)),
                  ),
                  child: Text(q, style: context.type.secondary),
                ),
              ),
            ),
        ],
      );
    }
    return ListView.builder(
      controller: _scrollController,
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      itemCount: _messages.length + (_sending ? 1 : 0),
      itemBuilder: (ctx, i) {
        if (_sending && i == _messages.length) {
          return Padding(
            padding: const EdgeInsets.all(8),
            child: Text('Thinking…', style: context.type.metadata),
          );
        }
        return _buildBubble(_messages[i]);
      },
    );
  }

  List<String> _suggestionsForMode() {
    switch (_mode) {
      case 'trades':
        return ['What is my open P&L right now?', 'Summarise today\'s closed trades', 'Any risk flags on open positions?'];
      case 'backend':
        return ['Where is the app slow or freezing?', 'Is REST burning mobile data?', 'Why did the backend restart?'];
      case 'app_ui':
        return ['Suggest a cleaner Results card layout', 'What should the Vision tab show first?', 'Review this screenshot (attach one)'];
      default:
        return ['How is the bot doing today?', 'Is Vision AI helping vs the bur?', 'Any freezes or data leak?'];
    }
  }

  Widget _buildBubble(_ChatMessage m) {
    final p = context.palette;
    final mine = m.role == 'user';
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.85),
        decoration: BoxDecoration(
          color: mine ? p.accent.withOpacity(0.15) : p.surfaceElevated,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: p.border.withOpacity(0.5)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (m.imageBytes != null) ...[
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.memory(m.imageBytes!, height: 120, fit: BoxFit.cover),
              ),
              const SizedBox(height: 8),
            ],
            if (mine)
              Text(m.content, style: context.type.secondary.copyWith(color: p.textPrimary))
            else
              ...aiMdBlocks(m.content, context.type.secondary.copyWith(color: p.textPrimary, height: 1.35), p.accent),
          ],
        ),
      ),
    );
  }

  Widget _buildInputBar(AppPalette p) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(10, 4, 10, 10),
      child: Row(
        children: [
          IconButton(
            icon: const Icon(Icons.image_outlined),
            tooltip: 'Attach screenshot',
            onPressed: _sending ? null : _pickImage,
          ),
          Expanded(
            child: TextField(
              controller: _inputController,
              minLines: 1,
              maxLines: 4,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _send(),
              decoration: InputDecoration(
                hintText: 'Message…',
                filled: true,
                fillColor: p.surfaceElevated,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
                contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              ),
            ),
          ),
          const SizedBox(width: 6),
          IconButton.filled(
            onPressed: _sending ? null : () => _send(),
            icon: const Icon(Icons.send_rounded, size: 20),
          ),
        ],
      ),
    );
  }
}
