import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:url_launcher/url_launcher.dart';
import 'data_source.dart';
import 'data_source_service.dart';

/// Drop this widget anywhere in your widget tree, e.g.:
///   DataSourcesWidget()
/// It fetches and displays the data sources on its own — no other
/// files need to change.
class DataSourcesWidget extends StatelessWidget {
  const DataSourcesWidget({super.key});

  Future<void> _handleTap(BuildContext context, DataLink link) async {
    if (link.isFtp) {
      // Most browsers/platforms can't open ftp:// links directly.
      // Copy to clipboard and let the user paste into an FTP client.
      await Clipboard.setData(ClipboardData(text: link.url));
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'FTP link copied. Open it in an FTP client (e.g. FileZilla):\n${link.url}',
            ),
            duration: const Duration(seconds: 4),
          ),
        );
      }
      return;
    }

    final uri = Uri.parse(link.url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    } else {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not open ${link.url}')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<DataSource>>(
      future: fetchDataSources(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return Padding(
            padding: const EdgeInsets.all(12),
            child: Text('Error loading data sources: ${snapshot.error}'),
          );
        }
        final sources = snapshot.data ?? [];
        return ListView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: sources.length,
          itemBuilder: (context, index) {
            final source = sources[index];
            return Card(
              margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 8),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      source.label,
                      style: const TextStyle(
                        fontWeight: FontWeight.bold,
                        fontSize: 16,
                      ),
                    ),
                    const SizedBox(height: 6),
                    if (source.links.isEmpty && source.note != null)
                      Text(
                        source.note!,
                        style: const TextStyle(
                          fontStyle: FontStyle.italic,
                          color: Colors.grey,
                        ),
                      ),
                    ...source.links.map(
                      (link) => InkWell(
                        onTap: () => _handleTap(context, link),
                        child: Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: Text(
                            link.isFtp
                                ? '${link.text} (FTP — tap to copy)'
                                : link.text,
                            style: const TextStyle(
                              color: Colors.blue,
                              decoration: TextDecoration.underline,
                            ),
                          ),
                        ),
                      ),
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
}
