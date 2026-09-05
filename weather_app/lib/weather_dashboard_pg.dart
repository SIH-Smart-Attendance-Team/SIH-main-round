import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import 'settings_page.dart';
import 'weather_service.dart';

enum Persona { farmer, fisherman, urbanCommuter }

extension PersonaX on Persona {
  String get label {
    switch (this) {
      case Persona.farmer:
        return 'Farmer';
      case Persona.fisherman:
        return 'Fisherman';
      case Persona.urbanCommuter:
        return 'Urban Commuter';
    }
  }

  IconData get icon {
    switch (this) {
      case Persona.farmer:
        return Icons.agriculture_rounded;
      case Persona.fisherman:
        return Icons.sailing_rounded;
      case Persona.urbanCommuter:
        return Icons.directions_transit_rounded;
    }
  }
}

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

class ChatMessage {
  final String text;
  final bool isUser;
  final DateTime timestamp;
  final Persona persona;

  ChatMessage({
    required this.text,
    required this.isUser,
    required this.persona,
  }) : timestamp = DateTime.now();
}

class WeatherDashboardPage extends StatefulWidget {
  const WeatherDashboardPage({super.key});

  @override
  State<WeatherDashboardPage> createState() => _WeatherDashboardPageState();
}

class _WeatherDashboardPageState extends State<WeatherDashboardPage> {
  Persona _persona = Persona.farmer;
  String _langCode = 'hi';
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

  late final WeatherService _weatherService;
  final AudioRecorder _recorder = AudioRecorder();
  final AudioPlayer _player = AudioPlayer();
  StreamSubscription<RecordState>? _recordSub;

  double _lat = 28.61;
  double _lon = 77.21;

  @override
  void initState() {
    super.initState();
    _loadBackendUrl();
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
  }

  @override
  void dispose() {
    _recordSub?.cancel();
    _recorder.dispose();
    _player.dispose();
    _chatController.dispose();
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
          accuracy: LocationAccuracy.high,
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
      _fetchWeatherData();
    }
  }

  Future<void> _refreshLocation() async {
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.high,
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

  Future<void> _startRecording() async {
    final hasPerm = await _recorder.hasPermission();
    if (!hasPerm) {
      _showSnack('Microphone permission denied');
      return;
    }
    final dir = await getTemporaryDirectory();
    final path = '${dir.path}/weathergpt_${DateTime.now().millisecondsSinceEpoch}.wav';
    await _recorder.start(
      const RecordConfig(encoder: AudioEncoder.wav, sampleRate: 16000, numChannels: 1),
      path: path,
    );
  }

  Future<void> _stopRecordingAndSend() async {
    final path = await _recorder.stop();
    if (path == null || !mounted) return;

    setState(() => _isProcessingVoice = true);
    try {
      final result = await _weatherService.fetchVoiceAdvisory(
        _lat,
        _lon,
        _langCode,
        _persona.name,
        File(path),
      );

      setState(() => _advisoryText = result.nativeAdvisory);

      if (result.audioBase64.isNotEmpty) {
        final audioBytes = base64Decode(result.audioBase64);
        final tmp = await getTemporaryDirectory();
        final outPath = '${tmp.path}/advisory.mp3';
        await File(outPath).writeAsBytes(audioBytes);
        await _player.play(DeviceFileSource(outPath));
      } else if (result.transcript != null && result.transcript!.isNotEmpty) {
        _showSnack(result.transcript!);
      }
    } catch (e) {
      debugPrint('Voice pipeline error: $e');
      _showSnack('Could not process voice query');
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
      final result = await _weatherService.fetchTextAdvisory(
        _lat,
        _lon,
        _langCode,
        _persona.name,
        query,
      );
      setState(() => _advisoryText = result.nativeAdvisory);

       if (result.audioBase64.isNotEmpty) {
        final audioBytes = base64Decode(result.audioBase64);
        final tmp = await getTemporaryDirectory();
        final outPath = '${tmp.path}/advisory_text.mp3';
        await File(outPath).writeAsBytes(audioBytes);
        await _player.play(DeviceFileSource(outPath));
      }
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
      final result = await _weatherService.fetchTextAdvisory(
        _lat,
        _lon,
        _langCode,
        _persona.name,
        text,
      );

      setState(() {
        _advisoryText = result.nativeAdvisory;
        _chatMessages.add(ChatMessage(
            text: result.nativeAdvisory,
            isUser: false,
            persona: _persona));
      });

      if (result.audioBase64.isNotEmpty) {
        final audioBytes = base64Decode(result.audioBase64);
        final tmp = await getTemporaryDirectory();
        final outPath = '${tmp.path}/advisory_chat.mp3';
        await File(outPath).writeAsBytes(audioBytes);
        await _player.play(DeviceFileSource(outPath));
      }
    } catch (e) {
      debugPrint('Chat error: $e');
      setState(() {
        _chatMessages.add(ChatMessage(
            text: 'Sorry, I could not process your request. Please try again.',
            isUser: false,
            persona: _persona));
      });
    } finally {
      if (mounted) setState(() => _isSendingMessage = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final isWide = MediaQuery.sizeOf(context).width >= 700;

    return Scaffold(
      backgroundColor: colorScheme.surface,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _fetchWeatherData,
          child: CustomScrollView(
            slivers: [
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
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 40),
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

              SliverPadding(
                padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                sliver: SliverToBoxAdapter(
                  child: _isLoadingClimate
                      ? const Center(child: CircularProgressIndicator())
                      : _buildClimateSection(colorScheme, theme),
                ),
              ),

              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 28),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _buildVoiceButton(colorScheme),
                      const SizedBox(height: 16),
                      _buildTextAdvisoryButton(colorScheme, theme),
                    ],
                  ),
                ),
              ),

              if (_advisoryText.isNotEmpty)
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 20),
                  sliver: SliverToBoxAdapter(
                    child: _buildAdvisoryCard(colorScheme, theme),
                  ),
                ),

               if (_chatMessages.length > 1)
                 SliverPadding(
                   padding: const EdgeInsets.fromLTRB(20, 0, 20, 80),
                   sliver: SliverToBoxAdapter(
                     child: _buildChatMessages(colorScheme, theme),
                   ),
                 ),
            ],
          ),
        ),
      ),
      bottomNavigationBar: _buildChatInput(colorScheme, theme),
    );
  }

  Widget _buildHeader(ColorScheme cs, ThemeData theme) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(24, 28, 24, 24),
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [cs.primaryContainer, cs.primary.withValues(alpha: 0.85)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: const BorderRadius.vertical(bottom: Radius.circular(28)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.location_on_rounded, color: cs.onPrimaryContainer, size: 20),
              const SizedBox(width: 6),
              Text(
                _locationLabel,
                style: theme.textTheme.titleMedium?.copyWith(
                  color: cs.onPrimaryContainer,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const Spacer(),
              if (_isLoadingWeather)
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              else
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      icon: Icon(Icons.refresh_rounded, color: cs.onPrimaryContainer),
                      onPressed: _refreshLocation,
                    ),
                    IconButton(
                      icon: Icon(Icons.settings_rounded, color: cs.onPrimaryContainer),
                      onPressed: () => _openSettings(),
                    ),
                  ],
                ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                _weatherData?.temperature != null
                    ? '${_weatherData!.temperature!.round()}°'
                    : '--°',
                style: theme.textTheme.displayLarge?.copyWith(
                  color: cs.onPrimaryContainer,
                  fontWeight: FontWeight.w300,
                  height: 1.0,
                ),
              ),
              const SizedBox(width: 12),
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: Text(
                  _condition,
                  style: theme.textTheme.titleLarge?.copyWith(
                    color: cs.onPrimaryContainer.withValues(alpha: 0.9),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildCurrentWeatherDetails(ColorScheme cs, ThemeData theme) {
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Current Conditions',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 16),
            LayoutBuilder(
              builder: (ctx, constraints) {
                final isWide = constraints.maxWidth >= 500;
                if (isWide) {
                  return Row(
                    mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                    children: [
                   _buildWeatherMetric(Icons.thermostat_rounded, 'TEMP', _formatTemp(), cs, theme),
                   _buildWeatherMetric(Icons.water_drop_rounded, 'HUMIDITY', _formatHumidity(), cs, theme),
                   _buildWeatherMetric(Icons.wind_power_rounded, 'WIND', _formatWind(), cs, theme),
                   _buildWeatherMetric(Icons.beach_access_rounded, 'PRECIP', _formatPrecip(), cs, theme),
                   _buildWeatherMetric(Icons.monitor_rounded, 'PRESSURE', _formatPressure(), cs, theme),
                     ],
                   );
                 }
                 return Wrap(
                   spacing: 12,
                   runSpacing: 12,
                   children: [
                     _buildWeatherMetric(Icons.thermostat_rounded, 'TEMP', _formatTemp(), cs, theme),
                     _buildWeatherMetric(Icons.water_drop_rounded, 'HUMIDITY', _formatHumidity(), cs, theme),
                     _buildWeatherMetric(Icons.wind_power_rounded, 'WIND', _formatWind(), cs, theme),
                     _buildWeatherMetric(Icons.beach_access_rounded, 'PRECIP', _formatPrecip(), cs, theme),
                     _buildWeatherMetric(Icons.monitor_rounded, 'PRESSURE', _formatPressure(), cs, theme),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
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

  Widget _buildWeatherMetric(IconData icon, String label, String value, ColorScheme cs, ThemeData theme) {
    return Column(
      children: [
        Icon(icon, color: cs.primary, size: 28),
        const SizedBox(height: 6),
        Text(label, style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant, fontWeight: FontWeight.w600)),
        Text(value, style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700)),
      ],
    );
  }

  Widget _buildForecastSection(ColorScheme cs, ThemeData theme) {
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '7-Day Forecast',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
             ListView.separated(
               shrinkWrap: true,
               physics: const NeverScrollableScrollPhysics(),
               itemCount: _forecast.isNotEmpty ? _forecast.length : 3,
               separatorBuilder: (_, _) => const Divider(height: 1),
               itemBuilder: (ctx, i) {
                 if (_forecast.isEmpty) {
                   return ListTile(
                      leading: Icon(Icons.calendar_today_rounded, color: cs.onSurfaceVariant.withValues(alpha: 0.3), size: 28),
                     title: Text('No forecast data', style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant.withValues(alpha: 0.5))),
                     trailing: Text('-- / --°', style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700, color: cs.onSurfaceVariant.withValues(alpha: 0.3))),
                   );
                 }
                 final day = _forecast[i];
                 return ListTile(
                   leading: Icon(_weatherCodeToIcon(day.weatherCode), color: cs.primary, size: 28),
                   title: Text(day.date, style: theme.textTheme.bodyMedium),
                   trailing: Text(
                     '${day.tempMin?.round() ?? "--"}° / ${day.tempMax?.round() ?? "--"}°',
                     style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
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
    return Card(
      elevation: 0,
      color: cs.surfaceContainerHighest,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Climate & Environmental',
              style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 16),
            if (agri != null) _buildClimateMetricsGrid(cs, theme, {
              'ET\u2080 (mm)': agri.et0FaoEvapotranspiration,
              'Soil Temp 0-7cm': agri.soilTemp0To7cm,
              'Soil Moisture 0-7cm': agri.soilMoisture0To7cm,
              'Leaf Wetness': agri.leafWetnessProbability,
            }),
            if (marine != null) ...[
              const SizedBox(height: 16),
              Text('Marine Conditions', style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              _buildClimateMetricsGrid(cs, theme, {
                'Wave Height (m)': marine.waveHeight,
                'Sea Surface Temp': marine.seaSurfaceTemperature,
                'Wind Gusts (km/h)': marine.windGusts,
              }),
            ],
            if (agri == null && marine == null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  'No climate data available',
                  style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant.withValues(alpha: 0.5)),
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
            crossAxisSpacing: 12,
            mainAxisSpacing: 12,
            childAspectRatio: isWide ? 3 : 3,
          ),
          itemCount: entries.length,
          itemBuilder: (ctx, i) {
            final e = entries[i];
            return Card(
              elevation: 0,
              color: cs.surface,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(e.key, style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
                    const Spacer(),
                    Text(
                      e.value?.toStringAsFixed(1) ?? '--',
                      style: theme.textTheme.bodyMedium?.copyWith(fontWeight: FontWeight.w700),
                    ),
                  ],
                ),
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
        Text('Persona', style: TextStyle(color: cs.onSurfaceVariant, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        SegmentedButton<Persona>(
          segments: Persona.values
              .map((p) => ButtonSegment(
                    value: p,
                    label: Text(p.label, style: const TextStyle(fontSize: 13)),
                    icon: Icon(p.icon, size: 18),
                  ))
              .toList(),
          selected: {_persona},
          onSelectionChanged: (s) => setState(() => _persona = s.first),
        ),
      ],
    );
  }

  Widget _buildLanguageSelector(ColorScheme cs) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Language', style: TextStyle(color: cs.onSurfaceVariant, fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        DropdownMenu<String>(
          initialSelection: _langCode,
          dropdownMenuEntries: kIndicLanguages.entries
              .map((e) => DropdownMenuEntry(value: e.key, label: e.value))
              .toList(),
          onSelected: (v) {
            if (v != null) setState(() => _langCode = v);
          },
          width: double.infinity,
        ),
      ],
    );
  }

  Widget _buildVoiceButton(ColorScheme cs) {
    return GestureDetector(
      onLongPressStart: (_) => _startRecording(),
      onLongPressEnd: (_) => _stopRecordingAndSend(),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        width: _isRecording ? 96 : 80,
        height: _isRecording ? 96 : 80,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: _isRecording
              ? cs.error
              : _isProcessingVoice
                  ? cs.secondary
                  : cs.primary,
          boxShadow: [
            BoxShadow(
              color: (_isRecording ? cs.error : cs.primary).withValues(alpha: 0.45),
              blurRadius: _isRecording ? 24 : 12,
              spreadRadius: _isRecording ? 4 : 0,
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
        label: const Text('Text Advisory'),
      ),
    );
  }

  Future<String?> _showTextQueryDialog(BuildContext ctx) async {
    final controller = TextEditingController();
    final personaLabel = _persona.label;
    final langLabel = kIndicLanguages[_langCode] ?? 'English';
    return showDialog<String>(
      context: ctx,
      builder: (dialogCtx) => AlertDialog(
        title: const Text('Weather Question'),
        content: SizedBox(
          width: double.maxFinite,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Persona: $personaLabel | Language: $langLabel'),
              const SizedBox(height: 12),
              TextField(
                controller: controller,
                decoration: InputDecoration(
                  hintText: _langCode == 'en' ? 'e.g. Will it rain tomorrow?' : 'আজকের আবহাওয়া কেমন থাকবে?',
                  border: const OutlineInputBorder(),
                ),
                maxLines: 3,
              ),
            ],
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(dialogCtx), child: const Text('Cancel')),
          TextButton(onPressed: () => Navigator.pop(dialogCtx, controller.text), child: const Text('Send')),
        ],
      ),
    );
  }

  Widget _buildChatMessages(ColorScheme cs, ThemeData theme) {
    return ListView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      reverse: true,
      itemCount: _chatMessages.length,
      itemBuilder: (ctx, i) {
        final msg = _chatMessages[_chatMessages.length - 1 - i];
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
                  hintText: kIndicLanguages[_langCode] != null
                      ? 'Type a message...'
                      : 'Type a message...',
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
      'Green': cs.tertiary,
      'Yellow': Colors.yellow.shade700,
      'Orange': Colors.orange.shade700,
      'Red': cs.error,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: _alerts.map((alert) {
        final level = alert['level']?.toString() ?? 'Green';
        final color = levelColor[level] ?? cs.tertiary;
        return Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Card(
            elevation: 0,
            color: cs.surfaceContainerHighest,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.warning_rounded, color: color, size: 24),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          alert['title']?.toString() ?? 'Alert',
                          style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        Text(
                          level,
                          style: theme.textTheme.bodySmall?.copyWith(color: color, fontWeight: FontWeight.w600),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          alert['description']?.toString() ?? '',
                          style: theme.textTheme.bodyMedium,
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
                Text('Advisory', style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              ],
            ),
            const SizedBox(height: 12),
            Text(_advisoryText, style: theme.textTheme.bodyLarge?.copyWith(height: 1.45)),
          ],
        ),
      ),
    );
  }
}
