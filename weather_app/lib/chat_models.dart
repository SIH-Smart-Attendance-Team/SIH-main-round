import 'package:flutter/material.dart';

enum Persona {
  farmer,
  fisherman,
  urbanCommuter,
}

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

  String get backendName {
    switch (this) {
      case Persona.farmer:
        return 'farmer';
      case Persona.fisherman:
        return 'fisherman';
      case Persona.urbanCommuter:
        return 'urban_commuter';
    }
  }

  IconData get icon {
    switch (this) {
      case Persona.farmer:
        return Icons.agriculture_rounded;
      case Persona.fisherman:
        return Icons.sailing_rounded;
      case Persona.urbanCommuter:
        return Icons.commute_rounded;
    }
  }

  Color get color {
    switch (this) {
      case Persona.farmer:
        return Colors.green;
      case Persona.fisherman:
        return Colors.blue;
      case Persona.urbanCommuter:
        return Colors.orange;
    }
  }
}

class ChatMessage {
  final String text;
  final bool isUser;
  final Persona persona;

  ChatMessage({
    required this.text,
    required this.isUser,
    required this.persona,
  });
}
