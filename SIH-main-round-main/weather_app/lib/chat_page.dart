import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_localizations.dart';
import 'chat_models.dart';
import 'weather_service.dart';

class ChatPage extends StatefulWidget {
  final double lat;
  final double lon;
  final String locationName;
  final String persona;
  final String language;

  const ChatPage({
    super.key,
    required this.lat,
    required this.lon,
    required this.locationName,
    required this.persona,
    required this.language,
  });

  @override
  State<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends State<ChatPage> {
  final _chatController = TextEditingController();
  final _scrollController = ScrollController();
  final List<ChatMessage> _messages = [];
  bool _isSending = false;
  bool _isRecording = false;
  bool _isProcessingVoice = false;
  bool _showHistory = false;
  List<Map<String, dynamic>> _chatHistory = [];

  final WeatherService _weatherService = WeatherService();
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  StreamSubscription<RecordState>? _recordSub;
  static const String _kHistoryKey = 'chat_history';

  @override
  void initState() {
    super.initState();
    _messages.add(ChatMessage(
      text: 'Hello! I\'m WeatherGPT. Ask me about the weather, crops, or marine conditions.',
      isUser: false,
      persona: Persona.values.firstWhere(
        (p) => p.backendName == widget.persona,
        orElse: () => Persona.farmer,
      ),
    ));
    _recordSub = _recorder.onStateChanged().listen((state) {
      if (mounted) setState(() => _isRecording = state == RecordState.record);
    });
    _loadChatHistory();
  }

  @override
  void dispose() {
    _recordSub?.cancel();
    _recorder.dispose();
    _player.dispose();
    _chatController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _loadChatHistory() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_kHistoryKey);
    if (raw != null) {
      try {
        final List<dynamic> decoded = jsonDecode(raw);
        setState(() {
          _chatHistory = decoded.cast<Map<String, dynamic>>();
        });
      } catch (e) {
        debugPrint('Chat history load error: $e');
      }
    }
  }

  Future<void> _saveChatSession() async {
    if (_messages.length <= 1) return;
    final prefs = await SharedPreferences.getInstance();
    final session = <String, dynamic>{
      'id': '${widget.lat}_${widget.lon}_${DateTime.now().millisecondsSinceEpoch}',
      'location': widget.locationName,
      'persona': widget.persona,
      'language': widget.language,
      'timestamp': DateTime.now().toIso8601String(),
      'messages': _messages.map((m) => {
        'text': m.text,
        'isUser': m.isUser,
        'persona': m.persona.backendName,
      }).toList(),
    };
    _chatHistory.insert(0, session);
    if (_chatHistory.length > 20) _chatHistory = _chatHistory.sublist(0, 20);
    await prefs.setString(_kHistoryKey, jsonEncode(_chatHistory));
  }

  Future<void> _loadSession(Map<String, dynamic> session) async {
    final msgs = session['messages'] as List<dynamic>? ?? [];
    setState(() {
      _messages.clear();
      for (final m in msgs) {
        _messages.add(ChatMessage(
          text: m['text'] as String,
          isUser: m['isUser'] as bool,
          persona: Persona.values.firstWhere(
            (p) => p.backendName == (m['persona'] as String? ?? 'farmer'),
            orElse: () => Persona.farmer,
          ),
        ));
      }
      _showHistory = false;
    });
    _scrollToBottom();
  }

  Future<void> _clearHistory() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kHistoryKey);
    setState(() => _chatHistory = []);
  }

  @override
  void deactivate() {
    super.deactivate();
    if (_messages.length > 1) {
      _saveChatSession();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _sendMessage(String query) async {
    final text = query.trim();
    if (text.isEmpty || _isSending) return;

    setState(() {
      _messages.add(ChatMessage(text: text, isUser: true, persona: _currentPersona));
      _isSending = true;
      _chatController.clear();
    });
    _scrollToBottom();

    try {
      final result = await _weatherService.fetchExpertChat(
        lat: widget.lat,
        lon: widget.lon,
        persona: widget.persona,
        lang: widget.language,
        query: text,
        locationName: widget.locationName,
        history: _messages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() {
        _messages.add(ChatMessage(text: result.reply, isUser: false, persona: _currentPersona));
      });
      _scrollToBottom();
      await _saveChatSession();
    } catch (e) {
      setState(() {
        _messages.add(ChatMessage(
          text: 'Sorry, I could not process your request. Please try again.',
          isUser: false,
          persona: _currentPersona,
        ));
      });
      _scrollToBottom();
    } finally {
      if (mounted) setState(() => _isSending = false);
    }
  }

  Future<void> _startRecording() async {
    try {
      final hasPerm = await _recorder.hasPermission();
      if (!hasPerm) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Microphone permission denied. Please enable it in settings.')),
          );
        }
        return;
      }
      final dir = await getTemporaryDirectory();
      final path = '${dir.path}/weathergpt_${DateTime.now().millisecondsSinceEpoch}.wav';
      await _recorder.start(
        const RecordConfig(encoder: AudioEncoder.pcm16bits, sampleRate: 16000, numChannels: 1),
        path: path,
      );
    } catch (e) {
      debugPrint('Record start error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not start recording: $e')),
        );
      }
    }
  }

  Future<void> _stopRecordingAndSend() async {
    final path = await _recorder.stop();
    if (path == null || !mounted) return;

    setState(() => _isProcessingVoice = true);
    try {
      final result = await _weatherService.fetchExpertVoice(
        lat: widget.lat,
        lon: widget.lon,
        persona: widget.persona,
        lang: widget.language,
        audioFile: File(path),
        locationName: widget.locationName,
        history: _messages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() {
        _messages.add(ChatMessage(text: result.transcript, isUser: true, persona: _currentPersona));
        _messages.add(ChatMessage(text: result.reply, isUser: false, persona: _currentPersona));
      });
      _scrollToBottom();

      if (result.replyAudioBase64.isNotEmpty) {
        final audioBytes = base64Decode(result.replyAudioBase64);
        final tmp = await getTemporaryDirectory();
        final outPath = '${tmp.path}/advisory_voice.mp3';
        await File(outPath).writeAsBytes(audioBytes);
        await _player.play(DeviceFileSource(outPath));
      }
    } catch (e) {
      debugPrint('Voice error: $e');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Voice failed: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _isProcessingVoice = false);
    }
  }

  Persona get _currentPersona {
    try {
      return Persona.values.firstWhere((p) => p.backendName == widget.persona);
    } catch (_) {
      return Persona.farmer;
    }
  }

  String _personaDescription(Persona persona) {
    final loc = AppLocalizations.of(context);
    switch (persona) {
      case Persona.farmer:
        return loc.farmerDesc;
      case Persona.fisherman:
        return loc.fishermanDesc;
      case Persona.urbanCommuter:
        return loc.urbanCommuterDesc;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final loc = AppLocalizations.of(context);
    final persona = _currentPersona;

    return Scaffold(
      backgroundColor: cs.surface,
      appBar: AppBar(
        backgroundColor: cs.surfaceContainerHigh,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(loc.weatherQuestion, style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
            Text(
              '${widget.locationName} • ${persona.label.toUpperCase()} • ${widget.language.toUpperCase()}',
              style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
            ),
          ],
        ),
        actions: [
          IconButton(
            onPressed: () {
              setState(() => _showHistory = !_showHistory);
            },
            icon: Icon(_showHistory ? Icons.chat_rounded : Icons.history_rounded),
            tooltip: 'Chat History',
          ),
        ],
      ),
      body: Column(
        children: [
          if (_showHistory)
            Container(
              height: 200,
              decoration: BoxDecoration(
                color: cs.surfaceContainerHighest,
                border: Border(bottom: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.3))),
              ),
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        Text('Recent Chats', style: theme.textTheme.titleSmall),
                        const Spacer(),
                        if (_chatHistory.isNotEmpty)
                          TextButton.icon(
                            onPressed: _clearHistory,
                            icon: const Icon(Icons.delete_outline_rounded, size: 18),
                            label: const Text('Clear'),
                          ),
                      ],
                    ),
                  ),
                  Expanded(
                    child: _chatHistory.isEmpty
                        ? Center(child: Text('No chat history yet', style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant)))
                        : ListView.builder(
                            padding: const EdgeInsets.symmetric(horizontal: 12),
                            itemCount: _chatHistory.length,
                            itemBuilder: (ctx, i) {
                              final session = _chatHistory[i];
                              final locName = session['location'] ?? 'Unknown';
                              final personaName = session['persona'] ?? 'general';
                              final time = DateTime.tryParse(session['timestamp'] ?? '') ?? DateTime.now();
                              final timeStr = '${time.day}/${time.month} ${time.hour}:${time.minute.toString().padLeft(2, '0')}';
                              return Card(
                                margin: const EdgeInsets.symmetric(vertical: 4),
                                child: ListTile(
                                  dense: true,
                                  leading: Icon(Icons.chat_bubble_outline_rounded, color: cs.primary),
                                  title: Text('$locName • ${personaName.toUpperCase()}'),
                                  subtitle: Text(timeStr),
                                  onTap: () => _loadSession(session),
                                ),
                              );
                            },
                          ),
                  ),
                ],
              ),
            ),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            decoration: BoxDecoration(
              color: persona.color.withValues(alpha: 0.12),
              border: Border(bottom: BorderSide(color: persona.color.withValues(alpha: 0.3))),
            ),
            child: Row(
              children: [
                Icon(persona.icon, color: persona.color, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _personaDescription(persona),
                    style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurface),
                  ),
                ),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.all(16),
              itemCount: _messages.length,
              itemBuilder: (ctx, i) {
                final msg = _messages[i];
                final isUser = msg.isUser;
                return Align(
                  alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
                  child: Container(
                    margin: const EdgeInsets.symmetric(vertical: 6),
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                    constraints: BoxConstraints(
                      maxWidth: MediaQuery.of(context).size.width * 0.75,
                    ),
                    decoration: BoxDecoration(
                      color: isUser ? cs.primary : persona.color.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.only(
                        topLeft: const Radius.circular(16),
                        topRight: const Radius.circular(16),
                        bottomLeft: Radius.circular(isUser ? 16 : 4),
                        bottomRight: Radius.circular(isUser ? 16 : 4),
                      ),
                    ),
                    child: Text(
                      msg.text,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: isUser ? cs.onPrimary : cs.onSurfaceVariant,
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          Container(
            padding: EdgeInsets.only(
              left: 12,
              right: 12,
              top: 12,
              bottom: MediaQuery.of(context).viewInsets.bottom + 12,
            ),
            decoration: BoxDecoration(
              color: cs.surface,
              border: Border(top: BorderSide(color: cs.outlineVariant.withValues(alpha: 0.3))),
            ),
            child: Row(
              children: [
                IconButton(
                  onPressed: _isProcessingVoice ? null : _isRecording ? _stopRecordingAndSend : _startRecording,
                  icon: _isProcessingVoice
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : Icon(_isRecording ? Icons.mic_rounded : Icons.mic_none_rounded),
                  style: IconButton.styleFrom(backgroundColor: cs.primaryContainer),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: TextField(
                    controller: _chatController,
                    decoration: InputDecoration(
                      hintText: loc.typeMessage,
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                    ),
                    maxLines: 3,
                    minLines: 1,
                    onSubmitted: _isSending ? null : (val) => _sendMessage(val),
                  ),
                ),
                const SizedBox(width: 8),
                FloatingActionButton.small(
                  onPressed: _isSending ? null : () => _sendMessage(_chatController.text),
                  child: _isSending
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.send_rounded, size: 20),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
