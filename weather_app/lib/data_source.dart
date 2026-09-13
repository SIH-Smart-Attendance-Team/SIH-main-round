class DataLink {
  final String text;
  final String url;
  final bool isFtp;

  DataLink({required this.text, required this.url, this.isFtp = false});

  factory DataLink.fromJson(Map<String, dynamic> json) {
    return DataLink(
      text: json['text'],
      url: json['url'],
      isFtp: json['is_ftp'] ?? false,
    );
  }
}

class DataSource {
  final String label;
  final List<DataLink> links;
  final String? note;

  DataSource({required this.label, required this.links, this.note});

  factory DataSource.fromJson(Map<String, dynamic> json) {
    return DataSource(
      label: json['label'],
      links: (json['links'] as List)
          .map((l) => DataLink.fromJson(l))
          .toList(),
      note: json['note'],
    );
  }
}
