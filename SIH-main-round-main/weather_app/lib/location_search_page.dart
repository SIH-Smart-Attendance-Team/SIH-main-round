import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'dart:convert';

import 'app_localizations.dart';
import 'weather_service.dart';

class LocationSearchPage extends StatefulWidget {
  const LocationSearchPage({super.key});

  @override
  State<LocationSearchPage> createState() => _LocationSearchPageState();
}

class _LocationSearchPageState extends State<LocationSearchPage> {
  final _controller = TextEditingController();
  bool _isLoading = false;
  List<LocationSearchResult> _results = [];
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _search(String query) async {
    if (query.trim().isEmpty) {
      setState(() {
        _results = [];
        _error = null;
      });
      return;
    }
    setState(() {
      _isLoading = true;
      _error = null;
    });
    try {
      final baseUrl = await BackendConfig.getBaseUrl();
      final uri = Uri.parse(
        '$baseUrl/api/v1/weather/search?q=${Uri.encodeComponent(query)}&count=8',
      );
      final res = await http.get(uri).timeout(const Duration(seconds: 10));
      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        final items = data['results'] as List<dynamic>? ?? [];
        setState(() {
          _results = items
              .map((e) => LocationSearchResult.fromJson(e as Map<String, dynamic>))
              .toList();
        });
      } else {
        setState(() => _error = AppLocalizations.of(context).couldNotReachBackend);
      }
    } catch (e) {
      setState(() => _error = AppLocalizations.of(context).couldNotReachBackend);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  void _selectLocation(LocationSearchResult result) {
    Navigator.of(context).pop(result);
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
        title: TextField(
          controller: _controller,
          autofocus: true,
          decoration: InputDecoration(
            hintText: loc.searchCity,
            border: InputBorder.none,
            hintStyle: TextStyle(color: cs.onSurfaceVariant.withValues(alpha: 0.6)),
          ),
          style: theme.textTheme.titleMedium,
          onSubmitted: _search,
        ),
        actions: [
          IconButton(
            onPressed: () => _search(_controller.text),
            icon: const Icon(Icons.search_rounded),
          ),
        ],
      ),
      body: _buildBody(theme, cs, loc),
    );
  }

  Widget _buildBody(ThemeData theme, ColorScheme cs, AppLocalizations loc) {
    if (_isLoading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
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
      );
    }
    if (_results.isEmpty && _controller.text.isNotEmpty) {
      return Center(
        child: Text(loc.noResultsFound, style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
      );
    }
    if (_results.isEmpty) {
      return Center(
        child: Text(loc.typeCityToSearch, style: theme.textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
      );
    }

    return ListView.builder(
      padding: const EdgeInsets.symmetric(vertical: 8),
      itemCount: _results.length,
      itemBuilder: (ctx, i) {
        final r = _results[i];
        return ListTile(
          leading: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: cs.primary.withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Icon(Icons.location_on_rounded, color: cs.primary, size: 22),
          ),
          title: Text(r.displayName, style: theme.textTheme.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
          subtitle: Text(
            '${r.latitude.toStringAsFixed(2)}, ${r.longitude.toStringAsFixed(2)}',
            style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
          ),
          onTap: () => _selectLocation(r),
        );
      },
    );
  }
}
