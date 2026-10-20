import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../providers/app_provider.dart';
import '../theme/app_theme.dart';
import '../widgets/glass_card.dart';
import '../widgets/owl_ambient_background.dart';
import '../widgets/owl_empty_state.dart';
import '../widgets/owl_entrance.dart';
import '../widgets/owl_eye_dot.dart';
import '../widgets/owl_pressable.dart';
import '../widgets/owl_refresh.dart';
import '../widgets/owl_skeleton.dart';

// ---- Minimal markdown for assistant replies (no extra package) ------------
// The model answers with **bold** and "* " / "- " bullets; shown as plain Text
// they appeared as raw asterisks. This turns them into real bold + bullet rows.
final RegExp _boldRe = RegExp(r'\*\*(.+?)\*\*');
final RegExp _tripleRe = RegExp(r'\*\*\*(.+?)\*\*');
final RegExp _bulletRe = RegExp(r'^\s*[*\-•]\s+(.*)$');

List<TextSpan> _inlineSpans(String raw) {
  final s = raw.replaceAllMapped(_tripleRe, (m) => '**${m.group(1)}**'); // "***x**" -> bold x
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
  final String role; // "user" or "assistant"
  final String content;
  _ChatMessage(this.role, this.content);
}

/// Simple chat screen for the in-app AI Assistant - opened from Settings >
/// AI Assistant > "Open Chat", or from the left drawer's quick AI access on
/// any screen. Talks to POST /api/ai/ask (see ai_assistant.py), which
/// itself calls whichever provider (OpenAI/Gemini/Claude) is picked in Settings.
/// The conversation is now PERSISTENT across app restarts (see
/// ai_chat_store.py) - this screen loads it from GET /api/ai/history on
/// open instead of always starting blank, and the backend saves both sides
/// of every turn itself after each successful ask() - this screen doesn't
/// need to explicitly save anything beyond sending the message.
class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key});

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  final List<_ChatMessage> _messages = [];
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  bool _sending = false;
  bool _loadingHistory = true;

  @override
  void initState() {
    super.initState();
    _loadHistory();
  }

  Future<void> _loadHistory() async {
    final provider = Provider.of<AppProvider>(context, listen: false);
    final saved = await provider.fetchAiHistory();
    if (!mounted) return;
    setState(() {
      _messages.clear();
      _messages.addAll(saved.map((m) => _ChatMessage('${m['role']}', '${m['content']}')));
      _loadingHistory = false;
    });
    _scrollToBottom();
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
        title: Text('Clear chat?', style: ctx.type.section),
        content: Text(
          'This deletes the saved conversation from this device and the backend. This cannot be undone.',
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
    await provider.clearAiHistory();
    if (!mounted) return;
    setState(() => _messages.clear());
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
    if (text.isEmpty || _sending) return;
    AppHaptics.light();
    final provider = Provider.of<AppProvider>(context, listen: false);
    final settings = provider.settings;

    if (settings['ai_enabled'] != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('AI Assistant is off — turn it on in Settings first.')),
      );
      return;
    }

    setState(() {
      _messages.add(_ChatMessage('user', text));
      _inputController.clear();
      _sending = true;
    });
    _scrollToBottom();

    final history = _messages
        .map((m) => {'role': m.role, 'content': _cardRe.hasMatch(m.content) ? m.content.replaceAll(_cardRe, '').trim() : m.content})
        .toList();
    final reply = await provider.askAi(text, history);

    setState(() {
      _sending = false;
      if (reply != null) {
        _messages.add(_ChatMessage('assistant', reply));
      } else {
        _messages.add(_ChatMessage(
          'assistant',
          '⚠️ ${provider.error ?? 'Something went wrong.'}',
        ));
      }
    });
    _scrollToBottom();
  }

  /// The backend appends [[OWLCARD {json}]] to summary answers (real numbers
  /// from trade_store). We strip it from the text and draw a stats card.
  static final RegExp _cardRe = RegExp(r'\s*\[\[OWLCARD (\{.*?\})\]\]');

  static const List<String> _suggestions = [
    'How did I do today?',
    'Why were some signals skipped?',
    'Explain my win rate',
    'What should I improve?',
  ];

  // QUICK EXIT - two gestures that never fight the chat's own scrolling:
  //  1) drag the header (title bar / grab pill) DOWN, or
  //  2) swipe RIGHT from the left edge strip (works with 3-button navigation,
  //     where the system back-swipe does not exist).
  double _vDrag = 0;
  double _hDrag = 0;

  void _closeScreen() {
    AppHaptics.light();
    FocusScope.of(context).unfocus();
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Scaffold(
      backgroundColor: p.bg,
      appBar: PreferredSize(
        preferredSize: const Size.fromHeight(kToolbarHeight + 14),
        child: GestureDetector(
          behavior: HitTestBehavior.opaque,
          onVerticalDragStart: (_) => _vDrag = 0,
          onVerticalDragUpdate: (d) => _vDrag += d.delta.dy,
          onVerticalDragEnd: (d) {
            if (_vDrag > 60 || (d.primaryVelocity ?? 0) > 300) _closeScreen();
            _vDrag = 0;
          },
          child: AppBar(
        backgroundColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        titleSpacing: 0,
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(14),
          child: Center(
            child: Container(
              width: 36,
              height: 4,
              margin: const EdgeInsets.only(bottom: 8),
              decoration: BoxDecoration(
                color: p.textMuted.withOpacity(0.45),
                borderRadius: BorderRadius.circular(2),
              ),
            ),
          ),
        ),
        title: Row(
          children: [
            OwlEyeDot(live: !_sending, color: p.owlEye, size: 8),
            const SizedBox(width: AppSpacing.s),
            Text('AI Assistant', style: context.type.section),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Clear chat',
            onPressed: _messages.isEmpty ? null : _confirmClearChat,
            icon: const Icon(Icons.delete_outline),
          ),
        ],
          ),
        ),
      ),
      body: Stack(
        children: [
          const Positioned.fill(child: OwlAmbientBackground()),
          SafeArea(
            child: Column(
              children: [
                Expanded(child: _buildBody(context)),
                if (_sending) _buildTyping(context),
                _buildComposer(context),
              ],
            ),
          ),
          // Left-edge swipe-right strip (translucent: taps still reach the chat).
          Positioned(
            left: 0,
            top: 0,
            bottom: 0,
            width: 28,
            child: GestureDetector(
              behavior: HitTestBehavior.translucent,
              onHorizontalDragStart: (_) => _hDrag = 0,
              onHorizontalDragUpdate: (d) => _hDrag += d.delta.dx,
              onHorizontalDragEnd: (d) {
                if (_hDrag > 70 || (d.primaryVelocity ?? 0) > 450) _closeScreen();
                _hDrag = 0;
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBody(BuildContext context) {
    final p = context.palette;
    if (_loadingHistory) {
      return ListView(
        physics: const NeverScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.l),
        children: const [
          Align(alignment: Alignment.centerLeft, child: OWLSkeleton(width: 220, height: 54, borderRadius: 16)),
          SizedBox(height: AppSpacing.m),
          Align(alignment: Alignment.centerRight, child: OWLSkeleton(width: 160, height: 40, borderRadius: 16)),
          SizedBox(height: AppSpacing.m),
          Align(alignment: Alignment.centerLeft, child: OWLSkeleton(width: 250, height: 70, borderRadius: 16)),
        ],
      );
    }

    if (_messages.isEmpty) {
      return OWLRefresh(
        onRefresh: _loadHistory,
        child: OWLPullEmpty(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const OWLEmptyState(
                icon: Icons.auto_awesome_rounded,
                title: 'Ask OWL anything',
                subtitle: 'Your trades, P&L, skipped signals or how the bot works.',
              ),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.l),
                child: Wrap(
                  alignment: WrapAlignment.center,
                  spacing: AppSpacing.s,
                  runSpacing: AppSpacing.s,
                  children: [
                    for (final q in _suggestions)
                      OWLPressable(
                        pressedScale: 0.96,
                        onTap: () => _send(q),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
                          decoration: BoxDecoration(
                            color: p.surfaceElevated,
                            borderRadius: BorderRadius.circular(AppSpacing.radiusPill),
                            border: Border.all(color: p.border, width: 0.5),
                          ),
                          child: Text(q, style: context.type.secondary.copyWith(color: p.textPrimary)),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      );
    }

    return OWLRefresh(
      onRefresh: _loadHistory,
      child: ListView.builder(
        controller: _scrollController,
        physics: owlPullPhysics,
        padding: const EdgeInsets.all(AppSpacing.m),
        itemCount: _messages.length,
        itemBuilder: (context, i) => OwlEntrance(
          key: ObjectKey(_messages[i]),
          child: _buildBubble(_messages[i]),
        ),
      ),
    );
  }

  Widget _buildTyping(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.l, 0, AppSpacing.l, AppSpacing.s),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: BoxDecoration(
            color: p.surfaceElevated,
            borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
            border: Border.all(color: p.border, width: 0.5),
          ),
          child: const _TypingDots(),
        ),
      ),
    );
  }

  Widget _buildComposer(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.fromLTRB(AppSpacing.m, AppSpacing.xs, AppSpacing.m, AppSpacing.s),
      child: GlassCard(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(AppSpacing.l, 2, 6, 2),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: _inputController,
                  style: context.type.primary,
                  cursorColor: p.accent,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => _send(),
                  decoration: InputDecoration(
                    hintText: 'Message OWL...',
                    hintStyle: context.type.secondary.copyWith(color: p.textMuted),
                    border: InputBorder.none,
                    enabledBorder: InputBorder.none,
                    focusedBorder: InputBorder.none,
                    filled: false,
                    contentPadding: const EdgeInsets.symmetric(vertical: AppSpacing.m),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              OWLPressable(
                enableHaptics: false, // _send() already fires its own haptic
                onTap: _sending ? null : _send,
                child: AnimatedContainer(
                  duration: AppMotion.base,
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: _sending ? p.surfaceHigher : p.accent,
                  ),
                  child: Icon(
                    Icons.arrow_upward_rounded,
                    size: 20,
                    color: _sending ? p.textMuted : Colors.white,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBubble(_ChatMessage m) {
    final p = context.palette;
    final isUser = m.role == 'user';
    String text = m.content;
    Map<String, dynamic>? card;
    final match = _cardRe.firstMatch(m.content);
    if (match != null) {
      text = m.content.replaceAll(_cardRe, '').trim();
      try {
        card = Map<String, dynamic>.from(jsonDecode(match.group(1)!) as Map);
      } catch (_) {
        card = null; // bad JSON -> just show the text
      }
    }
    final bubble = Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.78),
      decoration: BoxDecoration(
        color: isUser ? p.accent.withOpacity(0.22) : p.surfaceElevated,
        borderRadius: BorderRadius.circular(AppSpacing.radiusLarge),
        border: Border.all(
          color: isUser ? p.accent.withOpacity(0.45) : p.border,
          width: 0.5,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (isUser)
            Text(text, style: context.type.primary.copyWith(fontWeight: FontWeight.w400, height: 1.4))
          else
            ...aiMdBlocks(text, context.type.primary.copyWith(fontWeight: FontWeight.w400, height: 1.4), p.accent),
          if (card != null) ...[
            const SizedBox(height: AppSpacing.s),
            _SummaryCard(card),
          ],
        ],
      ),
    );
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      // Long-press any message to copy it.
      child: GestureDetector(
        onLongPress: () {
          AppHaptics.medium();
          Clipboard.setData(ClipboardData(text: _cardRe.hasMatch(m.content) ? m.content.replaceAll(_cardRe, '').trim() : m.content));
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Copied'), duration: Duration(seconds: 1)),
          );
        },
        child: bubble,
      ),
    );
  }
}

/// Three softly pulsing dots shown while the assistant is thinking.
class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots> with SingleTickerProviderStateMixin {
  late final AnimationController _c =
      AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))..repeat();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  double _dotOpacity(double v, int i) {
    final phase = (v * 3 - i).clamp(0.0, 2.0).toDouble();
    final pulse = phase <= 1.0 ? phase : 2.0 - phase;
    return 0.3 + 0.7 * pulse;
  }

  @override
  Widget build(BuildContext context) {
    final color = context.palette.textMuted;
    return AnimatedBuilder(
      animation: _c,
      builder: (context, _) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < 3; i++)
            Padding(
              padding: EdgeInsets.only(right: i == 2 ? 0 : 5),
              child: Opacity(
                opacity: _dotOpacity(_c.value, i),
                child: Container(
                  width: 7,
                  height: 7,
                  decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// Small stats card under an AI summary answer: P&L, trades, win rate.
class _SummaryCard extends StatelessWidget {
  final Map<String, dynamic> d;
  const _SummaryCard(this.d);

  double _n(String k) => (d[k] is num) ? (d[k] as num).toDouble() : 0.0;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final pnl = _n('pnl');
    final pnlColor = pnl >= 0 ? p.profit : p.loss;
    final isOpen = d['kind'] == 'open'; // unrealized P&L card (open trades), not today's closed P&L
    Widget stat(String label, String value, {Color? color}) => Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(label.toUpperCase(), style: context.type.label.copyWith(fontSize: 9.5, letterSpacing: 0.6)),
              const SizedBox(height: 3),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(value, style: AppTypography.numberLarge.copyWith(fontSize: 16, color: color ?? p.textPrimary)),
              ),
            ],
          ),
        );
    return Container(
      padding: const EdgeInsets.all(AppSpacing.m),
      decoration: BoxDecoration(
        color: p.bg.withOpacity(0.35),
        borderRadius: BorderRadius.circular(AppSpacing.radiusMedium),
        border: Border.all(color: pnlColor.withOpacity(0.35), width: 0.8),
      ),
      // 2x2 grid: four columns in one row were too tight on phones
      // ("+147.85" ran into the next number).
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(children: isOpen
              ? [
                  stat('P&L open', '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT', color: pnlColor),
                  stat('Open trades', '${_n('n').toInt()}'),
                ]
              : [
                  stat('P&L today', '${pnl >= 0 ? '+' : ''}${pnl.toStringAsFixed(2)} USDT', color: pnlColor),
                  stat('Trades today', '${_n('trades').toInt()}'),
                ]),
          const SizedBox(height: 10),
          Row(children: isOpen
              ? [
                  stat('In profit', '${_n('green_n').toInt()} / ${_n('n').toInt()}'),
                  stat('Avg ROI (open)', '${_n('avg_roi') >= 0 ? '+' : ''}${_n('avg_roi').toStringAsFixed(1)}%', color: p.accent),
                ]
              : [
                  stat('W / L today', '${_n('wins').toInt()} / ${_n('losses').toInt()}'),
                  stat('Win rate today', '${_n('win_rate').toStringAsFixed(1)}%', color: p.accent),
                ]),
        ],
      ),
    );
  }
}
