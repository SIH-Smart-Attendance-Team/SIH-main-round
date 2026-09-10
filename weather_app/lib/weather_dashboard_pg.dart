import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:file_picker/file_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:connectivity_plus/connectivity_plus.dart';

import 'app_localizations.dart';
import 'chat_models.dart';
import 'settings_page.dart';
import 'location_search_page.dart';
import 'disaster_map_page.dart';
import 'chat_page.dart';
import 'weather_service.dart';
import 'offline_service.dart';

const Map<String, String> kIndicLanguages = {
  'hi': 'हिन्दी (Hindi)',
  'en': 'English',
  'bn': 'বাংলা (Bengali)',
  'ta': 'தமிழ் (Tamil)',
  'te': 'తెలుగు (Telugu)',
  'mr': 'मराठी (Marathi)',
  'gu': 'ગુજરાતી (Gujarati)',
  'kn': 'ಕನ್ನಡ (Kannada)',
  'ml': 'മലയാളം (Malayalam)',
  'pa': 'ਪੰਜਾਬੀ (Punjabi)',
  'or': 'ଓଡ଼ିଆ (Odia)',
  'as': 'অসমীয়া (Assamese)',
  'ur': 'اردو (Urdu)',
  'ne': 'नेपाली (Nepali)',
  'sa': 'संस्कृतम् (Sanskrit)',
  'sd': 'سنڌي (Sindhi)',
  'mai': 'मैथिली (Maithili)',
  'sat': 'ᱥᱟᱱᱛᱟᱲᱤ (Santali)',
  'kok': 'कोंकणी (Konkani)',
  'mni': 'মৈতৈলোন্ (Manipuri)',
  'doi': 'डोगरी (Dogri)',
  'brx': 'बड़ो (Bodo)',
  'ks': 'کٲشُر (Kashmiri)',
};

class WeatherDashboardPage extends StatefulWidget {
  final void Function(String)? onLocaleChanged;
  const WeatherDashboardPage({super.key, this.onLocaleChanged});

  @override
  State<WeatherDashboardPage> createState() => _WeatherDashboardPageState();
}

class _WeatherDashboardPageState extends State<WeatherDashboardPage> {
  Persona _persona = Persona.farmer;
  String _langCode = 'en';
  String _locationLabel = 'New Delhi';
  WeatherData? _weatherData;
  String _condition = '—';
  String _advisoryText = '';
  bool _isLoadingWeather = false;
  bool _isRecording = false;
  bool _isProcessingVoice = false;
  List<Map<String, dynamic>> _alerts = [];
  bool _isLoadingAlerts = false;
  List<DailyForecast> _forecast = [];
  bool _isLoadingForecast = false;
  AgriMetrics? _agriMetrics;
  bool _isLoadingClimate = false;
  MarineMetrics? _marineMetrics;
  List<ChatMessage> _chatMessages = [];
  final _chatController = TextEditingController();
  bool _isSendingMessage = false;
  final ScrollController _chatScrollController = ScrollController();
  bool _isOnline = true;

  late final WeatherService _weatherService;
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  StreamSubscription<RecordState>? _recordSub;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;

  double _lat = 28.61;
  double _lon = 77.21;

  @override
  void initState() {
    super.initState();
    _loadBackendUrl();
    _loadSavedLanguage();
    _chatMessages = [
      ChatMessage(
        text: 'Hello! I\'m WeatherGPT. Ask me about the weather in any Indian language.',
        isUser: false,
        persona: Persona.farmer,
      ),
    ];
    _recordSub = _recorder.onStateChanged().listen((state) {
      if (mounted) setState(() => _isRecording = state == RecordState.record);
    });
    _isOnline = OfflineServices.instance.isOnline;
    _connectivitySub = Connectivity().onConnectivityChanged.listen((results) {
      final online = OfflineServices.instance.isOnline;
      if (mounted && online != _isOnline) {
        setState(() => _isOnline = online);
      }
    });
  }

  Future<void> _loadSavedLanguage() async {
    final prefs = await SharedPreferences.getInstance();
    final savedLang = prefs.getString('app_lang') ?? 'en';
    if (mounted) {
      setState(() => _langCode = savedLang);
    }
  }

  Future<void> _changeLanguage(String langCode) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('app_lang', langCode);
    if (mounted) {
      setState(() => _langCode = langCode);
    }
  }

  @override
  void dispose() {
    _recordSub?.cancel();
    _connectivitySub?.cancel();
    _recorder.dispose();
    _player.dispose();
    _chatController.dispose();
    _chatScrollController.dispose();
    super.dispose();
  }

  Future<void> _loadBackendUrl() async {
    final baseUrl = await BackendConfig.getBaseUrl();
    _weatherService = WeatherService(baseUrl: baseUrl);
    _initLocation();
  }

  Future<void> _initLocation() async {
    final permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      final req = await Geolocator.requestPermission();
      if (req == LocationPermission.denied) {
        _showSnack('Location permission denied. Using default location.');
        _fetchWeatherData();
        return;
      }
    }
    if (permission == LocationPermission.deniedForever) {
      _showSnack('Location permission denied forever. Using default location.');
      _fetchWeatherData();
      return;
    }
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.best,
          timeLimit: Duration(seconds: 15),
        ),
      );
      setState(() {
        _lat = pos.latitude;
        _lon = pos.longitude;
        _locationLabel = '${pos.latitude.toStringAsFixed(4)}, ${pos.longitude.toStringAsFixed(4)}';
      });
      final placeName = await _reverseGeocode(pos.latitude, pos.longitude);
      if (placeName != null && placeName.isNotEmpty) {
        setState(() => _locationLabel = placeName);
      }
      _fetchWeatherData();
    } catch (e) {
      debugPrint('Location error: $e');
      // Fall back to last known position for better accuracy
      try {
        final lastPos = await Geolocator.getLastKnownPosition();
        if (lastPos != null) {
          setState(() {
            _lat = lastPos.latitude;
            _lon = lastPos.longitude;
            _locationLabel = '${lastPos.latitude.toStringAsFixed(4)}, ${lastPos.longitude.toStringAsFixed(4)}';
          });
          final placeName = await _reverseGeocode(lastPos.latitude, lastPos.longitude);
          if (placeName != null && placeName.isNotEmpty) {
            setState(() => _locationLabel = placeName);
          }
        }
      } catch (e2) {
        debugPrint('Last known position error: $e2');
      }
      _fetchWeatherData();
    }
  }

  Future<void> _refreshLocation() async {
    try {
      final pos = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(
          accuracy: LocationAccuracy.best,
          timeLimit: Duration(seconds: 15),
        ),
      );
      setState(() {
        _lat = pos.latitude;
        _lon = pos.longitude;
        _locationLabel = '${pos.latitude.toStringAsFixed(4)}, ${pos.longitude.toStringAsFixed(4)}';
      });
      final placeName = await _reverseGeocode(pos.latitude, pos.longitude);
      if (placeName != null && placeName.isNotEmpty) {
        setState(() => _locationLabel = placeName);
      }
    } catch (e) {
      debugPrint('Refresh location error: $e');
      _showSnack('Could not refresh location. Using last known position.');
    }
    _fetchWeatherData();
  }

  void _openSettings() {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => const SettingsPage(),
        fullscreenDialog: true,
      ),
    );
  }

  Future<String?> _reverseGeocode(double lat, double lon) async {
    try {
      final uri = Uri.parse(
          'https://nominatim.openstreetmap.org/reverse?lat=$lat&lon=$lon&format=json&zoom=10&addressdetails=1');
      final res = await http
          .get(uri, headers: {
            'User-Agent': 'WeatherGPT-Mobile/1.0 (contact@weathergpt.app)',
            'Accept-Language': 'en',
          })
          .timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final address = data['address'] as Map<String, dynamic>?;
        final city = address?['city'] ??
            address?['town'] ??
            address?['village'] ??
            address?['hamlet'] ??
            address?['county'] ??
            data['display_name']?.toString().split(',').first;
        return city?.toString();
      }
    } catch (e) {
      debugPrint('Reverse geocode error: $e');
    }
    return null;
  }

  Future<void> _fetchWeatherData() async {
    _fetchCurrentWeather();
    _fetchAlerts();
    _fetchForecast();
    _fetchClimateMetrics();
  }

  Future<void> _fetchCurrentWeather() async {
    setState(() => _isLoadingWeather = true);
    try {
      final data = await _weatherService.fetchCurrentWeather(_lat, _lon, 'Asia/Kolkata');
      setState(() {
        _weatherData = data;
        _condition = _weatherCodeToLabel(data.weatherCode);
      });
    } catch (e) {
      debugPrint('Weather fetch error: $e');
      _showSnack('Could not load weather data. Check your connection.');
    } finally {
      if (mounted) setState(() => _isLoadingWeather = false);
    }
  }

  Future<void> _fetchAlerts() async {
    setState(() => _isLoadingAlerts = true);
    try {
      final alerts = await _weatherService.fetchAlerts(_lat, _lon);
      setState(() => _alerts = alerts.map((a) => <String, dynamic>{
            'level': a.level,
            'color': a.color,
            'title': a.title,
            'description': a.description,
            'wind_speed_kmh': a.windSpeedKmh,
            'precipitation_mm': a.precipitationMm,
            'issued_at': a.issuedAt,
          }).toList());
    } catch (e) {
      debugPrint('Alerts fetch error: $e');
    } finally {
      if (mounted) setState(() => _isLoadingAlerts = false);
    }
  }

  Future<void> _fetchForecast() async {
    setState(() => _isLoadingForecast = true);
    try {
      final forecast = await _weatherService.fetchForecast(_lat, _lon, 7);
      setState(() => _forecast = forecast);
    } catch (e) {
      debugPrint('Forecast fetch error: $e');
      _showSnack('Could not load forecast data.');
    } finally {
      if (mounted) setState(() => _isLoadingForecast = false);
    }
  }

  Future<void> _fetchClimateMetrics() async {
    setState(() => _isLoadingClimate = true);
    try {
      final agri = await _weatherService.fetchAgriMetrics(_lat, _lon);
      setState(() => _agriMetrics = agri);
    } catch (e) {
      debugPrint('Agri metrics fetch error: $e');
    }
    try {
      final marine = await _weatherService.fetchMarineMetrics(_lat, _lon);
      setState(() => _marineMetrics = marine);
    } catch (e) {
      debugPrint('Marine metrics fetch error: $e');
    }
    if (mounted) {
      setState(() => _isLoadingClimate = false);
    }
  }

  String _weatherCodeToLabel(int? code) {
    if (code == null) return 'Unknown';
    if (code == 0) return 'Clear sky';
    if (code <= 3) return 'Partly cloudy';
    if (code <= 48) return 'Foggy';
    if (code <= 57) return 'Drizzle';
    if (code <= 67) return 'Rain';
    if (code <= 77) return 'Snow';
    if (code <= 82) return 'Showers';
    if (code >= 95) return 'Thunderstorm';
    return 'Cloudy';
  }

  IconData _weatherCodeToIcon(int? code) {
    if (code == null) return Icons.question_mark;
    if (code == 0) return Icons.wb_sunny_rounded;
    if (code <= 3) return Icons.wb_cloudy_rounded;
    if (code <= 48) return Icons.foggy;
    if (code <= 57) return Icons.grain_rounded;
    if (code <= 67) return Icons.beach_access_rounded;
    if (code <= 77) return Icons.ac_unit_rounded;
    if (code <= 82) return Icons.grain_rounded;
    if (code >= 95) return Icons.bolt_rounded;
    return Icons.cloud_rounded;
  }

  List<Color> _getWeatherGradient(int? code) {
    if (code == null) return [const Color(0xFF667eea), const Color(0xFF764ba2)];
    if (code == 0) return [const Color(0xFFFF9A56), const Color(0xFFFFD93D)];
    if (code <= 3) return [const Color(0xFF4facfe), const Color(0xFF00f2fe)];
    if (code <= 48) return [const Color(0xFF8e9aaf), const Color(0xFFc9d6df)];
    if (code <= 57) return [const Color(0xFF4facfe), const Color(0xFF87ceeb)];
    if (code <= 67) return [const Color(0xFF0f4c75), const Color(0xFF3282b8)];
    if (code <= 77) return [const Color(0xFFe0eafc), const Color(0xFFcfdef3)];
    if (code <= 82) return [const Color(0xFF1e3c72), const Color(0xFF2a5298)];
    if (code >= 95) return [const Color(0xFF434343), const Color(0xFF000000)];
    return [const Color(0xFF667eea), const Color(0xFF764ba2)];
  }

  void _scrollChatToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_chatScrollController.hasClients) {
        _chatScrollController.animateTo(
          _chatScrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _startRecording() async {
    final hasPerm = await _recorder.hasPermission();
    if (!hasPerm) {
      _showSnack('Microphone permission denied');
      return;
    }
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/weathergpt_${DateTime.now().millisecondsSinceEpoch}.m4a';
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.aacLc, sampleRate: 16000, numChannels: 1),
      path: path,
    );
  }

  Future<void> _stopRecordingAndSend() async {
    final path = await _recorder.stop();
    if (path == null || !mounted) return;

    setState(() => _isProcessingVoice = true);
    try {
      final result = await _weatherService.fetchExpertVoice(
        lat: _lat,
        lon: _lon,
        persona: _persona.backendName,
        lang: _langCode,
        audioFile: File(path),
        locationName: _locationLabel,
        history: _chatMessages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() => _advisoryText = result.reply);

      _chatMessages.add(ChatMessage(
        text: result.transcript,
        isUser: true,
        persona: _persona,
      ));
      _chatMessages.add(ChatMessage(
        text: result.reply,
        isUser: false,
        persona: _persona,
      ));

      if (result.replyAudioBase64.isNotEmpty) {
        final audioBytes = base64Decode(result.replyAudioBase64);
        final tmp = await getTemporaryDirectory();
        final outPath = '${tmp.path}/advisory_voice.mp3';
        await File(outPath).writeAsBytes(audioBytes);
        await _player.play(DeviceFileSource(outPath));
      } else if (result.transcript.isNotEmpty) {
        _showSnack(result.transcript);
      }
      _scrollChatToBottom();
    } catch (e) {
      debugPrint('Voice pipeline error: $e');
      _showSnack('Could not process voice query');
    } finally {
      if (mounted) setState(() => _isProcessingVoice = false);
    }
  }

  Future<void> _pickAndAnalyzeFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.any,
      allowMultiple: false,
    );
    if (result == null || result.files.isEmpty) return;

    final file = File(result.files.single.path!);
    final fileName = result.files.single.name;

    setState(() => _isProcessingVoice = true);
    try {
      final chatResult = await _weatherService.fetchExpertAnalyze(
        lat: _lat,
        lon: _lon,
        persona: _persona.backendName,
        lang: _langCode,
        file: file,
        prompt: AppLocalizations.of(context).typeMessage,
        history: _chatMessages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() {
        _chatMessages.add(ChatMessage(
          text: '[Uploaded: $fileName] ${AppLocalizations.of(context).typeMessage}',
          isUser: true,
          persona: _persona,
        ));
        _chatMessages.add(ChatMessage(
          text: chatResult.reply,
          isUser: false,
          persona: _persona,
        ));
      });
      _scrollChatToBottom();
    } catch (e) {
      debugPrint('File analysis error: $e');
      _showSnack('Could not analyze file');
    } finally {
      if (mounted) setState(() => _isProcessingVoice = false);
    }
  }

  void _showSnack(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _fetchTextAdvisory(String query) async {
    if (query.trim().isEmpty) return;
    setState(() => _isProcessingVoice = true);
    try {
      final result = await _weatherService.fetchExpertChat(
        lat: _lat,
        lon: _lon,
        persona: _persona.backendName,
        lang: _langCode,
        query: query,
        locationName: _locationLabel,
        history: _chatMessages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() => _advisoryText = result.reply);
      _chatMessages.add(ChatMessage(
        text: query,
        isUser: true,
        persona: _persona,
      ));
      _chatMessages.add(ChatMessage(
        text: result.reply,
        isUser: false,
        persona: _persona,
      ));
      _scrollChatToBottom();
    } catch (e) {
      debugPrint('Text advisory error: $e');
      _showSnack('Could not process text query');
    } finally {
      if (mounted) setState(() => _isProcessingVoice = false);
    }
  }

  Future<void> _sendChatMessage(String query) async {
    final text = query.trim();
    if (text.isEmpty || _isSendingMessage) return;

    setState(() {
      _chatMessages.add(ChatMessage(text: text, isUser: true, persona: _persona));
      _isSendingMessage = true;
      _chatController.clear();
    });

    try {
      final result = await _weatherService.fetchExpertChat(
        lat: _lat,
        lon: _lon,
        persona: _persona.backendName,
        lang: _langCode,
        query: text,
        locationName: _locationLabel,
        history: _chatMessages.map((m) => {
          'role': m.isUser ? 'user' : 'assistant',
          'content': m.text,
        }).toList(),
      );

      setState(() {
        _chatMessages.add(ChatMessage(
          text: result.reply,
          isUser: false,
          persona: _persona,
        ));
      });
      _scrollChatToBottom();
    } catch (e) {
      debugPrint('Chat error: $e');
      setState(() {
        _chatMessages.add(ChatMessage(
          text: 'Sorry, I could not process your request. Please try again.',
          isUser: false,
          persona: _persona));
      });
      _scrollChatToBottom();
    } finally {
      if (mounted) setState(() => _isSendingMessage = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final isWide = MediaQuery.sizeOf(context).width >= 700;
    final maxContentWidth = isWide ? 900.0 : double.infinity;

    return Scaffold(
      backgroundColor: colorScheme.surface,
      body: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: maxContentWidth),
          child: SafeArea(
            child: RefreshIndicator(
              onRefresh: _fetchWeatherData,
              child: CustomScrollView(
                slivers: [
                  if (!_isOnline)
                    SliverToBoxAdapter(
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                        color: colorScheme.errorContainer,
                        child: Row(
                          children: [
                            Icon(Icons.wifi_off_rounded, color: colorScheme.onErrorContainer, size: 18),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(
                                'You are offline. Showing cached data.',
                                style: theme.textTheme.bodySmall?.copyWith(color: colorScheme.onErrorContainer),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  SliverToBoxAdapter(child: _buildHeader(colorScheme, theme)),

                  SliverPadding(
                    padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                    sliver: isWide
                        ? SliverToBoxAdapter(
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(child: _buildPersonaSelector(colorScheme)),
                                const SizedBox(width: 16),
                                Expanded(child: _buildLanguageSelector(colorScheme)),
                              ],
                            ),
                          )
                        : SliverList(
                            delegate: SliverChildListDelegate([
                              _buildPersonaSelector(colorScheme),
                              const SizedBox(height: 12),
                              _buildLanguageSelector(colorScheme),
                            ]),
                          ),
                  ),

                  if (_alerts.isNotEmpty || _isLoadingAlerts)
                    SliverPadding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                      sliver: SliverToBoxAdapter(
                        child: _isLoadingAlerts
                            ? const Center(child: CircularProgressIndicator())
                            : _buildAlertsSection(colorScheme, theme),
                      ),
                    ),

                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                    sliver: SliverToBoxAdapter(
                      child: _buildCurrentWeatherDetails(colorScheme, theme),
                    ),
                  ),

                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                    sliver: SliverToBoxAdapter(
                      child: _isLoadingForecast
                          ? const Center(child: CircularProgressIndicator())
                          : _buildForecastSection(colorScheme, theme),
                    ),
                  ),

                  if (_marineMetrics != null)
                    SliverPadding(
                      padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                      sliver: SliverToBoxAdapter(
                        child: _buildMarineSection(colorScheme, theme),
                      ),
                    ),

                  SliverPadding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 40),
                    sliver: SliverToBoxAdapter(
                      child: _isLoadingClimate
                          ? const Center(child: CircularProgressIndicator())
                          : _buildClimateSection(colorScheme, theme),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _showHelpBottomSheet,
        icon: const Icon(Icons.support_rounded),
        label: Text(AppLocalizations.of(context).helpline),
        backgroundColor: colorScheme.primaryContainer,
      ),
    );
  }

  Widget _buildHeader(ColorScheme cs, ThemeData theme) {
    final gradientColors = _getWeatherGradient(_weatherData?.weatherCode);
    final weatherIcon = _weatherCodeToIcon(_weatherData?.weatherCode);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 28, 24, 36),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: gradientColors,
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: const BorderRadius.vertical(bottom: Radius.circular(32)),
        boxShadow: [
          BoxShadow(
            color: gradientColors[0].withValues(alpha: 0.4),
            blurRadius: 24,
            offset: const Offset(0, 10),
          ),
        ],
      ),
      child: Stack(
        children: [
          // Decorative animated circles for visual depth
          Positioned(
            top: -40,
            right: -30,
            child: Container(
              width: 140,
              height: 140,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white.withValues(alpha: 0.08),
              ),
            ),
          ),
          Positioned(
            bottom: -50,
            left: 100,
            child: Container(
              width: 120,
              height: 120,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white.withValues(alpha: 0.06),
              ),
            ),
          ),
          Positioned(
            top: 60,
            right: 60,
            child: Container(
              width: 50,
              height: 50,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: Colors.white.withValues(alpha: 0.1),
              ),
            ),
          ),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: Colors.white.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.white.withValues(alpha: 0.15)),
                    ),
                    child: Icon(Icons.location_on_rounded, color: Colors.white, size: 20),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      _locationLabel,
                      style: theme.textTheme.titleMedium?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w600,
                        letterSpacing: 0.2,
                      ),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
              if (_isLoadingWeather)
                Container(
                  width: 24,
                  height: 24,
                  padding: const EdgeInsets.all(4),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.2),
                    shape: BoxShape.circle,
                  ),
                  child: const CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                )
              else
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _buildHeaderIconButton(Icons.search_rounded, () async {
                      final result = await Navigator.of(context).push<LocationSearchResult>(
                        MaterialPageRoute(builder: (_) => const LocationSearchPage()),
                      );
                      if (result != null && mounted) {
                        setState(() {
                          _lat = result.latitude;
                          _lon = result.longitude;
                          _locationLabel = result.displayName;
                        });
                        _fetchWeatherData();
                      }
                    }),
                    const SizedBox(width: 4),
                    _buildHeaderIconButton(Icons.refresh_rounded, _refreshLocation),
                    const SizedBox(width: 4),
                    _buildHeaderIconButton(Icons.settings_rounded, () => _openSettings()),
                    const SizedBox(width: 4),
                    _buildHeaderIconButton(Icons.chat_rounded, () async {
                      final result = await Navigator.of(context).push<ChatPage>(
                        MaterialPageRoute(
                          builder: (_) => ChatPage(
                            lat: _lat,
                            lon: _lon,
                            locationName: _locationLabel,
                            persona: _persona.backendName,
                            language: _langCode,
                          ),
                        ),
                      );
                    }),
                    const SizedBox(width: 4),
                    _buildHeaderIconButton(Icons.map_rounded, () async {
                      final result = await Navigator.of(context).push<Map<String, dynamic>?>(
                        MaterialPageRoute(builder: (_) => DisasterMapPage(lat: _lat, lon: _lon)),
                      );
                      if (result != null && mounted) {
                        setState(() {
                          _lat = result['lat'] as double;
                          _lon = result['lon'] as double;
                          _locationLabel = result['name'] as String? ?? _locationLabel;
                        });
                        _fetchWeatherData();
                      }
                    }),
                  ],
                ),
                ],
              ),
              const SizedBox(height: 28),
              Row(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  TweenAnimationBuilder<double>(
                    tween: Tween(begin: 0, end: _weatherData?.temperature?.toDouble() ?? 0),
                    duration: const Duration(milliseconds: 800),
                    curve: Curves.easeOutCubic,
                    builder: (ctx, val, child) {
                      return Text(
                        _weatherData?.temperature != null ? '${val.round()}°' : '--°',
                        style: theme.textTheme.displayLarge?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w300,
                          height: 1.0,
                          fontSize: 88,
                          shadows: [
                            Shadow(
                              color: Colors.black.withValues(alpha: 0.15),
                              blurRadius: 24,
                              offset: const Offset(0, 8),
                            ),
                          ],
                        ),
                      );
                    },
                  ),
                  const SizedBox(width: 18),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.22),
                            borderRadius: BorderRadius.circular(20),
                            border: Border.all(color: Colors.white.withValues(alpha: 0.1)),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(weatherIcon, color: Colors.white, size: 18),
                              const SizedBox(width: 6),
                              Flexible(
                                child: Text(
                                  _condition,
                                  style: theme.textTheme.titleMedium?.copyWith(
                                    color: Colors.white,
                                    fontWeight: FontWeight.w600,
                                  ),
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                            ],
                          ),
                        ),
                        const SizedBox(height: 10),
                        Row(
                          children: [
                            Icon(Icons.thermostat_rounded, color: Colors.white.withValues(alpha: 0.7), size: 14),
                            const SizedBox(width: 4),
                            Text(
                              'Feels like ${_weatherData?.apparentTemperature?.round() ?? _weatherData?.temperature?.round() ?? "--"}°C',
                              style: theme.textTheme.bodyMedium?.copyWith(
                                color: Colors.white.withValues(alpha: 0.85),
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Row(
                          children: [
                            Icon(Icons.water_drop_outlined, color: Colors.white.withValues(alpha: 0.7), size: 14),
                            const SizedBox(width: 4),
                            Text(
                              _formatHumidity(),
                              style: theme.textTheme.bodySmall?.copyWith(
                                color: Colors.white.withValues(alpha: 0.85),
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                  // Large animated weather icon
                  TweenAnimationBuilder<double>(
                    tween: Tween(begin: 0.8, end: 1.0),
                    duration: const Duration(milliseconds: 900),
                    curve: Curves.easeOutBack,
                    builder: (ctx, val, child) {
                      return Transform.scale(
                        scale: val,
                        child: Container(
                          width: 76,
                          height: 76,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: Colors.white.withValues(alpha: 0.18),
                            border: Border.all(color: Colors.white.withValues(alpha: 0.25)),
                            boxShadow: [
                              BoxShadow(
                                color: Colors.white.withValues(alpha: 0.2),
                                blurRadius: 30,
                                spreadRadius: 5,
                              ),
                            ],
                          ),
                          child: Icon(weatherIcon, color: Colors.white, size: 36),
                        ),
                      );
                    },
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildHeaderIconButton(IconData icon, VoidCallback onPressed) {
    return Material(
      color: Colors.white.withValues(alpha: 0.2),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Icon(icon, color: Colors.white, size: 20),
        ),
      ),
    );
  }

  Widget _buildCurrentWeatherDetails(ColorScheme cs, ThemeData theme) {
    return Container(
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: cs.shadow.withValues(alpha: 0.08),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [cs.primaryContainer, cs.primary.withValues(alpha: 0.3)],
                    ),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(Icons.analytics_rounded, color: cs.primary, size: 20),
                ),
                const SizedBox(width: 12),
                Text(
                  'Current Conditions',
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 20),
            // Responsive metric grid using Wrap so cards never overflow
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                _buildWeatherMetricCard(Icons.thermostat_rounded, 'TEMP', _formatTemp(), cs, theme),
                _buildWeatherMetricCard(Icons.water_drop_rounded, 'HUMIDITY', _formatHumidity(), cs, theme),
                _buildWeatherMetricCard(Icons.air_rounded, 'WIND', _formatWind(), cs, theme),
                _buildWeatherMetricCard(Icons.umbrella_rounded, 'PRECIP', _formatPrecip(), cs, theme),
                _buildWeatherMetricCard(Icons.speed_rounded, 'PRESSURE', _formatPressure(), cs, theme),
                _buildWeatherMetricCard(Icons.wb_sunny_rounded, 'UV INDEX', _formatUvIndex(), cs, theme),
                _buildWeatherMetricCard(Icons.visibility_rounded, 'VISIBILITY', _formatVisibility(), cs, theme),
                _buildWeatherMetricCard(Icons.water_drop_outlined, 'DEW POINT', _formatDewPoint(), cs, theme),
                _buildWeatherMetricCard(Icons.cloud_rounded, 'CLOUD', _formatCloudCover(), cs, theme),
                _buildWeatherMetricCard(Icons.air_rounded, 'GUSTS', _formatWindGusts(), cs, theme),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildWeatherMetricCard(IconData icon, String label, String value, ColorScheme cs, ThemeData theme) {
    // Calculate card width responsively based on screen width
    final screenWidth = MediaQuery.sizeOf(context).width;
    final isCompact = screenWidth < 380;
    final cardWidth = isCompact ? (screenWidth - 80) / 3 : 96.0;

    return Container(
      width: cardWidth,
      padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 8),
      decoration: BoxDecoration(
        color: cs.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: cs.primary.withValues(alpha: 0.12), width: 1),
        boxShadow: [
          BoxShadow(
            color: cs.primary.withValues(alpha: 0.04),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: cs.primary.withValues(alpha: 0.1),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: cs.primary, size: 20),
          ),
          const SizedBox(height: 8),
          Text(
            label,
            style: theme.textTheme.labelSmall?.copyWith(
              color: cs.onSurfaceVariant,
              fontWeight: FontWeight.w700,
              fontSize: isCompact ? 9 : 10,
              letterSpacing: 0.5,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: theme.textTheme.titleSmall?.copyWith(
              fontWeight: FontWeight.w800,
              color: cs.onSurface,
              fontSize: isCompact ? 12 : 13,
            ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ],
      ),
    );
  }

  String _personaLocLabel(Persona p) {
    final loc = AppLocalizations.of(context);
    switch (p) {
      case Persona.farmer:
        return loc.farmer;
      case Persona.fisherman:
        return loc.fisherman;
      case Persona.urbanCommuter:
        return loc.urbanCommuter;
    }
  }

  String _personaDesc(Persona p) {
    final loc = AppLocalizations.of(context);
    switch (p) {
      case Persona.farmer:
        return loc.farmerDesc;
      case Persona.fisherman:
        return loc.fishermanDesc;
      case Persona.urbanCommuter:
        return loc.urbanCommuterDesc;
    }
  }

  String _formatTemp() {
    final t = _weatherData?.temperature;
    return t != null ? '${t.round()}°C' : 'N/A';
  }

  String _formatHumidity() {
    final h = _weatherData?.relativeHumidity;
    return h != null ? '${h.round()}%' : 'N/A';
  }

  String _formatWind() {
    final w = _weatherData?.windSpeed;
    return w != null ? '${w.toStringAsFixed(1)} km/h' : 'N/A';
  }

  String _formatPrecip() {
    final p = _weatherData?.precipitation;
    return p != null ? '${p.toStringAsFixed(1)} mm' : 'N/A';
  }

  String _formatPressure() {
    final p = _weatherData?.pressure;
    return p != null ? '${p.toStringAsFixed(1)} hPa' : 'N/A';
  }

  String _formatUvIndex() {
    final uv = _weatherData?.uvIndex;
    if (uv == null) return 'N/A';
    if (uv < 3) return '${uv.toStringAsFixed(1)} Low';
    if (uv < 6) return '${uv.toStringAsFixed(1)} Mod';
    if (uv < 8) return '${uv.toStringAsFixed(1)} High';
    if (uv < 11) return '${uv.toStringAsFixed(1)} V.High';
    return '${uv.toStringAsFixed(1)} Ext';
  }

  String _formatVisibility() {
    final v = _weatherData?.visibility;
    if (v == null) return 'N/A';
    if (v >= 1000) return '${(v / 1000).toStringAsFixed(1)} km';
    return '${v.round()} m';
  }

  String _formatDewPoint() {
    final d = _weatherData?.dewPoint;
    return d != null ? '${d.round()}°C' : 'N/A';
  }

  String _formatCloudCover() {
    final c = _weatherData?.cloudCover;
    return c != null ? '${c.round()}%' : 'N/A';
  }

  String _formatWindGusts() {
    final g = _weatherData?.windGusts;
    return g != null ? '${g.toStringAsFixed(1)} km/h' : 'N/A';
  }

  Widget _buildForecastSection(ColorScheme cs, ThemeData theme) {
    return Container(
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: cs.shadow.withValues(alpha: 0.08),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [cs.primaryContainer, cs.primary.withValues(alpha: 0.3)],
                    ),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(Icons.calendar_month_rounded, color: cs.primary, size: 20),
                ),
                const SizedBox(width: 12),
                Text(
                  '7-Day Forecast',
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
                const Spacer(),
                if (_forecast.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: cs.primary.withValues(alpha: 0.08),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      '${_forecast.length} days',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: cs.primary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 16),
             ListView.separated(
               shrinkWrap: true,
               physics: const NeverScrollableScrollPhysics(),
               itemCount: _forecast.isNotEmpty ? _forecast.length : 3,
               separatorBuilder: (_, _) => Divider(color: cs.outlineVariant.withValues(alpha: 0.2), height: 1),
               itemBuilder: (ctx, i) {
                 if (_forecast.isEmpty) {
                   return Padding(
                     padding: const EdgeInsets.symmetric(vertical: 12),
                     child: Row(
                       children: [
                         Container(
                           padding: const EdgeInsets.all(10),
                           decoration: BoxDecoration(
                             color: cs.surfaceContainerHighest,
                             borderRadius: BorderRadius.circular(12),
                           ),
                           child: Icon(Icons.calendar_today_rounded, color: cs.onSurfaceVariant.withValues(alpha: 0.3), size: 24),
                         ),
                         const SizedBox(width: 14),
                          Text(AppLocalizations.of(context).noForecastData, style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant.withValues(alpha: 0.5))),
                         const Spacer(),
                         Text('-- / --°', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700, color: cs.onSurfaceVariant.withValues(alpha: 0.3))),
                       ],
                     ),
                   );
                 }
                 final day = _forecast[i];
                 final isToday = i == 0;
                 return Padding(
                   padding: const EdgeInsets.symmetric(vertical: 10),
                   child: Row(
                     children: [
                       Container(
                         padding: const EdgeInsets.all(10),
                         decoration: BoxDecoration(
                           color: isToday
                               ? cs.primary.withValues(alpha: 0.15)
                               : cs.primary.withValues(alpha: 0.08),
                           borderRadius: BorderRadius.circular(12),
                         ),
                         child: Icon(
                           _weatherCodeToIcon(day.weatherCode),
                           color: cs.primary,
                           size: 24,
                         ),
                       ),
                       const SizedBox(width: 14),
                       Expanded(
                         child: Column(
                           crossAxisAlignment: CrossAxisAlignment.start,
                           children: [
                             Text(
                               day.date,
                               style: theme.textTheme.bodyMedium?.copyWith(
                                 fontWeight: FontWeight.w600,
                                 color: isToday ? cs.primary : cs.onSurface,
                               ),
                             ),
                             if (isToday) ...[
                               const SizedBox(height: 2),
                               Text(
                                 'Today',
                                 style: theme.textTheme.labelSmall?.copyWith(
                                   color: cs.primary,
                                   fontWeight: FontWeight.w700,
                                 ),
                               ),
                             ],
                           ],
                         ),
                       ),
                       Container(
                         padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                         decoration: BoxDecoration(
                           color: isToday
                               ? cs.primary
                               : cs.surfaceContainerHighest,
                           borderRadius: BorderRadius.circular(20),
                         ),
                         child: Text(
                           '${day.tempMin?.round() ?? "--"}° / ${day.tempMax?.round() ?? "--"}°',
                           style: theme.textTheme.bodyMedium?.copyWith(
                             fontWeight: FontWeight.w800,
                             color: isToday ? cs.onPrimary : cs.primary,
                           ),
                         ),
                       ),
                     ],
                   ),
                 );
               },
             ),
          ],
        ),
      ),
    );
  }

  Widget _buildClimateSection(ColorScheme cs, ThemeData theme) {
    final agri = _agriMetrics;
    final marine = _marineMetrics;
    return Container(
      decoration: BoxDecoration(
        color: cs.surface,
        borderRadius: BorderRadius.circular(24),
        boxShadow: [
          BoxShadow(
            color: cs.shadow.withValues(alpha: 0.08),
            blurRadius: 16,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      colors: [cs.primaryContainer, cs.primary.withValues(alpha: 0.3)],
                    ),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(Icons.eco_rounded, color: cs.primary, size: 20),
                ),
                const SizedBox(width: 12),
                Text(
                  AppLocalizations.of(context).climateEnvironmental,
                  style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ],
            ),
            const SizedBox(height: 20),
            if (agri != null) ...[
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: cs.primary.withValues(alpha: 0.1),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Icon(Icons.agriculture_rounded, color: cs.primary, size: 16),
                  ),
                  const SizedBox(width: 8),
                   Text(AppLocalizations.of(context).agriculturalConditions, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600, color: cs.primary)),
                ],
              ),
              const SizedBox(height: 12),
              _buildClimateMetricsGrid(cs, theme, {
                'ET\u2080 (mm)': agri.et0FaoEvapotranspiration,
                'Soil Temp': agri.soilTemp0To7cm,
                'Soil Moisture': agri.soilMoisture0To7cm,
                'Leaf Wetness': agri.leafWetnessProbability,
              }),
            ],
            if (agri == null && marine == null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Row(
                  children: [
                    Icon(Icons.cloud_off_rounded, color: cs.onSurfaceVariant.withValues(alpha: 0.3), size: 24),
                    const SizedBox(width: 12),
                    Text(
                      'No climate data available',
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: cs.onSurfaceVariant.withValues(alpha: 0.5),
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

  Widget _buildClimateMetricsGrid(ColorScheme cs, ThemeData theme, Map<String, double?> metrics) {
    final entries = metrics.entries.toList();
    return LayoutBuilder(
      builder: (ctx, constraints) {
        final isWide = constraints.maxWidth >= 500;
        return GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: isWide ? 4 : 2,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            // Use mainAxisExtent instead of childAspectRatio to prevent
            // content overlap on small screens (the root cause of the
            // climate section clipping on phones).
            mainAxisExtent: isWide ? 88 : 82,
          ),
          itemCount: entries.length,
          itemBuilder: (ctx, i) {
            final e = entries[i];
            return Container(
              decoration: BoxDecoration(
                color: cs.surfaceContainerLowest,
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: cs.primary.withValues(alpha: 0.15), width: 1),
                boxShadow: [
                  BoxShadow(
                    color: cs.shadow.withValues(alpha: 0.04),
                    blurRadius: 8,
                    offset: const Offset(0, 2),
                  ),
                ],
              ),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 6,
                        height: 6,
                        decoration: BoxDecoration(
                          color: cs.primary,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Text(
                          e.key,
                          style: theme.textTheme.bodySmall?.copyWith(
                            color: cs.onSurfaceVariant,
                            fontSize: 11,
                            fontWeight: FontWeight.w600,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    e.value?.toStringAsFixed(1) ?? '--',
                    style: theme.textTheme.titleMedium?.copyWith(
                      fontWeight: FontWeight.w800,
                      color: cs.primary,
                      fontSize: 18,
                      height: 1.0,
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildPersonaSelector(ColorScheme cs) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(AppLocalizations.of(context).persona, style: TextStyle(color: cs.onSurfaceVariant, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<Persona>(
          segments: Persona.values
              .map((p) => ButtonSegment(
                    value: p,
                    label: Text(_personaLocLabel(p), style: const TextStyle(fontSize: 13)),
                    icon: Icon(p.icon, size: 18),
                  ))
              .toList(),
          selected: {_persona},
          onSelectionChanged: (s) => setState(() => _persona = s.first),
        ),
        const SizedBox(height: 6),
        Text(
          _personaDesc(_persona),
          style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12),
        ),
      ],
    );
  }

  Widget _buildLanguageSelector(ColorScheme cs) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(AppLocalizations.of(context).language, style: TextStyle(color: cs.onSurfaceVariant, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        DropdownMenu<String>(
          initialSelection: _langCode,
          dropdownMenuEntries: kIndicLanguages.entries
              .map((e) => DropdownMenuEntry(value: e.key, label: e.value))
              .toList(),
          onSelected: (v) async {
            if (v != null) {
              await _changeLanguage(v);
              widget.onLocaleChanged?.call(v);
              if (mounted) {
                setState(() => _langCode = v);
              }
            }
          },
          width: double.infinity,
        ),
      ],
    );
  }

  Widget _buildAttachButton(ColorScheme cs) {
    return GestureDetector(
      onTap: _pickAndAnalyzeFile,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: 72,
        height: 72,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: cs.tertiary,
          boxShadow: [
            BoxShadow(
              color: cs.tertiary.withValues(alpha: 0.4),
              blurRadius: 12,
              spreadRadius: 1,
            ),
          ],
        ),
        child: Icon(
          Icons.image_rounded,
          color: Colors.white,
          size: 32,
        ),
      ),
    );
  }

  Widget _buildVoiceButton(ColorScheme cs) {
    final buttonColor = _isRecording
        ? cs.error
        : _isProcessingVoice
            ? cs.secondary
            : cs.primary;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Stack(
          alignment: Alignment.center,
          children: [
            if (_isRecording)
              TweenAnimationBuilder<double>(
                tween: Tween(begin: 1.0, end: 1.4),
                duration: const Duration(milliseconds: 800),
                builder: (ctx, val, child) {
                  return Container(
                    width: (_isRecording ? 96 : 80) * val,
                    height: (_isRecording ? 96 : 80) * val,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: cs.error.withValues(alpha: 0.3 * (1.4 - val) / 0.4),
                    ),
                  );
                },
              ),
            GestureDetector(
              onLongPressStart: (_) => _startRecording(),
              onLongPressEnd: (_) => _stopRecordingAndSend(),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                width: _isRecording ? 96 : 80,
                height: _isRecording ? 96 : 80,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: buttonColor,
                  boxShadow: [
                    BoxShadow(
                      color: buttonColor.withValues(alpha: 0.5),
                      blurRadius: _isRecording ? 30 : 16,
                      spreadRadius: _isRecording ? 6 : 2,
                    ),
                  ],
                ),
                child: _isProcessingVoice
                    ? const Padding(
                        padding: EdgeInsets.all(22),
                        child: CircularProgressIndicator(color: Colors.white, strokeWidth: 3),
                      )
                    : Icon(
                        _isRecording ? Icons.mic_rounded : Icons.mic_none_rounded,
                        color: Colors.white,
                        size: 36,
                      ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),
        Text(
          _isRecording ? 'Release to send' : 'Hold to speak',
          style: TextStyle(
            color: cs.onSurfaceVariant,
            fontSize: 12,
            fontWeight: FontWeight.w500,
          ),
        ),
      ],
    );
  }

  Widget _buildTextAdvisoryButton(ColorScheme cs, ThemeData theme) {
    return SizedBox(
      width: 200,
      child: FilledButton.icon(
        onPressed: _isProcessingVoice
            ? null
            : () async {
                final query = await _showTextQueryDialog(context);
                if (query != null && query.trim().isNotEmpty) {
                  await _fetchTextAdvisory(query);
                }
              },
        icon: _isProcessingVoice
            ? const SizedBox(
                width: 14,
                height: 14,
                child: CircularProgressIndicator(strokeWidth: 1.5, color: Colors.white70),
              )
            : const Icon(Icons.text_format_rounded, size: 18),
        label: Text(AppLocalizations.of(context).textAdvisory),
      ),
    );
  }

  Future<String?> _showTextQueryDialog(BuildContext ctx) async {
    final controller = TextEditingController();
    final personaLabel = _personaLocLabel(_persona);
    final langLabel = kIndicLanguages[_langCode] ?? 'English';
    final loc = AppLocalizations.of(ctx);
    return showDialog<String>(
      context: ctx,
      builder: (dialogCtx) => AlertDialog(
        title: Text(loc.weatherQuestion),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(loc.personaLabel(personaLabel, langLabel)),
              const SizedBox(height: 12),
              TextField(
                controller: controller,
                decoration: InputDecoration(
                  hintText: loc.typeMessage,
                  border: const OutlineInputBorder(),
                ),
                maxLines: 3,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogCtx), child: Text(loc.cancel)),
          TextButton(onPressed: () => Navigator.pop(dialogCtx, controller.text), child: Text(loc.send)),
        ],
      ),
    );
  }

  Widget _buildChatMessages(ColorScheme cs, ThemeData theme) {
    return SizedBox(
      height: 320,
      child: ListView.builder(
        controller: _chatScrollController,
        reverse: false,
        itemCount: _chatMessages.length,
        itemBuilder: (ctx, i) {
          final msg = _chatMessages[i];
          final isUser = msg.isUser;
          return Align(
            alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 4),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.78,
              ),
              decoration: BoxDecoration(
                color: isUser ? cs.primary : cs.surfaceContainerHighest,
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(16),
                  topRight: const Radius.circular(16),
                  bottomLeft: Radius.circular(isUser ? 16 : 4),
                  bottomRight: Radius.circular(isUser ? 4 : 16),
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
    );
  }

  Widget _buildChatInput(ColorScheme cs, ThemeData theme) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: _chatController,
                decoration: InputDecoration(
                  hintText: AppLocalizations.of(context).typeMessage,
                  hintStyle: TextStyle(color: cs.onSurfaceVariant.withValues(alpha: 0.5)),
                  border: const OutlineInputBorder(
                    borderRadius: BorderRadius.all(Radius.circular(24)),
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                ),
                maxLines: 3,
                minLines: 1,
                onSubmitted: _isSendingMessage ? null : (val) => _sendChatMessage(val),
              ),
            ),
            const SizedBox(width: 8),
            FloatingActionButton.small(
              onPressed: _isSendingMessage
                  ? null
                  : () => _sendChatMessage(_chatController.text),
              child: _isSendingMessage
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.send_rounded, size: 20),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildAlertsSection(ColorScheme cs, ThemeData theme) {
    final levelColor = <String, Color>{
      'Green': const Color(0xFF4CAF50),
      'Yellow': const Color(0xFFFFC107),
      'Orange': const Color(0xFFFF9800),
      'Red': const Color(0xFFF44336),
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: _alerts.map((alert) {
        final level = alert['level']?.toString() ?? 'Green';
        final color = levelColor[level] ?? const Color(0xFF4CAF50);
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Container(
            decoration: BoxDecoration(
              color: cs.surface,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: color.withValues(alpha: 0.3), width: 1.5),
              boxShadow: [
                BoxShadow(
                  color: color.withValues(alpha: 0.15),
                  blurRadius: 12,
                  offset: const Offset(0, 4),
                ),
              ],
            ),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: color.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Icon(Icons.warning_rounded, color: color, size: 22),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                alert['title']?.toString() ?? 'Alert',
                                style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                              ),
                            ),
                            Container(
                              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                              decoration: BoxDecoration(
                                color: color.withValues(alpha: 0.15),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                level,
                                style: theme.textTheme.labelSmall?.copyWith(color: color, fontWeight: FontWeight.w700),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        Text(
                          alert['description']?.toString() ?? '',
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: cs.onSurfaceVariant,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _buildAdvisoryCard(ColorScheme cs, ThemeData theme) {
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.auto_awesome_rounded, color: cs.primary, size: 20),
                const SizedBox(width: 8),
                Text(AppLocalizations.of(context).advisory, style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              ],
            ),
            const SizedBox(height: 12),
            Text(_advisoryText, style: theme.textTheme.bodyLarge?.copyWith(height: 1.45)),
          ],
        ),
      ),
    );
  }

  Future<void> _launchWhatsAppHelpline() async {
    final loc = AppLocalizations.of(context);
    final phone = '15556667888';
    final message = Uri.encodeComponent('Hello, I need weather help.');
    final uris = [
      Uri.parse('https://wa.me/$phone?text=$message'),
      Uri.parse('whatsapp://send?phone=$phone&text=$message'),
      Uri.parse('https://api.whatsapp.com/send?phone=$phone&text=$message'),
    ];
    bool launched = false;
    for (final uri in uris) {
      if (await canLaunchUrl(uri)) {
        launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
        if (launched) break;
      }
    }
    if (!launched && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('WhatsApp not available. Please install WhatsApp to use this feature.')),
      );
    }
  }

  Future<void> _launchCallHelpline() async {
    final loc = AppLocalizations.of(context);
    final phone = 'tel:+15556667888';
    final uri = Uri.parse(phone);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    } else {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('${loc.callHelpline} not available')),
        );
      }
    }
  }

  Widget _buildWhatsAppButton(VoidCallback onPressed) {
    return Material(
      color: const Color(0xFF25D366),
      borderRadius: BorderRadius.circular(12),
      child: InkWell(
        onTap: onPressed,
        borderRadius: BorderRadius.circular(12),
        child: const Padding(
          padding: EdgeInsets.all(8),
          child: Icon(Icons.message_rounded, color: Colors.white, size: 20),
        ),
      ),
    );
  }

  Widget _buildMarineSection(ColorScheme cs, ThemeData theme) {
    final marine = _marineMetrics;
    if (marine == null) return const SizedBox.shrink();
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.water_rounded, color: cs.primary, size: 20),
                const SizedBox(width: 8),
                Text(AppLocalizations.of(context).marineConditions, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600, color: cs.primary)),
              ],
            ),
            const SizedBox(height: 12),
            _buildClimateMetricsGrid(cs, theme, {
              'Wave Height': marine.waveHeight,
              'Sea Temp': marine.seaSurfaceTemperature,
              'Wind Gusts': marine.windGusts,
            }),
          ],
        ),
      ),
    );
  }

  void _showHelpBottomSheet() {
    showModalBottomSheet(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(AppLocalizations.of(context).helpline, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.pop(ctx);
                    _launchWhatsAppHelpline();
                  },
                  icon: const Icon(Icons.message_rounded),
                  label: Text(AppLocalizations.of(context).whatsappHelpline),
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF25D366),
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: () {
                    Navigator.pop(ctx);
                    _launchCallHelpline();
                  },
                  icon: const Icon(Icons.phone_rounded),
                  label: Text(AppLocalizations.of(context).callHelpline),
                  style: FilledButton.styleFrom(
                    padding: const EdgeInsets.symmetric(vertical: 14),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
