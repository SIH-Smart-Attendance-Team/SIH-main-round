import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'offline_service.dart';

const String kBackendBaseUrl = String.fromEnvironment(
  'BACKEND_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

const String _kBackendUrlKey = 'backend_url';

class BackendConfig {
  final SharedPreferences _prefs;

  BackendConfig._(this._prefs);

  static Future<BackendConfig> create() async {
    final prefs = await SharedPreferences.getInstance();
    return BackendConfig._(prefs);
  }

  String get baseUrl {
    final saved = _prefs.getString(_kBackendUrlKey);
    if (saved != null && saved.isNotEmpty) {
      return saved;
    }
    return kBackendBaseUrl;
  }

  Future<void> saveBaseUrl(String url) async {
    await _prefs.setString(_kBackendUrlKey, url);
  }

  bool get hasCustomUrl => _prefs.getString(_kBackendUrlKey) != null;

  static Future<String> getBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(_kBackendUrlKey);
    if (saved != null && saved.isNotEmpty) {
      return saved;
    }
    return kBackendBaseUrl;
  }
}

class WeatherService {
  final http.Client _client;
  final OfflineServices offline;
  final String baseUrl;

  WeatherService({http.Client? client, OfflineServices? offline, String? baseUrl})
      : _client = client ?? http.Client(),
        offline = offline ?? OfflineServices.instance,
        baseUrl = baseUrl ?? kBackendBaseUrl;

  Future<http.Response> _get(String path, {Map<String, String>? headers}) {
    final uri = Uri.parse('$baseUrl$path');
    return _client.get(uri, headers: headers);
  }

  Future<http.Response> _post(String path,
      {Map<String, String>? fields, List<http.MultipartFile>? files}) async {
    final uri = Uri.parse('$kBackendBaseUrl$path');
    final request = http.MultipartRequest('POST', uri)
      ..fields.addAll(fields ?? {});
    if (files != null) {
      request.files.addAll(files);
    }
    final streamed = await request.send();
    return http.Response.fromStream(streamed);
  }

  Future<WeatherData> fetchCurrentWeather(
      double lat, double lon, String timezone) async {
    final cacheKey = 'weather:$lat:$lon';
    final cached = offline.getWeatherPreferCache(cacheKey);
    if (cached != null) {
      return WeatherData.fromJson(cached);
    }

    final res = await _get('/api/v1/weather/current?lat=$lat&lon=$lon')
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Weather API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    await offline.cacheWeatherData(cacheKey, data);
    return WeatherData.fromJson(data);
  }

  Future<List<DailyForecast>> fetchForecast(
      double lat, double lon, int days) async {
    final res = await _get(
        '/api/v1/weather/forecast?lat=$lat&lon=$lon&days=$days')
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Forecast API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final daily = data['daily'] as List<dynamic>? ?? [];
    return daily
        .map((e) => DailyForecast.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<AgriMetrics> fetchAgriMetrics(double lat, double lon) async {
    final res = await _get('/api/v1/weather/agri?lat=$lat&lon=$lon')
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Agri API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return AgriMetrics.fromJson(data);
  }

  Future<MarineMetrics> fetchMarineMetrics(double lat, double lon) async {
    final res = await _get('/api/v1/weather/marine?lat=$lat&lon=$lon')
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Marine API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return MarineMetrics.fromJson(data);
  }

  Future<List<AlertItem>> fetchAlerts(double lat, double lon) async {
    final res = await _get('/api/v1/alerts/active?lat=$lat&lon=$lon')
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Alerts API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final alerts = data['active_alerts'] as List<dynamic>? ?? [];
    return alerts.map((e) => AlertItem.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<AdvisoryResponse> fetchVoiceAdvisory(
      double lat, double lon, String lang, String persona, File audioFile) async {
    final res = await _post(
      '/api/v1/voice/advisory',
      fields: {
        'lat': lat.toString(),
        'lon': lon.toString(),
        'lang': lang,
        'persona': persona,
      },
      files: [
        http.MultipartFile.fromBytes(
          'audio',
          await audioFile.readAsBytes(),
          filename: 'query.wav',
        ),
      ],
    ).timeout(const Duration(seconds: 30));
    if (res.statusCode != 200) {
      throw HttpException('Voice advisory API error ${res.statusCode}');
    }
    return AdvisoryResponse.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<AdvisoryResponse> fetchTextAdvisory(
      double lat, double lon, String lang, String persona, String query) async {
    final res = await _post(
      '/api/v1/advisory/text',
      fields: {
        'lat': lat.toString(),
        'lon': lon.toString(),
        'lang': lang,
        'persona': persona,
        'query': query,
      },
    ).timeout(const Duration(seconds: 30));
    if (res.statusCode != 200) {
      throw HttpException('Text advisory API error ${res.statusCode}');
    }
    return AdvisoryResponse.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }
}

class WeatherData {
  final double? temperature;
  final double? relativeHumidity;
  final double? precipitation;
  final double? windSpeed;
  final double? windDirection;
  final int? weatherCode;
  final double? pressure;
  final String? time;
  final String? timezone;

  WeatherData({
    this.temperature,
    this.relativeHumidity,
    this.precipitation,
    this.windSpeed,
    this.windDirection,
    this.weatherCode,
    this.pressure,
    this.time,
    this.timezone,
  });

  factory WeatherData.fromJson(Map<String, dynamic> data) => WeatherData(
        temperature: (data['temperature'] as num?)?.toDouble(),
        relativeHumidity: (data['relative_humidity'] as num?)?.toDouble(),
        precipitation: (data['precipitation'] as num?)?.toDouble(),
        windSpeed: (data['wind_speed'] as num?)?.toDouble(),
        windDirection: (data['wind_direction'] as num?)?.toDouble(),
        weatherCode: data['weather_code'] as int?,
        pressure: (data['pressure'] as num?)?.toDouble(),
        time: data['time'] as String?,
        timezone: data['timezone'] as String?,
      );
}

class DailyForecast {
  final String date;
  final double? tempMax;
  final double? tempMin;
  final double? precipitationSum;
  final double? precipitationProbabilityMax;
  final int? weatherCode;

  DailyForecast({
    required this.date,
    this.tempMax,
    this.tempMin,
    this.precipitationSum,
    this.precipitationProbabilityMax,
    this.weatherCode,
  });

  factory DailyForecast.fromJson(Map<String, dynamic> data) => DailyForecast(
        date: data['date'] as String,
        tempMax: (data['temperature_max'] as num?)?.toDouble(),
        tempMin: (data['temperature_min'] as num?)?.toDouble(),
        precipitationSum: (data['precipitation_sum'] as num?)?.toDouble(),
        precipitationProbabilityMax:
            (data['precipitation_probability_max'] as num?)?.toDouble(),
        weatherCode: data['weather_code'] as int?,
      );
}

class AgriMetrics {
  final double? et0FaoEvapotranspiration;
  final double? soilTemp0To7cm;
  final double? soilTemp7To28cm;
  final double? soilMoisture0To7cm;
  final double? soilMoisture7To28cm;
  final double? leafWetnessProbability;

  AgriMetrics({
    this.et0FaoEvapotranspiration,
    this.soilTemp0To7cm,
    this.soilTemp7To28cm,
    this.soilMoisture0To7cm,
    this.soilMoisture7To28cm,
    this.leafWetnessProbability,
  });

  factory AgriMetrics.fromJson(Map<String, dynamic> data) => AgriMetrics(
        et0FaoEvapotranspiration:
            (data['et0_fao_evapotranspiration'] as num?)?.toDouble(),
        soilTemp0To7cm:
            (data['soil_temperature_0_to_7cm'] as num?)?.toDouble(),
        soilTemp7To28cm:
            (data['soil_temperature_7_to_28cm'] as num?)?.toDouble(),
        soilMoisture0To7cm:
            (data['soil_moisture_0_to_7cm'] as num?)?.toDouble(),
        soilMoisture7To28cm:
            (data['soil_moisture_7_to_28cm'] as num?)?.toDouble(),
        leafWetnessProbability:
            (data['leaf_wetness_probability'] as num?)?.toDouble(),
      );
}

class MarineMetrics {
  final double? waveHeight;
  final double? waveDirection;
  final double? swellWaveHeight;
  final double? swellWaveDirection;
  final double? seaSurfaceTemperature;
  final double? windGusts;

  MarineMetrics({
    this.waveHeight,
    this.waveDirection,
    this.swellWaveHeight,
    this.swellWaveDirection,
    this.seaSurfaceTemperature,
    this.windGusts,
  });

  factory MarineMetrics.fromJson(Map<String, dynamic> data) => MarineMetrics(
        waveHeight: (data['wave_height'] as num?)?.toDouble(),
        waveDirection: (data['wave_direction'] as num?)?.toDouble(),
        swellWaveHeight: (data['swell_wave_height'] as num?)?.toDouble(),
        swellWaveDirection: (data['swell_wave_direction'] as num?)?.toDouble(),
        seaSurfaceTemperature:
            (data['sea_surface_temperature'] as num?)?.toDouble(),
        windGusts: (data['wind_gusts'] as num?)?.toDouble(),
      );
}

class AlertItem {
  final String level;
  final String color;
  final String title;
  final String description;
  final double? windSpeedKmh;
  final double? precipitationMm;
  final String issuedAt;

  AlertItem({
    required this.level,
    required this.color,
    required this.title,
    required this.description,
    this.windSpeedKmh,
    this.precipitationMm,
    required this.issuedAt,
  });

  factory AlertItem.fromJson(Map<String, dynamic> data) => AlertItem(
        level: data['level'] as String? ?? 'Green',
        color: data['color'] as String? ?? '#00AA00',
        title: data['title'] as String? ?? '',
        description: data['description'] as String? ?? '',
        windSpeedKmh: (data['wind_speed_kmh'] as num?)?.toDouble(),
        precipitationMm: (data['precipitation_mm'] as num?)?.toDouble(),
        issuedAt: data['issued_at'] as String? ?? '',
      );
}

class AdvisoryResponse {
  final String? transcript;
  final String nativeAdvisory;
  final String englishAdvisory;
  final String audioBase64;

  AdvisoryResponse({
    this.transcript,
    required this.nativeAdvisory,
    required this.englishAdvisory,
    required this.audioBase64,
  });

  factory AdvisoryResponse.fromJson(Map<String, dynamic> data) =>
      AdvisoryResponse(
        transcript: data['transcript'] as String?,
        nativeAdvisory: data['native_advisory'] as String? ??
            data['english_advisory'] as String? ??
            data['advisory'] as String? ??
            '',
        englishAdvisory: data['english_advisory'] as String? ??
            data['advisory'] as String? ??
            '',
        audioBase64: data['audio_base64'] as String? ?? '',
      );
}
