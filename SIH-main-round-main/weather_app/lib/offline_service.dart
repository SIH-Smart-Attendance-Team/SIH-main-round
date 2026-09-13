// offline_services.dart
//
// Offline Data Storage Engine for WeatherGPT.
//
// - Hive-backed key-value cache for weather / advisory payloads
// - Connectivity-aware offline queue that flushes when the device
//   comes back online
//
// Required packages (pubspec.yaml):
//   hive: ^2.2.3
//   hive_flutter: ^1.1.0
//   connectivity_plus: ^6.0.0
//   path_provider: ^2.1.0

import 'dart:async';
import 'dart:convert';

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:hive_flutter/hive_flutter.dart';

// ---------------------------------------------------------------------------
// Box names
// ---------------------------------------------------------------------------
const String _kWeatherBox = 'weather_cache';
const String _kQueueBox = 'offline_queue';
const String _kMetaBox = 'offline_meta';

// Default TTL for cached weather data (6 hours)
const Duration kDefaultCacheTtl = Duration(hours: 6);

// ---------------------------------------------------------------------------
// OfflineServices singleton
// ---------------------------------------------------------------------------
class OfflineServices {
  OfflineServices._();
  static final OfflineServices instance = OfflineServices._();

  Box<String>? _weatherBox;
  Box<String>? _queueBox;
  Box<dynamic>? _metaBox;

  StreamSubscription<List<ConnectivityResult>>? _connectivitySub;
  bool _isOnline = true;
  bool _initialized = false;

  /// Callback invoked when the device transitions from offline → online.
  /// Register your own sync handlers here (e.g. flush pending voice queries).
  final List<Future<void> Function()> _onReconnectCallbacks = [];

  // -----------------------------------------------------------------------
  // Lifecycle
  // -----------------------------------------------------------------------

  /// Call once at app start (before runApp or inside main).
  Future<void> init() async {
    if (_initialized) return;

    await Hive.initFlutter();
    _weatherBox = await Hive.openBox<String>(_kWeatherBox);
    _queueBox = await Hive.openBox<String>(_kQueueBox);
    _metaBox = await Hive.openBox(_kMetaBox);

    // Seed connectivity state
    final results = await Connectivity().checkConnectivity();
    _isOnline = _hasConnection(results);

    _connectivitySub = Connectivity().onConnectivityChanged.listen((results) {
      final wasOnline = _isOnline;
      _isOnline = _hasConnection(results);

      if (!wasOnline && _isOnline) {
        debugPrint('[OfflineServices] Back online – flushing queue');
        _flushQueue();
        for (final cb in _onReconnectCallbacks) {
          cb().catchError((e) => debugPrint('Reconnect callback error: $e'));
        }
      } else if (wasOnline && !_isOnline) {
        debugPrint('[OfflineServices] Gone offline');
      }
    });

    _initialized = true;
    debugPrint('[OfflineServices] Initialised (online=$_isOnline)');
  }

  Future<void> dispose() async {
    await _connectivitySub?.cancel();
    await _weatherBox?.close();
    await _queueBox?.close();
    await _metaBox?.close();
    _initialized = false;
  }

  bool get isOnline => _isOnline;

  void addOnReconnectListener(Future<void> Function() cb) {
    _onReconnectCallbacks.add(cb);
  }

  void removeOnReconnectListener(Future<void> Function() cb) {
    _onReconnectCallbacks.remove(cb);
  }

  // -----------------------------------------------------------------------
  // Weather cache
  // -----------------------------------------------------------------------

  /// Persist a weather / advisory payload under [key].
  ///
  /// The value is stored as a JSON string together with a timestamp so that
  /// [getOfflineWeather] can honour TTL.
  Future<void> cacheWeatherData(
    String key,
    Map<String, dynamic> data, {
    Duration ttl = kDefaultCacheTtl,
  }) async {
    _ensureInit();
    final envelope = <String, dynamic>{
      'cached_at': DateTime.now().toUtc().toIso8601String(),
      'ttl_seconds': ttl.inSeconds,
      'payload': data,
    };
    await _weatherBox!.put(key, jsonEncode(envelope));
    debugPrint('[OfflineServices] Cached "$key"');
  }

  /// Return the cached payload for [key], or `null` when missing / expired.
  Map<String, dynamic>? getOfflineWeather(String key) {
    _ensureInit();
    final raw = _weatherBox!.get(key);
    if (raw == null) return null;

    try {
      final envelope = jsonDecode(raw) as Map<String, dynamic>;
      final cachedAt = DateTime.parse(envelope['cached_at'] as String);
      final ttlSeconds = envelope['ttl_seconds'] as int? ?? kDefaultCacheTtl.inSeconds;
      final age = DateTime.now().toUtc().difference(cachedAt);

      if (age.inSeconds > ttlSeconds) {
        // Expired – remove lazily
        _weatherBox!.delete(key);
        debugPrint('[OfflineServices] Cache expired for "$key"');
        return null;
      }
      return Map<String, dynamic>.from(envelope['payload'] as Map);
    } catch (e) {
      debugPrint('[OfflineServices] Corrupt cache for "$key": $e');
      _weatherBox!.delete(key);
      return null;
    }
  }

  /// Convenience: returns cache when offline, otherwise null
  /// (caller should hit the network).
  Map<String, dynamic>? getWeatherPreferCache(String key) {
    if (!_isOnline) return getOfflineWeather(key);
    return null;
  }

  Future<void> clearWeatherCache() async {
    _ensureInit();
    await _weatherBox!.clear();
  }

  // -----------------------------------------------------------------------
  // Offline action queue
  // -----------------------------------------------------------------------

  /// Enqueue an arbitrary action that should be replayed when connectivity
  /// is restored.  [type] is a free-form tag (e.g. "voice_query", "feedback").
  Future<void> enqueueOfflineAction(
    String type,
    Map<String, dynamic> payload,
  ) async {
    _ensureInit();
    final id = '${DateTime.now().millisecondsSinceEpoch}_${type.hashCode}';
    final entry = <String, dynamic>{
      'id': id,
      'type': type,
      'payload': payload,
      'enqueued_at': DateTime.now().toUtc().toIso8601String(),
    };
    await _queueBox!.put(id, jsonEncode(entry));
    debugPrint('[OfflineServices] Enqueued action "$type" ($id)');
  }

  /// Drain the queue.  Each entry is passed to the optional [handler].
  /// If [handler] returns `true` the entry is removed; otherwise it stays
  /// for a later attempt.
  Future<void> _flushQueue({
    Future<bool> Function(String type, Map<String, dynamic> payload)? handler,
  }) async {
    _ensureInit();
    if (_queueBox!.isEmpty) return;

    final keys = _queueBox!.keys.toList();
    for (final key in keys) {
      final raw = _queueBox!.get(key);
      if (raw == null) continue;
      try {
        final entry = jsonDecode(raw) as Map<String, dynamic>;
        final type = entry['type'] as String;
        final payload = Map<String, dynamic>.from(entry['payload'] as Map);

        bool success = true;
        if (handler != null) {
          success = await handler(type, payload);
        } else {
          // Default: just log – real handlers are registered via callbacks
          debugPrint('[OfflineServices] Would replay "$type": $payload');
        }

        if (success) {
          await _queueBox!.delete(key);
        }
      } catch (e) {
        debugPrint('[OfflineServices] Failed to process queue item $key: $e');
      }
    }
  }

  /// Public entry-point so other modules can force a flush with a custom handler.
  Future<void> flushOfflineQueue(
    Future<bool> Function(String type, Map<String, dynamic> payload) handler,
  ) =>
      _flushQueue(handler: handler);

  int get pendingQueueLength {
    _ensureInit();
    return _queueBox!.length;
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  bool _hasConnection(List<ConnectivityResult> results) {
    return results.any((r) =>
        r == ConnectivityResult.mobile ||
        r == ConnectivityResult.wifi ||
        r == ConnectivityResult.ethernet ||
        r == ConnectivityResult.vpn);
  }

  void _ensureInit() {
    if (!_initialized || _weatherBox == null) {
      throw StateError(
        'OfflineServices not initialised. Call OfflineServices.instance.init() first.',
      );
    }
  }
}

// ---------------------------------------------------------------------------
// Convenience top-level aliases (optional sugar)
// ---------------------------------------------------------------------------
Future<void> cacheWeatherData(String key, Map<String, dynamic> data) =>
    OfflineServices.instance.cacheWeatherData(key, data);

Map<String, dynamic>? getOfflineWeather(String key) =>
    OfflineServices.instance.getOfflineWeather(key);