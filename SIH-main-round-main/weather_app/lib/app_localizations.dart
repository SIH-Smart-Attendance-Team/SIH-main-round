import 'dart:ui';
import 'package:flutter/material.dart';

class AppLocalizations {
  final Locale locale;

  AppLocalizations(this.locale);

  static const supportedLocales = [
    Locale('en'),
    Locale('hi'),
    Locale('bn'),
    Locale('ta'),
    Locale('te'),
    Locale('mr'),
    Locale('gu'),
    Locale('kn'),
    Locale('ml'),
    Locale('pa'),
    Locale('or'),
    Locale('as'),
    Locale('ur'),
    Locale('ne'),
    Locale('sa'),
    Locale('sd'),
    Locale('mai'),
    Locale('sat'),
    Locale('kok'),
    Locale('mni'),
    Locale('doi'),
    Locale('brx'),
    Locale('ks'),
  ];

  static AppLocalizations of(BuildContext context) {
    return Localizations.of<AppLocalizations>(context, AppLocalizations)!;
  }

  static const _localizedValues = <String, Map<String, String>>{
    'en': {
      'appTitle': 'WeatherGPT',
      'subtitle': 'Your Intelligent Weather Assistant',
      'welcomeBack': 'Welcome Back 👋',
      'signInToContinue': 'Sign in to continue to WeatherGPT',
      'createAccount': 'Create Account',
      'joinWeatherGPT': 'Join WeatherGPT for personalized forecasts',
      'name': 'Name',
      'email': 'Email',
      'password': 'Password',
      'signIn': 'Sign In',
      'signUp': 'Sign Up',
      'dontHaveAccount': "Don't have an account? Sign Up",
      'alreadyHaveAccount': 'Already have an account? Sign In',
      'pleaseEnterEmailAndPassword': 'Please enter email and password',
      'currentConditions': 'Current Conditions',
      'sevenDayForecast': '7-Day Forecast',
      'climateEnvironmental': 'Climate & Environmental',
      'agriculturalConditions': 'Agricultural Conditions',
      'noClimateDataAvailable': 'No climate data available',
      'noForecastData': 'No forecast data',
      'temp': 'TEMP',
      'humidity': 'HUMIDITY',
      'wind': 'WIND',
      'precip': 'PRECIP',
      'pressure': 'PRESSURE',
      'feelsLike': 'Feels like {temp}°C',
      'persona': 'Persona',
      'language': 'Language',
      'farmer': 'Farmer',
      'fisherman': 'Fisherman',
      'urbanCommuter': 'Urban Commuter',
      'searchCity': 'Search city...',
      'typeCityToSearch': 'Type a city name to search',
      'noResultsFound': 'No results found',
      'couldNotReachBackend':
          'Could not reach backend. Check your internet and settings.',
      'settings': 'Settings',
      'backendServer': 'Backend Server',
      'backendUrlHint': 'http://192.168.1.100:8000',
      'backendUrlDescription':
          'Enter the URL of your WeatherGPT backend server.',
      'save': 'Save',
      'backendUrlSaved': 'Backend URL saved',
      'pleaseEnterValidUrl':
          'Please enter a valid URL (e.g. http://192.168.1.100:8000)',
      'current': 'Current: {url}',
      'advisory': 'Advisory',
      'textAdvisory': 'Text Advisory',
      'holdToSpeak': 'Hold to speak',
      'releaseToSend': 'Release to send',
      'typeMessage': 'Type a message...',
      'send': 'Send',
      'weatherQuestion': 'Weather Question',
      'personaLabel': 'Persona: {persona} | Language: {lang}',
      'cancel': 'Cancel',
      'sendQuestion': 'Send',
      'noActiveWeatherAlerts': 'No Active Weather Alerts',
      'currentConditionsNormal':
          'Current conditions are within normal range.',
      'marineConditions': 'Marine Conditions',
      'soilTemp': 'Soil Temp',
      'soilMoisture': 'Soil Moisture',
      'leafWetness': 'Leaf Wetness',
      'waveHeight': 'Wave Height',
      'seaTemp': 'Sea Temp',
      'windGusts': 'Wind Gusts',
      'farmerDesc': 'Crops, irrigation, spraying & harvest advice',
      'fishermanDesc': 'Waves, storms, sea conditions & safe fishing',
      'urbanCommuterDesc': 'Rain, commute, travel & city weather',
      'helpline': 'Helpline',
      'whatsappHelpline': 'WhatsApp Helpline',
      'callHelpline': 'Call Helpline',
    },
    'hi': {
      'appTitle': 'वेदरGPT',
      'subtitle': 'आपका बुद्धिमान मौसम सहायक',
      'welcomeBack': 'वापसी पर स्वागत है 👋',
      'signInToContinue': 'वेदरGPT में जारी रखने के लिए साइन इन करें',
      'createAccount': 'खाता बनाएं',
      'joinWeatherGPT': 'व्यक्तिगत पूर्वानुमान के लिए वेदरGPT से जुड़ें',
      'name': 'नाम',
      'email': 'ईमेल',
      'password': 'पासवर्ड',
      'signIn': 'साइन इन',
      'signUp': 'साइन अप',
      'dontHaveAccount': 'खाता नहीं है? साइन अप करें',
      'alreadyHaveAccount': 'पहले से खाता है? साइन इन करें',
      'pleaseEnterEmailAndPassword': 'कृपया ईमेल और पासवर्ड दर्ज करें',
      'currentConditions': 'वर्तमान स्थिति',
      'sevenDayForecast': '7-दिन का पूर्वानुमान',
      'climateEnvironmental': 'जलवायु और पर्यावरण',
      'noClimateDataAvailable': 'कोई जलवायु डेटा उपलब्ध नहीं',
      'noForecastData': 'कोई पूर्वानुमान डेटा नहीं',
      'temp': 'तापमान',
      'humidity': 'आर्द्रता',
      'wind': 'हवा',
      'precip': 'वर्षा',
      'pressure': 'दाब',
      'feelsLike': 'महसूस होता है {temp}°C',
      'persona': 'व्यक्तित्व',
      'language': 'भाषा',
      'farmer': 'किसान',
      'fisherman': 'मचुआरा',
      'urbanCommuter': 'शहरी यात्री',
      'farmerDesc': 'फसल, सिंचाई, स्प्रे और कटाई की सलाह',
      'fishermanDesc': 'लहरें, तूफान, समुद्री स्थिति और सुरक्षित मछली पकड़ना',
      'urbanCommuterDesc': 'बारिश, कम्यूट, यात्रा और शहर का मौसम',
      'helpline': 'हेल्पलाइन',
      'whatsappHelpline': 'व्हाट्सएप हेल्पलाइन',
      'callHelpline': 'हेल्पलाइन कॉल करें',
      'searchCity': 'शहर खोजें...',
      'typeCityToSearch': 'शहर का नाम टाइप करें',
      'noResultsFound': 'कोई परिणाम नहीं मिला',
      'couldNotReachBackend':
          'बैकएंड तक नहीं पहुंच सका। अपने इंटरनेट और सेटिंग्स की जांच करें।',
      'settings': 'सेटिंग्स',
      'backendServer': 'बैकएंड सर्वर',
      'backendUrlHint': 'http://192.168.1.100:8000',
      'backendUrlDescription':
          'अपने वेदरGPT बैकएंड सर्वर का URL दर्ज करें।',
      'save': 'सहेजें',
      'backendUrlSaved': 'बैकएंड URL सहेजा गया',
      'pleaseEnterValidUrl':
          'कृपया एक वैध URL दर्ज करें (उदाहरण: http://192.168.1.100:8000)',
      'current': 'वर्तमान: {url}',
      'advisory': 'सलाह',
      'textAdvisory': 'टेक्स्ट सलाह',
      'holdToSpeak': 'बोलने के लिए दबाएं',
      'releaseToSend': 'भेजने के लिए छोड़ें',
      'typeMessage': 'संदेश टाइप करें...',
      'send': 'भेजें',
      'weatherQuestion': 'मौसम प्रश्न',
      'personaLabel': 'व्यक्तित्व: {persona} | भाषा: {lang}',
      'cancel': 'रद्द करें',
      'sendQuestion': 'भेजें',
      'noActiveWeatherAlerts': 'कोई सक्रिय मौसम अलर्ट नहीं',
      'currentConditionsNormal':
          'वर्तमान स्थिति सामान्य सीमा में है।',
      'marineConditions': 'समुद्री स्थिति',
      'soilTemp': 'मिट्टी का तापमान',
      'soilMoisture': 'मिट्टी की नमी',
      'leafWetness': 'पत्ती की नमी',
      'waveHeight': 'लहर ऊंचाई',
      'seaTemp': 'समुद्री तापमान',
      'windGusts': 'हवा के झोंके',
    },
    'bn': {
      'appTitle': 'ওয়েদারGPT',
      'subtitle': 'আপনার বুদ্ধিমান আবহাওয়া সহায়ক',
      'welcomeBack': 'ফিরে আস科学者ে স্বাগতম 👋',
      'signInToContinue': 'ওয়েদারGPT তে যেতে সাইন ইন করুন',
      'createAccount': 'অ্যাকাউন্ট তৈরি করুন',
      'joinWeatherGPT': 'ব্যক্তিগত পূর্বাভাসের জন্য ওয়েদারGPT যোগ দিন',
      'name': 'নাম',
      'email': 'ইমেইল',
      'password': 'পাসওয়ার্ড',
      'signIn': 'সাইন ইন',
      'signUp': 'সাইন আপ',
      'dontHaveAccount': 'অ্যাকাউন্ট নেই? সাইন আপ করুন',
      'alreadyHaveAccount': 'অ্যাকাউন্ট আছে? সাইন ইন করুন',
      'pleaseEnterEmailAndPassword': 'অনুগ্রহ করে ইমেইল ও পাসওয়ার্ড দিন',
      'currentConditions': 'বর্তমান অবস্থা',
      'sevenDayForecast': '৭-দিনের পূর্বাভাস',
      'climateEnvironmental': 'জলবায়ু ও পরিবেশ',
      'noClimateDataAvailable': 'কোন জলবায়ু ডাটা নেই',
      'noForecastData': 'কোন পূর্বাভাস ডাটা নেই',
      'temp': 'তাপমাত্রা',
      'humidity': 'আর্দ্রতা',
      'wind': 'বায়ু',
      'precip': 'বৃষ্টি',
      'pressure': 'চাপ',
      'feelsLike': 'অনুভূত {temp}°C',
      'persona': 'ব্যক্তিত্ব',
      'language': 'ভাষা',
      'farmer': 'কৃষক',
      'fisherman': 'মats',
      'urbanCommuter': 'শহरी পথিক',
      'searchCity': 'শহার খুঁজুন...',
      'typeCityToSearch': 'শহার নাম টাইপ করুন',
      'noResultsFound': 'কোন ফলাফল পাওয়া যায়নি',
      'couldNotReachBackend':
          'ব্যাকএন্ডে পৌঁছাতে পারি না। ইন্টারনেট ও সেটিংস চেক করুন।',
      'settings': 'সেটিংস',
      'backendServer': 'ব্যাকএন্ড সার্ভার',
      'backendUrlHint': 'http://192.168.1.100:8000',
      'backendUrlDescription':
          'আপনার ওয়েদারGPT ব্যাকএন্ড সার্ভারের URL লিখুন।',
      'save': 'সংরক্ষণ',
      'backendUrlSaved': 'ব্যাকএন্ড URL সংরক্ষিত',
      'pleaseEnterValidUrl':
          'অনুগ্রহ করে বৈধ URL দিন (যেমন: http://192.168.1.100:8000)',
      'current': 'বর্তমান: {url}',
      'advisory': 'পরামর্শ',
      'textAdvisory': 'টেক্সট পরামর্শ',
      'holdToSpeak': 'কথা বলতে ধরে রাখুন',
      'releaseToSend': 'পাঠাতে ছাড়ুন',
      'typeMessage': 'বার্তা টাইপ করুন...',
      'send': 'পাঠান',
      'weatherQuestion': 'আবহাওয়া প্রশ্ন',
      'personaLabel': 'ব্যক্তিত্ব: {persona} | ভাষা: {lang}',
      'cancel': 'বাতিল',
      'sendQuestion': 'পাঠান',
      'noActiveWeatherAlerts': 'কোন সক্রিয় আবহাওয়া সতর্কতা নেই',
      'currentConditionsNormal': 'বর্তমান অবস্থা স্বাভাবিক সীমার মধ্যে।',
      'marineConditions': 'সমুদ্রীয় অবস্থা',
      'soilTemp': 'মাটির তাপমাত্রা',
      'soilMoisture': 'মাটির আর্দ্রতা',
      'leafWetness': 'পানthora আর্দ্রতা',
      'waveHeight': 'তরঙ্গ উচ্চতা',
      'seaTemp': 'সমুদ্র তাপমাত্রা',
      'windGusts': 'বায়ু ঝড়',
    },
    'ta': {
      'appTitle': 'வேதர்GPT',
      'subtitle': 'உங்கள் புத்திசாலி வானிலை உதவியாளர்',
      'welcomeBack': 'மீண்டும் வரவேற்கிறோம் 👋',
      'signInToContinue': 'வேதர்GPT க்கு தொடரக்க உள்நுழையவும்',
      'createAccount': 'கணக்கை உருவாக்கவும்',
      'joinWeatherGPT': 'தனிப்பயன் முன்னறிவிப்புகளுக்கு வேதர்GPT இல் சேரவும்',
      'name': 'பெயர்',
      'email': 'மின்னஞ்சல்',
      'password': 'கடவுச்சொல்',
      'signIn': 'உள்நுழைக',
      'signUp': 'பதிவு செய்க',
      'dontHaveAccount': 'கணக்கு இல்லையா? பதிவு செய்க',
      'alreadyHaveAccount': 'ஏற்கனவே கணக்கு உள்ளதா? உள்நுழைக',
      'pleaseEnterEmailAndPassword': 'மின்னஞ்சல் மற்றும் கடவுச்சொல்லை உள்ளிடவும்',
      'currentConditions': 'தற்போதைய நிலைமை',
      'sevenDayForecast': '7-நாள் முன்னறிவு',
      'climateEnvironmental': 'காலநிலை & சுற்றுச்சூழல்',
      'noClimateDataAvailable': 'காலநிலை தரவு இல்லை',
      'noForecastData': 'முன்னறிவு தரவு இல்லை',
      'temp': 'வெப்பநிலை',
      'humidity': 'தேவmedio',
      'wind': 'காற்று',
      'precip': 'மழை',
      'pressure': 'அழுத்தம்',
      'feelsLike': '{temp}°C போல் உணர்கிறது',
      'persona': 'தனிப்பட்ட விவரம்',
      'language': 'மொழி',
      'farmer': 'விவசாயி',
      'fisherman': 'மீன்வளர்',
      'urbanCommuter': 'நகர பயணி',
      'searchCity': 'நகரம் தேடுங்கள்...',
      'typeCityToSearch': 'நகரத்தின் பெயரை தட்டச்சு செய்யுங்கள்',
      'noResultsFound': 'முடிவுகள் இல்லை',
      'couldNotReachBackend':
          'ব্যাকএন্ডinki पह公司ોच率帕尔费尔。 இணைப்பு மற்றும் அமைப்புகளை சரிபார்க்கவும்.',
      'settings': 'அமைப்புகள்',
      'backendServer': 'ব্যাকএন্ড সার্ভার',
      'backendUrlHint': 'http://192.168.1.100:8000',
      'backendUrlDescription':
          'உங்கள் WeatherGPT ব্যাকএন্ড সার্ভার URL ஐ உள்ளிடவும்.',
      'save': 'சேமி',
      'backendUrlSaved': 'ব্যাকএন্ড URL சேமிக்கப்பட்டது',
      'pleaseEnterValidUrl':
          'தயவுசெய்து செல்லுபடியான URL ஐ உள்ளிடவும் (உதா: http://192.168.1.100:8000)',
      'current': 'தற்போது: {url}',
      'advisory': 'ஆலோசனை',
      'textAdvisory': 'உரை ஆலோசனை',
      'holdToSpeak': 'பேச த矢ק公司oம்',
      'releaseToSend': 'அனுப்ப விடவும்',
      'typeMessage': 'செய்தியை தட்டச்சு செய்யுங்கள்...',
      'send': 'அனுப்பு',
      'weatherQuestion': 'வானிலaii கேள்வி',
      'personaLabel': 'தனிப்பட்ட விவரம்: {persona} | மொழி: {lang}',
      'cancel': 'ரதித公司',
      'sendQuestion': 'அனுப்பு',
      'noActiveWeatherAlerts': 'சक்ரிய வானிலை எச்சரிக்கைகள் இல்லை',
      'currentConditionsNormal': 'தற்போதைய நிலைமை சாதாரண வ级公司度.',
      'marineConditions': 'கடல் நிலைமைகள்',
      'soilTemp': 'மண் வெப்பநிலை',
      'soilMoisture': 'மண் ஈர்ப்பு',
      'leafWetness': 'இலை ஈர்ப்பு',
      'waveHeight': 'அலை உயரம்',
      'seaTemp': 'கடல் வெப்பநிலை',
      'windGusts': 'காற்று அதிகம்',
    },
    'te': {
      'appTitle': 'వేదరGPT',
      'subtitle': 'మీ బుద్ధిమంతమైన వాతావరణ సహాయకుడు',
      'welcomeBack': 'మళ్లీ స్వాగతం 👋',
      'signInToContinue': 'వేదరGPT కు కొనసాగించడానికి సైన్ ఇన్ చేయండి',
      'createAccount': 'ఖాతా సృష్టించండి',
      'joinWeatherGPT': 'వ్యక్తిగత పూర్వాంక Genomics కోసం వేదరGPT కు చేరండి',
      'name': 'పేరు',
      'email': 'ఇమెయిల్',
      'password': 'పాస్‌వర్డ్',
      'signIn': 'సైన్ ఇన్',
      'signUp': 'సైన్ అప్',
      'dontHaveAccount': 'ఖాతా లేదా? సైన్ అప్ చేయండి',
      'alreadyHaveAccount': 'ఇప్పుడే ఖాతా ఉందా? సైన్ ఇన్ చేయండి',
      'pleaseEnterEmailAndPassword': 'దయచేసి ఇమెయిల్ మరియు పాస్‌వర్డ్ నమోదు చేయండి',
      'currentConditions': 'ప్రస్తుత పరిస్థితులు',
      'sevenDayForecast': '7-రోజుల అంచనా',
      'climateEnvironmental': 'వాతావరణం & పర్యావరణం',
      'noClimateDataAvailable': 'వాతావరణ డాటా లేదు',
      'noForecastData': 'అంచనా డాటా లేదు',
      'temp': 'తాపం',
      'humidity': 'ఆర్ద్రత',
      'wind': 'గాలి',
      'precip': 'వర్షం',
      'pressure': 'ఒత్తిడి',
      'feelsLike': '{temp}°C లా అనిపిస్తుంది',
      'persona': 'వ్యక్తిత్వం',
      'language': 'భాష',
      'farmer': 'రైతు',
      'fisherman': 'చేపలు',
      'urbanCommuter': 'నగర యాత్రికుడు',
      'searchCity': 'నగరం శోధించండి...',
      'typeCityToSearch': 'నగరం పేరు టైప్ చేయండి',
      'noResultsFound': 'ఫలితాలు లేవు',
      'couldNotReachBackend':
          'ব্যাকএন্ডకు చేరలేగాను。 మీ ఇంటర్నెట్ & సెట్టింగ్‌లను చెక్ చేయండి.',
      'settings': 'సెట్టింగ్‌లు',
      'backendServer': 'ব্যাকএন্ড সার্ভర',
      'backendUrlHint': 'http://192.168.1.100:8000',
      'backendUrlDescription':
          'మీ WeatherGPT ব্যাকএন্ড সার্ভర URL ను నమోదు చేయండి.',
      'save': 'సేవ్',
      'backendUrlSaved': 'ব্যাকএন্ড URL సేవ్ అయ్యింది',
      'pleaseEnterValidUrl':
          'దయచేసి సరైన URL ను నమోదు చేయండి (ఉదా: http://192.168.1.100:8000)',
      'current': 'ప్రస్తుతం: {url}',
      'advisory': 'సలహా',
      'textAdvisory': 'టెక్స్ట్ సలహా',
      'holdToSpeak': 'మాటలు చెప్పడానికి పెట్టుకోండి',
      'releaseToSend': 'పంపడానికి విడిదండి',
      'typeMessage': 'సందేశాన్ని టైప్ చేయండి...',
      'send': 'పంపు',
      'weatherQuestion': 'వాతావరణ ప్రశ్న',
      'personaLabel': 'వ్యక్తిత్వం: {persona} | భాష: {lang}',
      'cancel': 'రద్దు',
      'sendQuestion': 'పంపు',
      'noActiveWeatherAlerts': 'సక్రియ వాతావరణ ఎర్టులు లేవు',
      'currentConditionsNormal': 'ప్రస్తుత పరిస్థితులు సాధారణ పరిమితిలో ఉన్నాయి.',
      'marineConditions': 'సముద్ర పరిస్థితులు',
      'soilTemp': 'నేల ఉష్ణత',
      'soilMoisture': 'నేల తేమ',
      'leafWetness': 'ఆకు తేమ',
      'waveHeight': 'అల ఎత్తు',
      'seaTemp': 'సముద్ర ఉష్ణత',
      'windGusts': 'గాలి గుడ్డి',
    },
  };

  String get appTitle => _t('appTitle');
  String get subtitle => _t('subtitle');
  String get welcomeBack => _t('welcomeBack');
  String get signInToContinue => _t('signInToContinue');
  String get createAccount => _t('createAccount');
  String get joinWeatherGPT => _t('joinWeatherGPT');
  String get name => _t('name');
  String get email => _t('email');
  String get password => _t('password');
  String get signIn => _t('signIn');
  String get signUp => _t('signUp');
  String get dontHaveAccount => _t('dontHaveAccount');
  String get alreadyHaveAccount => _t('alreadyHaveAccount');
  String get pleaseEnterEmailAndPassword => _t('pleaseEnterEmailAndPassword');
  String get currentConditions => _t('currentConditions');
  String get sevenDayForecast => _t('sevenDayForecast');
  String get climateEnvironmental => _t('climateEnvironmental');
  String get agriculturalConditions => _t('agriculturalConditions');
  String get noClimateDataAvailable => _t('noClimateDataAvailable');
  String get noForecastData => _t('noForecastData');
  String get temp => _t('temp');
  String get humidity => _t('humidity');
  String get wind => _t('wind');
  String get precip => _t('precip');
  String get pressure => _t('pressure');
  String get persona => _t('persona');
  String get language => _t('language');
  String get farmer => _t('farmer');
  String get fisherman => _t('fisherman');
  String get urbanCommuter => _t('urbanCommuter');
  String get farmerDesc => _t('farmerDesc');
  String get fishermanDesc => _t('fishermanDesc');
  String get urbanCommuterDesc => _t('urbanCommuterDesc');
  String get helpline => _t('helpline');
  String get whatsappHelpline => _t('whatsappHelpline');
  String get callHelpline => _t('callHelpline');
  String get searchCity => _t('searchCity');
  String get typeCityToSearch => _t('typeCityToSearch');
  String get noResultsFound => _t('noResultsFound');
  String get couldNotReachBackend => _t('couldNotReachBackend');
  String get settings => _t('settings');
  String get backendServer => _t('backendServer');
  String get backendUrlHint => _t('backendUrlHint');
  String get backendUrlDescription => _t('backendUrlDescription');
  String get save => _t('save');
  String get backendUrlSaved => _t('backendUrlSaved');
  String get pleaseEnterValidUrl => _t('pleaseEnterValidUrl');
  String get advisory => _t('advisory');
  String get textAdvisory => _t('textAdvisory');
  String get holdToSpeak => _t('holdToSpeak');
  String get releaseToSend => _t('releaseToSend');
  String get typeMessage => _t('typeMessage');
  String get send => _t('send');
  String get weatherQuestion => _t('weatherQuestion');
  String get cancel => _t('cancel');
  String get noActiveWeatherAlerts => _t('noActiveWeatherAlerts');
  String get currentConditionsNormal => _t('currentConditionsNormal');
  String get marineConditions => _t('marineConditions');
  String get soilTemp => _t('soilTemp');
  String get soilMoisture => _t('soilMoisture');
  String get leafWetness => _t('leafWetness');
  String get waveHeight => _t('waveHeight');
  String get seaTemp => _t('seaTemp');
  String get windGusts => _t('windGusts');

  String feelsLike(String temp) => _t('feelsLike').replaceAll('{temp}', temp);
  String current(String url) => _t('current').replaceAll('{url}', url);
  String personaLabel(String persona, String lang) =>
      _t('personaLabel').replaceAll('{persona}', persona).replaceAll('{lang}', lang);

  String _t(String key) {
    final lang = locale.languageCode;
    final map = _localizedValues[lang] ?? _localizedValues['en']!;
    return map[key] ?? _localizedValues['en']![key] ?? key;
  }
}

class AppLocalizationsDelegate extends LocalizationsDelegate<AppLocalizations> {
  const AppLocalizationsDelegate();

  @override
  bool isSupported(Locale locale) =>
      AppLocalizations.supportedLocales.any((l) => l.languageCode == locale.languageCode);

  @override
  Future<AppLocalizations> load(Locale locale) async => AppLocalizations(locale);

  @override
  bool shouldReload(AppLocalizationsDelegate old) => false;
}
