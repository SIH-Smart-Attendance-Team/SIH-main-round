import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_localizations.dart';
import 'weather_service.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final _controller = TextEditingController();
  bool _isLoading = true;
  String _savedUrl = '';
  String get _kBackendUrlKey => 'backend_url';

  @override
  void initState() {
    super.initState();
    _loadUrl();
  }

  Future<void> _loadUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final url = prefs.getString(_kBackendUrlKey) ?? kBackendBaseUrl;
    setState(() {
      _savedUrl = url;
      _controller.text = url;
      _isLoading = false;
    });
  }

  Future<void> _saveUrl() async {
    final url = _controller.text.trim();
    final loc = AppLocalizations.of(context);
    if (url.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(loc.pleaseEnterValidUrl)),
      );
      return;
    }
    Uri? parsed;
    try {
      parsed = Uri.parse(url);
    } catch (_) {
      parsed = null;
    }
    if (parsed == null || !parsed.hasAbsolutePath || parsed.host.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(loc.pleaseEnterValidUrl)),
      );
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kBackendUrlKey, url);
    setState(() => _savedUrl = url);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(loc.backendUrlSaved)),
      );
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
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
        title: Text(loc.settings, style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
        centerTitle: false,
        actions: [
          TextButton(
            onPressed: _saveUrl,
            child: Text(loc.save, style: TextStyle(color: cs.primary, fontWeight: FontWeight.w700)),
          ),
        ],
      ),
      body: _isLoading
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              children: [
                const SizedBox(height: 24),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Text(
                    loc.backendServer,
                    style: theme.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  ),
                ),
                const SizedBox(height: 8),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: Text(
                    loc.backendUrlDescription,
                    style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                  ),
                ),
                const SizedBox(height: 12),
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 24),
                  child: TextField(
                    controller: _controller,
                    decoration: InputDecoration(
                      hintText: loc.backendUrlHint,
                      border: const OutlineInputBorder(),
                      isDense: true,
                    ),
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                  ),
                ),
                const SizedBox(height: 32),
                if (_savedUrl != kBackendBaseUrl)
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 24),
                    child: Text(
                      loc.current(_savedUrl),
                      style: theme.textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
                    ),
                  ),
              ],
            ),
    );
  }
}
