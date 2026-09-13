import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'offline_service.dart';

const String kBackendBaseUrl = String.fromEnvironment(
  'BACKEND_URL',
  defaultValue: 'http://10.142.255.156:8000',
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

const String kOpenMeteoUrl = 'https://api.open-meteo.com/v1/forecast';
const String kOpenMeteoMarineUrl = 'https://marine-api.open-meteo.com/v1/marine';

const String kStormGlassUrl = 'https://api.stormglass.io/v2/weather/point';

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
    final uri = Uri.parse('$baseUrl$path');
    final request = http.MultipartRequest('POST', uri)
      ..fields.addAll(fields ?? {});
    if (files != null) {
      request.files.addAll(files);
    }
    final streamed = await request.send();
    return http.Response.fromStream(streamed);
  }

  // ---------------------------------------------------------------------
  // Direct Open-Meteo fallback (no backend required)
  // ---------------------------------------------------------------------

  Future<Map<String, dynamic>> _fetchOpenMeteoCurrent(
      double lat, double lon) async {
    final uri = Uri.parse(
        '$kOpenMeteoUrl?latitude=$lat&longitude=$lon'
        '&current=temperature_2m,relative_humidity_2m,apparent_temperature,'
        'precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m,'
        'weather_code,pressure_msl,cloud_cover,visibility,dew_point_2m,'
        'uv_index,is_day&timezone=auto');
    final res = await _client
        .get(uri)
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Open-Meteo error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final current = data['current'] as Map<String, dynamic>? ?? {};
    return <String, dynamic>{
      'temperature': current['temperature_2m'],
      'relative_humidity': current['relative_humidity_2m'],
      'apparent_temperature': current['apparent_temperature'],
      'precipitation': current['precipitation'],
      'wind_speed': current['wind_speed_10m'],
      'wind_direction': current['wind_direction_10m'],
      'wind_gusts': current['wind_gusts_10m'],
      'weather_code': current['weather_code'],
      'pressure': current['pressure_msl'],
      'cloud_cover': current['cloud_cover'],
      'visibility': current['visibility'],
      'dew_point_2m': current['dew_point_2m'],
      'uv_index': current['uv_index'],
      'is_day': current['is_day'],
      'time': current['time'],
      'timezone': data['timezone'],
    };
  }

  Future<List<Map<String, dynamic>>> _fetchOpenMeteoForecast(
      double lat, double lon, int days) async {
    final uri = Uri.parse(
        '$kOpenMeteoUrl?latitude=$lat&longitude=$lon'
        '&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,'
        'precipitation_probability_max,weather_code'
        '&forecast_days=$days&timezone=auto');
    final res = await _client
        .get(uri)
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Open-Meteo forecast error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final daily = data['daily'] as Map<String, dynamic>? ?? {};
    final times = daily['time'] as List<dynamic>? ?? [];
    final result = <Map<String, dynamic>>[];
    for (var i = 0; i < times.length; i++) {
      result.add(<String, dynamic>{
        'date': times[i],
        'temperature_max': _safeListIndex(daily['temperature_2m_max'], i),
        'temperature_min': _safeListIndex(daily['temperature_2m_min'], i),
        'precipitation_sum': _safeListIndex(daily['precipitation_sum'], i),
        'precipitation_probability_max':
            _safeListIndex(daily['precipitation_probability_max'], i),
        'weather_code': _safeListIndex(daily['weather_code'], i),
      });
    }
    return result;
  }

  Future<Map<String, dynamic>> _fetchOpenMeteoAgri(
      double lat, double lon) async {
    final uri = Uri.parse(
        '$kOpenMeteoUrl?latitude=$lat&longitude=$lon'
        '&current=et0_fao_evapotranspiration,soil_temperature_0_to_7cm,'
        'soil_temperature_7_to_28cm,soil_moisture_0_to_7cm,'
        'soil_moisture_7_to_28cm,leaf_wetness_probability&timezone=auto');
    final res = await _client
        .get(uri)
        .timeout(const Duration(seconds: 12));
    if (res.statusCode != 200) {
      throw HttpException('Open-Meteo agri error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final current = data['current'] as Map<String, dynamic>? ?? {};
    return <String, dynamic>{
      'et0_fao_evapotranspiration':
          current['et0_fao_evapotranspiration'],
      'soil_temperature_0_to_7cm': current['soil_temperature_0_to_7cm'],
      'soil_temperature_7_to_28cm': current['soil_temperature_7_to_28cm'],
      'soil_moisture_0_to_7cm': current['soil_moisture_0_to_7cm'],
      'soil_moisture_7_to_28cm': current['soil_moisture_7_to_28cm'],
      'leaf_wetness_probability': current['leaf_wetness_probability'],
    };
  }

  dynamic _safeListIndex(List<dynamic>? list, int index) {
    if (list == null || index >= list.length) return null;
    return list[index];
  }

  Future<WeatherData> fetchCurrentWeather(
      double lat, double lon, String timezone) async {
    final cacheKey = 'weather:$lat:$lon';
    final cached = offline.getWeatherPreferCache(cacheKey);
    if (cached != null) {
      return WeatherData.fromJson(cached);
    }

    // Try backend first
    try {
      final res = await _get('/api/v1/weather/current?lat=$lat&lon=$lon')
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        await offline.cacheWeatherData(cacheKey, data);
        return WeatherData.fromJson(data);
      }
    } catch (e) {
      debugPrint('Backend weather failed, using Open-Meteo fallback: $e');
    }

    // Fallback: direct Open-Meteo
    final data = await _fetchOpenMeteoCurrent(lat, lon);
    await offline.cacheWeatherData(cacheKey, data);
    return WeatherData.fromJson(data);
  }

  Future<List<DailyForecast>> fetchForecast(
      double lat, double lon, int days) async {
    // Try backend first
    try {
      final res = await _get(
          '/api/v1/weather/forecast?lat=$lat&lon=$lon&days=$days')
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final daily = data['daily'] as List<dynamic>? ?? [];
        return daily
            .map((e) => DailyForecast.fromJson(e as Map<String, dynamic>))
            .toList();
      }
    } catch (e) {
      debugPrint('Backend forecast failed, using Open-Meteo fallback: $e');
    }

    // Fallback: direct Open-Meteo
    final daily = await _fetchOpenMeteoForecast(lat, lon, days);
    return daily
        .map((e) => DailyForecast.fromJson(e))
        .toList();
  }

  Future<AgriMetrics> fetchAgriMetrics(double lat, double lon) async {
    // Try backend first
    try {
      final res = await _get('/api/v1/weather/agri?lat=$lat&lon=$lon')
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return AgriMetrics.fromJson(data);
      }
    } catch (e) {
      debugPrint('Backend agri failed, using Open-Meteo fallback: $e');
    }

    // Fallback: direct Open-Meteo
    final data = await _fetchOpenMeteoAgri(lat, lon);
    return AgriMetrics.fromJson(data);
  }

  Future<MarineMetrics> fetchMarineMetrics(double lat, double lon) async {
    // Try backend first (it may enrich with Open-Meteo + StormGlass)
    try {
      final res = await _get('/api/v1/weather/marine?lat=$lat&lon=$lon')
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        return MarineMetrics.fromJson(data);
      }
    } catch (e) {
      debugPrint('Backend marine failed, trying fallbacks: $e');
    }

    // Fallback 1: direct Open-Meteo Marine API
    final openMeteoData = await _fetchOpenMeteoMarine(lat, lon);

    // Fallback 2: StormGlass API (enrichment for wave period & additional detail)
    final stormGlassData = await _fetchStormGlassMarine(lat, lon);

    // Merge: StormGlass fills gaps where Open-Meteo is missing data
    final merged = <String, dynamic>{...openMeteoData};
    for (final entry in stormGlassData.entries) {
      if (merged[entry.key] == null) merged[entry.key] = entry.value;
    }

    if (merged.isNotEmpty) return MarineMetrics.fromJson(merged);
    return MarineMetrics();
  }

  Future<Map<String, dynamic>> _fetchOpenMeteoMarine(double lat, double lon) async {
    try {
      final uri = Uri.parse(
          '$kOpenMeteoMarineUrl?latitude=$lat&longitude=$lon'
          '&current=wave_height,wave_direction,swell_wave_height,'
          'swell_wave_direction,sea_surface_temperature,wave_period,wave_peak_period'
          '&timezone=auto');
      final res = await _client.get(uri).timeout(const Duration(seconds: 12));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final current = data['current'] as Map<String, dynamic>? ?? {};
        final marine = <String, dynamic>{
          'wave_height': current['wave_height'],
          'wave_direction': current['wave_direction'],
          'swell_wave_height': current['swell_wave_height'],
          'swell_wave_direction': current['swell_wave_direction'],
          'sea_surface_temperature': current['sea_surface_temperature'],
          'wave_period': current['wave_period'],
          'wave_peak_period': current['wave_peak_period'],
        };

        // Also fetch wind gusts from the regular forecast API
        try {
          final gustsUri = Uri.parse(
              '$kOpenMeteoUrl?latitude=$lat&longitude=$lon'
              '&current=wind_gusts_10m&timezone=auto');
          final gustsRes = await _client.get(gustsUri).timeout(const Duration(seconds: 8));
          if (gustsRes.statusCode == 200) {
            final gustsData = jsonDecode(gustsRes.body) as Map<String, dynamic>;
            final gustsCurrent = gustsData['current'] as Map<String, dynamic>? ?? {};
            marine['wind_gusts'] = gustsCurrent['wind_gusts_10m'];
          }
        } catch (e) {
          debugPrint('Marine wind gusts fetch failed: $e');
        }

        return marine;
      }
    } catch (e) {
      debugPrint('Open-Meteo marine fetch failed: $e');
    }
    return {};
  }

  Future<Map<String, dynamic>> _fetchStormGlassMarine(double lat, double lon) async {
    const apiKey = String.fromEnvironment('STORMGLASS_API_KEY', defaultValue: '');
    if (apiKey.isEmpty) return {};
    try {
      final uri = Uri.parse(
          '$kStormGlassUrl?lat=$lat&lng=$lon'
          '&params=waveHeight,waveDirection,wavePeriod,swellHeight,waterTemperature,currentSpeed,currentDirection'
          '&source=sg');
      final res = await _client
          .get(uri, headers: {'Authorization': apiKey})
          .timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final hours = data['hours'] as List<dynamic>? ?? [];
        if (hours.isNotEmpty) {
          final current = hours[0] as Map<String, dynamic>;
          return {
            'wave_height': current['waveHeight'],
            'wave_direction': current['waveDirection'],
            'wave_period': current['wavePeriod'],
            'swell_wave_height': current['swellHeight'],
            'sea_surface_temperature': current['waterTemperature'],
          };
        }
      }
    } catch (e) {
      debugPrint('StormGlass marine fetch failed: $e');
    }
    return {};
  }

  Future<List<AlertItem>> fetchAlerts(double lat, double lon) async {
    // Try backend first
    try {
      final res = await _get('/api/v1/alerts/active?lat=$lat&lon=$lon')
          .timeout(const Duration(seconds: 8));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final alerts = data['active_alerts'] as List<dynamic>? ?? [];
        return alerts
            .map((e) => AlertItem.fromJson(e as Map<String, dynamic>))
            .toList();
      }
    } catch (e) {
      debugPrint('Backend alerts failed: $e');
    }
    // Fallback: derive simple alerts from current weather
    try {
      final current = await _fetchOpenMeteoCurrent(lat, lon);
      final wind = (current['wind_speed'] as num?)?.toDouble() ?? 0.0;
      final precip = (current['precipitation'] as num?)?.toDouble() ?? 0.0;
      final now = DateTime.now().toUtc().toIso8601String();
      final alerts = <AlertItem>[];
      if (wind >= 60) {
        alerts.add(AlertItem(
          level: 'Orange',
          color: '#FFA500',
          title: 'High Wind Alert',
          description: 'Strong winds expected. Secure loose objects.',
          windSpeedKmh: wind,
          precipitationMm: precip,
          issuedAt: now,
        ));
      } else if (wind >= 40) {
        alerts.add(AlertItem(
          level: 'Yellow',
          color: '#FFFF00',
          title: 'Moderate Wind Advisory',
          description: 'Elevated wind speeds. Exercise caution.',
          windSpeedKmh: wind,
          precipitationMm: precip,
          issuedAt: now,
        ));
      }
      if (precip >= 25) {
        alerts.add(AlertItem(
          level: 'Orange',
          color: '#FFA500',
          title: 'Heavy Rainfall Warning',
          description: 'Heavy rain likely. Possible localised flooding.',
          windSpeedKmh: wind,
          precipitationMm: precip,
          issuedAt: now,
        ));
      } else if (precip >= 10) {
        alerts.add(AlertItem(
          level: 'Yellow',
          color: '#FFFF00',
          title: 'Moderate Rainfall Advisory',
          description: 'Moderate rainfall expected. Carry umbrella.',
          windSpeedKmh: wind,
          precipitationMm: precip,
          issuedAt: now,
        ));
      }
      if (alerts.isEmpty) {
        alerts.add(AlertItem(
          level: 'Green',
          color: '#00AA00',
          title: 'No Active Weather Alerts',
          description: 'Current conditions are within normal range.',
          windSpeedKmh: wind,
          precipitationMm: precip,
          issuedAt: now,
        ));
      }
      return alerts;
    } catch (e) {
      debugPrint('Open-Meteo alerts fallback failed: $e');
      return [];
    }
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

  Future<List<LocationSearchResult>> searchLocation(String query) async {
    final encoded = Uri.encodeComponent(query);
    final res = await _get('/api/v1/weather/search?q=$encoded&count=8')
        .timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) {
      throw HttpException('Search API error ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    final results = data['results'] as List<dynamic>? ?? [];
    return results
        .map((e) => LocationSearchResult.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<ExpertChatResponse> fetchExpertChat({
    required double lat,
    required double lon,
    required String persona,
    required String lang,
    required String query,
    String? locationName,
    List<Map<String, dynamic>>? history,
  }) async {
    final fields = {
      'lat': lat.toString(),
      'lon': lon.toString(),
      'persona': persona,
      'lang': lang,
      'query': query,
      if (locationName != null) 'location_name': locationName,
      if (history != null && history.isNotEmpty)
        'history_json': jsonEncode(history),
    };

    final res = await _post('/api/v1/expert/chat', fields: fields)
        .timeout(const Duration(seconds: 60));
    if (res.statusCode != 200) {
      throw HttpException('Expert chat API error ${res.statusCode}');
    }
    return ExpertChatResponse.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<ExpertVoiceResponse> fetchExpertVoice({
    required double lat,
    required double lon,
    required String persona,
    required String lang,
    required File audioFile,
    List<Map<String, dynamic>>? history,
    String? locationName,
  }) async {
    final fields = {
      'lat': lat.toString(),
      'lon': lon.toString(),
      'persona': persona,
      'lang': lang,
      if (history != null && history.isNotEmpty)
        'history_json': jsonEncode(history),
      if (locationName != null) 'location_name': locationName,
    };

    final res = await _post(
      '/api/v1/expert/voice',
      fields: fields,
      files: [
        http.MultipartFile.fromBytes(
          'audio',
          await audioFile.readAsBytes(),
          filename: 'voice_query.wav',
        ),
      ],
    ).timeout(const Duration(seconds: 60));

    if (res.statusCode != 200) {
      throw HttpException('Expert voice API error ${res.statusCode}');
    }
    return ExpertVoiceResponse.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }

  Future<ExpertChatResponse> fetchExpertAnalyze({
    required double lat,
    required double lon,
    required String persona,
    required String lang,
    required File file,
    String? prompt,
    List<Map<String, dynamic>>? history,
  }) async {
    final fields = {
      'lat': lat.toString(),
      'lon': lon.toString(),
      'persona': persona,
      'lang': lang,
      if (prompt != null) 'prompt': prompt,
      if (history != null && history.isNotEmpty)
        'history_json': jsonEncode(history),
    };

    final res = await _post(
      '/api/v1/expert/analyze',
      fields: fields,
      files: [
        http.MultipartFile.fromBytes(
          'file',
          await file.readAsBytes(),
          filename: file.path.split('/').last,
        ),
      ],
    ).timeout(const Duration(seconds: 120));

    if (res.statusCode != 200) {
      throw HttpException('Expert analyze API error ${res.statusCode}');
    }
    return ExpertChatResponse.fromJson(jsonDecode(res.body) as Map<String, dynamic>);
  }
}

class WeatherData {
  final double? temperature;
  final double? relativeHumidity;
  final double? apparentTemperature;
  final double? precipitation;
  final double? windSpeed;
  final double? windDirection;
  final double? windGusts;
  final int? weatherCode;
  final double? pressure;
  final double? cloudCover;
  final double? visibility;
  final double? dewPoint;
  final double? uvIndex;
  final int? isDay;
  final String? time;
  final String? timezone;

  WeatherData({
    this.temperature,
    this.relativeHumidity,
    this.apparentTemperature,
    this.precipitation,
    this.windSpeed,
    this.windDirection,
    this.windGusts,
    this.weatherCode,
    this.pressure,
    this.cloudCover,
    this.visibility,
    this.dewPoint,
    this.uvIndex,
    this.isDay,
    this.time,
    this.timezone,
  });

  factory WeatherData.fromJson(Map<String, dynamic> data) => WeatherData(
        temperature: (data['temperature'] as num?)?.toDouble(),
        relativeHumidity: (data['relative_humidity'] as num?)?.toDouble(),
        apparentTemperature: (data['apparent_temperature'] as num?)?.toDouble(),
        precipitation: (data['precipitation'] as num?)?.toDouble(),
        windSpeed: (data['wind_speed'] as num?)?.toDouble(),
        windDirection: (data['wind_direction'] as num?)?.toDouble(),
        windGusts: (data['wind_gusts'] as num?)?.toDouble(),
        weatherCode: data['weather_code'] as int?,
        pressure: (data['pressure'] as num?)?.toDouble(),
        cloudCover: (data['cloud_cover'] as num?)?.toDouble(),
        visibility: (data['visibility'] as num?)?.toDouble(),
        dewPoint: (data['dew_point_2m'] as num?)?.toDouble(),
        uvIndex: (data['uv_index'] as num?)?.toDouble(),
        isDay: data['is_day'] as int?,
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
   final double? wavePeriod;
   final double? wavePeakPeriod;

   MarineMetrics({
     this.waveHeight,
     this.waveDirection,
     this.swellWaveHeight,
     this.swellWaveDirection,
     this.seaSurfaceTemperature,
     this.windGusts,
     this.wavePeriod,
     this.wavePeakPeriod,
   });

   factory MarineMetrics.fromJson(Map<String, dynamic> data) => MarineMetrics(
         waveHeight: (data['wave_height'] as num?)?.toDouble(),
         waveDirection: (data['wave_direction'] as num?)?.toDouble(),
         swellWaveHeight: (data['swell_wave_height'] as num?)?.toDouble(),
         swellWaveDirection: (data['swell_wave_direction'] as num?)?.toDouble(),
         seaSurfaceTemperature:
             (data['sea_surface_temperature'] as num?)?.toDouble(),
         windGusts: (data['wind_gusts'] as num?)?.toDouble(),
         wavePeriod: (data['wave_period'] as num?)?.toDouble(),
         wavePeakPeriod: (data['wave_peak_period'] as num?)?.toDouble(),
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

class ExpertChatResponse {
  final String reply;
  final List<Map<String, dynamic>> history;
  final String language;
  final bool weatherAvailable;
  final String persona;

  ExpertChatResponse({
    required this.reply,
    required this.history,
    required this.language,
    required this.weatherAvailable,
    required this.persona,
  });

  factory ExpertChatResponse.fromJson(Map<String, dynamic> data) {
    final historyList = data['history'] as List<dynamic>? ?? [];
    return ExpertChatResponse(
      reply: data['reply'] as String? ?? '',
      history: historyList.cast<Map<String, dynamic>>(),
      language: data['language'] as String? ?? 'en',
      weatherAvailable: data['weather_available'] as bool? ?? false,
      persona: data['persona'] as String? ?? 'general',
    );
  }
}

class ExpertVoiceResponse {
  final String transcript;
  final String reply;
  final String replyAudioBase64;
  final List<Map<String, dynamic>> history;
  final String language;

  ExpertVoiceResponse({
    required this.transcript,
    required this.reply,
    required this.replyAudioBase64,
    required this.history,
    required this.language,
  });

  factory ExpertVoiceResponse.fromJson(Map<String, dynamic> data) {
    final historyList = data['history'] as List<dynamic>? ?? [];
    return ExpertVoiceResponse(
      transcript: data['transcript'] as String? ?? '',
      reply: data['reply'] as String? ?? '',
      replyAudioBase64: data['reply_audio'] as String? ?? '',
      history: historyList.cast<Map<String, dynamic>>(),
      language: data['language'] as String? ?? 'en',
    );
  }
}

class LocationSearchResult {
  final String name;
  final String? country;
  final String? admin1;
  final double latitude;
  final double longitude;

  LocationSearchResult({
    required this.name,
    this.country,
    this.admin1,
    required this.latitude,
    required this.longitude,
  });

  String get displayName {
    final parts = <String>[
      if (admin1 != null && admin1!.isNotEmpty) admin1!,
      if (country != null && country!.isNotEmpty) country!,
    ];
    return parts.isNotEmpty ? '$name, ${parts.join(', ')}' : name;
  }

  factory LocationSearchResult.fromJson(Map<String, dynamic> data) =>
      LocationSearchResult(
        name: data['name'] as String? ?? 'Unknown',
        country: data['country'] as String?,
        admin1: data['admin1'] as String?,
        latitude: (data['latitude'] as num?)?.toDouble() ?? 0.0,
        longitude: (data['longitude'] as num?)?.toDouble() ?? 0.0,
      );
}
