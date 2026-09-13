import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import 'app_localizations.dart';
import 'weather_service.dart';

class DisasterMapPage extends StatefulWidget {
  final double lat;
  final double lon;

  const DisasterMapPage({super.key, required this.lat, required this.lon});

  @override
  State<DisasterMapPage> createState() => _DisasterMapPageState();
}

class _DisasterMapPageState extends State<DisasterMapPage> {
  bool _isLoading = true;
  List<Map<String, dynamic>> _alerts = [];
  String? _error;
  final MapController _mapController = MapController();

  @override
  void initState() {
    super.initState();
    _loadAlerts();
  }

  Future<void> _loadAlerts() async {
    try {
      final baseUrl = await BackendConfig.getBaseUrl();
      final uri = Uri.parse(
        '$baseUrl/api/v1/disaster/alerts?lat=${widget.lat}&lon=${widget.lon}&radius_km=2000&days=7',
      );
      final res = await http.get(uri).timeout(const Duration(seconds: 20));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final alerts = (data['alerts'] as List<dynamic>? ?? [])
            .map((e) => Map<String, dynamic>.from(e as Map))
            .toList();
        setState(() {
          _alerts = alerts;
          _isLoading = false;
        });
      } else {
        setState(() {
          _error = 'Failed to load alerts (${res.statusCode})';
          _isLoading = false;
        });
      }
    } catch (e) {
      setState(() {
        _error = 'Could not reach backend';
        _isLoading = false;
      });
    }
  }

  Color _severityColor(String severity) {
    switch (severity.toLowerCase()) {
      case 'red':
        return const Color(0xFFD8402A);
      case 'orange':
        return const Color(0xFFE8720C);
      case 'yellow':
        return const Color(0xFFE4B92F);
      case 'green':
      default:
        return const Color(0xFF2E9E5B);
    }
  }

  IconData _hazardIcon(String hazardType) {
    switch (hazardType.toLowerCase()) {
      case 'earthquake':
        return Icons.vibration_rounded;
      case 'cyclone':
        return Icons.cyclone_rounded;
      case 'flood':
        return Icons.water_rounded;
      case 'drought':
        return Icons.water_drop_rounded;
      case 'wildfire':
        return Icons.local_fire_department_rounded;
      case 'volcano':
        return Icons.volcano_rounded;
      case 'thunderstorm_risk':
        return Icons.flash_on_rounded;
      default:
        return Icons.warning_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final loc = AppLocalizations.of(context);

    return Scaffold(
      backgroundColor: cs.surface,
      appBar: AppBar(
        backgroundColor: cs.surfaceContainerHigh,
        title: Text('Disaster & Hazard Map', style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
        centerTitle: false,
        actions: [
          IconButton(onPressed: _loadAlerts, icon: const Icon(Icons.refresh_rounded)),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.wifi_off_rounded, size: 48, color: cs.onSurfaceVariant.withValues(alpha: 0.4)),
                        const SizedBox(height: 16),
                        Text(_error!, textAlign: TextAlign.center, style: theme.textTheme.bodyMedium),
                      ],
                    ),
                  ),
                )
              : Stack(
                  children: [
                    FlutterMap(
                      mapController: _mapController,
                      options: MapOptions(
                        initialCenter: LatLng(20.59, 78.96),  // Center of India
                        initialZoom: 5,
                        minZoom: 3,
                        maxZoom: 18,
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                          userAgentPackageName: 'com.example.weather_app',
                        ),
                        MarkerLayer(
                          markers: _alerts.where((alert) {
                            final lat = alert['latitude'] as double?;
                            final lon = alert['longitude'] as double?;
                            return lat != null && lon != null;
                          }).map((alert) {
                            final lat = alert['latitude'] as double;
                            final lon = alert['longitude'] as double;
                            final severity = (alert['severity'] as String?)?.toLowerCase() ?? 'green';
                            final hazardType = (alert['hazard_type'] as String?) ?? 'unknown';
                            final distance = (alert['distance_km'] as num?)?.toDouble() ?? 0.0;
                            
                            // Size based on severity
                            double size = 24;
                            if (severity == 'red') size = 48;
                            else if (severity == 'orange') size = 40;
                            else if (severity == 'yellow') size = 32;
                            
                            return Marker(
                              width: size,
                              height: size,
                              point: LatLng(lat, lon),
                              child: GestureDetector(
                                onTap: () => _showAlertBottomSheet(context, alert),
                                child: Container(
                                  padding: EdgeInsets.all(size / 6),
                                  decoration: BoxDecoration(
                                    color: _severityColor(severity),
                                    shape: BoxShape.circle,
                                    boxShadow: [
                                      BoxShadow(
                                        color: _severityColor(severity).withValues(alpha: 0.5),
                                        blurRadius: size / 3,
                                        spreadRadius: 2,
                                      ),
                                    ],
                                  ),
                                  child: Icon(
                                    _hazardIcon(hazardType),
                                    color: Colors.white,
                                    size: size / 2,
                                  ),
                                ),
                              ),
                            );
                          }).toList(),
                        ),
                      ],
                    ),
                    if (_alerts.isNotEmpty)
                      Positioned(
                        top: 16,
                        left: 16,
                        right: 16,
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: Theme.of(context).colorScheme.surface,
                            borderRadius: BorderRadius.circular(12),
                            boxShadow: [
                              BoxShadow(
                                color: Theme.of(context).colorScheme.shadow.withValues(alpha: 0.1),
                                blurRadius: 8,
                                offset: const Offset(0, 2),
                              ),
                            ],
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'Showing ${_alerts.length} disaster alerts across India',
                                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                  fontWeight: FontWeight.w600,
                                  color: Theme.of(context).colorScheme.onSurface,
                                ),
                              ),
                              const SizedBox(height: 8),
                              Row(
                                children: [
                                  _buildLegendItem('Red', const Color(0xFFD8402A), 'Critical'),
                                  const SizedBox(width: 12),
                                  _buildLegendItem('Orange', const Color(0xFFE8720C), 'High'),
                                  const SizedBox(width: 12),
                                  _buildLegendItem('Yellow', const Color(0xFFE4B92F), 'Medium'),
                                  const SizedBox(width: 12),
                                  _buildLegendItem('Green', const Color(0xFF2E9E5B), 'Low'),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
    );
  }

  Widget _buildLegendItem(String label, Color color, String description) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 12,
          height: 12,
          decoration: BoxDecoration(
            color: color,
            shape: BoxShape.circle,
          ),
        ),
        const SizedBox(width: 4),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: TextStyle(
                color: color,
                fontWeight: FontWeight.w700,
                fontSize: 12,
              ),
            ),
            Text(
              description,
              style: const TextStyle(
                color: Colors.black54,
                fontSize: 10,
              ),
            ),
          ],
        ),
      ],
    );
  }

  void _showAlertBottomSheet(BuildContext context, Map<String, dynamic> alert) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final severity = (alert['severity'] as String?)?.toLowerCase() ?? 'green';
    final title = (alert['title'] as String?) ?? 'Alert';
    final description = (alert['description'] as String?) ?? '';
    final hazardType = (alert['hazard_type'] as String?) ?? 'unknown';
    final source = (alert['source'] as String?) ?? '';

    showModalBottomSheet(
      context: context,
      builder: (ctx) => Container(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(_hazardIcon(hazardType), color: _severityColor(severity), size: 28),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    title,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(
                    color: _severityColor(severity).withValues(alpha: 0.15),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    severity.toUpperCase(),
                    style: theme.textTheme.labelSmall?.copyWith(
                      color: _severityColor(severity),
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ],
            ),
            if (description.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(description, style: theme.textTheme.bodyMedium),
            ],
            if (source.isNotEmpty) ...[
              const SizedBox(height: 8),
              Text('Source: $source', style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
            ],
          ],
        ),
      ),
    );
  }
}
