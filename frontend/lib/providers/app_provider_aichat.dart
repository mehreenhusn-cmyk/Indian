part of 'app_provider.dart';

/// AI Assistant chat calls (backend /api/ai/history, /api/ai/chats/*).
/// Moved out of app_provider.dart (NEXT-5a). Same code, same names: callers still write provider.xxx().
/// An extension in a part file sees every private member of AppProvider (same library).
extension AppProviderAiChat on AppProvider {
  /// Restores the saved AI Assistant conversation from the backend (see
  /// ai_chat_store.py) - called once when the chat screen opens, so a
  /// previous conversation survives an app restart instead of starting
  /// blank every time.
  Future<List<Map<String, dynamic>>> fetchAiHistory({String? chatId}) async {
    try {
      final uri = chatId == null || chatId.isEmpty
          ? _u('/api/ai/history')
          : _u('/api/ai/history').replace(queryParameters: {'chat_id': chatId});
      final res = await _getResilient(uri);
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return List<Map<String, dynamic>>.from(
          (data['messages'] as List<dynamic>? ?? []).map((m) => Map<String, dynamic>.from(m as Map)),
        );
      }
    } catch (_) {}
    return [];
  }

  /// Full multi-chat payload: messages + chat list + active id + mode.
  Future<Map<String, dynamic>> fetchAiHistoryBundle({String? chatId}) async {
    try {
      final uri = chatId == null || chatId.isEmpty
          ? _u('/api/ai/history')
          : _u('/api/ai/history').replace(queryParameters: {'chat_id': chatId});
      final res = await _getResilient(uri);
      if (res.statusCode == 200) {
        return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
      }
    } catch (_) {}
    return {'messages': [], 'chats': [], 'active': null, 'mode': 'general'};
  }

  Future<bool> clearAiHistory({String? chatId}) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/history/clear'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<Map<String, dynamic>?> createAiChat({String mode = 'general', String title = ''}) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'mode': mode, 'title': title}),
      );
      if (res.statusCode == 200) return Map<String, dynamic>.from(jsonDecode(res.body) as Map);
    } catch (_) {}
    return null;
  }

  Future<bool> setActiveAiChat(String chatId) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/active'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> deleteAiChat(String chatId) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/delete'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> renameAiChat(String chatId, String title) async {
    try {
      final res = await _postResilient(
        _u('/api/ai/chats/rename'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'chat_id': chatId, 'title': title}),
      );
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

}
