import 'package:flutter/material.dart';

import 'app_localizations.dart';
import 'auth_service.dart';
import 'weather_dashboard_pg.dart';

class AuthPage extends StatefulWidget {
  const AuthPage({super.key});

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  bool _isLogin = true;
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _nameController = TextEditingController();
  bool _isLoading = false;
  bool _obscurePassword = true;
  final AuthService _auth = AuthService();

  @override
  void initState() {
    super.initState();
    _auth.init();
  }

  void _toggleMode() {
    setState(() => _isLogin = !_isLogin);
  }

  Future<void> _submit() async {
    if (_emailController.text.trim().isEmpty || _passwordController.text.isEmpty) {
      if (mounted) {
        final loc = AppLocalizations.of(context);
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(loc.pleaseEnterEmailAndPassword)),
        );
      }
      return;
    }

    setState(() => _isLoading = true);
    try {
      if (_isLogin) {
        await _auth.login(
          email: _emailController.text.trim(),
          password: _passwordController.text,
        );
      } else {
        await _auth.signup(
          email: _emailController.text.trim(),
          password: _passwordController.text,
          name: _nameController.text.trim().isNotEmpty ? _nameController.text.trim() : null,
        );
      }

      if (mounted) {
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => const WeatherDashboardPage()),
        );
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(e.toString())),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final cs = theme.colorScheme;
    final loc = AppLocalizations.of(context);

    return Scaffold(
      backgroundColor: cs.surface,
      body: SafeArea(
        child: Stack(
          children: [
            // Decorative background gradient orbs
            Positioned(
              top: -80,
              right: -60,
              child: Container(
                width: 220,
                height: 220,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      cs.primary.withValues(alpha: 0.15),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ),
            Positioned(
              bottom: -100,
              left: -80,
              child: Container(
                width: 260,
                height: 260,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      cs.tertiary.withValues(alpha: 0.12),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ),
            Positioned(
              top: 180,
              left: -50,
              child: Container(
                width: 120,
                height: 120,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  gradient: RadialGradient(
                    colors: [
                      cs.secondary.withValues(alpha: 0.1),
                      Colors.transparent,
                    ],
                  ),
                ),
              ),
            ),
            Center(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 32),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    // Animated weather logo
                    TweenAnimationBuilder<double>(
                      tween: Tween(begin: 0.8, end: 1.0),
                      duration: const Duration(milliseconds: 900),
                      curve: Curves.easeOutBack,
                      builder: (ctx, val, child) {
                        return Transform.scale(
                          scale: val,
                          child: Container(
                            width: 96,
                            height: 96,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              gradient: LinearGradient(
                                colors: [cs.primary, cs.primary.withValues(alpha: 0.7)],
                                begin: Alignment.topLeft,
                                end: Alignment.bottomRight,
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color: cs.primary.withValues(alpha: 0.35),
                                  blurRadius: 30,
                                  spreadRadius: 4,
                                  offset: const Offset(0, 8),
                                ),
                              ],
                            ),
                            child: Icon(
                              Icons.wb_sunny_rounded,
                              size: 44,
                              color: Colors.white,
                            ),
                          ),
                        );
                      },
                    ),
                    const SizedBox(height: 20),
                     Text(
                       loc.appTitle,
                       style: theme.textTheme.headlineMedium?.copyWith(
                         fontWeight: FontWeight.w800,
                         color: cs.primary,
                         letterSpacing: -0.5,
                       ),
                     ),
                     const SizedBox(height: 4),
                     Text(
                       loc.subtitle,
                       style: theme.textTheme.bodyMedium?.copyWith(
                         color: cs.onSurfaceVariant,
                       ),
                     ),
                    const SizedBox(height: 40),
                    // Glass card container
                    Container(
                      padding: const EdgeInsets.all(24),
                      decoration: BoxDecoration(
                        color: cs.surfaceContainerLowest.withValues(alpha: 0.8),
                        borderRadius: BorderRadius.circular(28),
                        border: Border.all(
                          color: cs.outlineVariant.withValues(alpha: 0.2),
                        ),
                        boxShadow: [
                          BoxShadow(
                            color: cs.shadow.withValues(alpha: 0.06),
                            blurRadius: 24,
                            offset: const Offset(0, 8),
                          ),
                        ],
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                           Text(
                             _isLogin ? loc.welcomeBack : loc.createAccount,
                             style: theme.textTheme.headlineSmall?.copyWith(
                               fontWeight: FontWeight.w700,
                             ),
                           ),
                           const SizedBox(height: 4),
                           Text(
                             _isLogin
                                 ? loc.signInToContinue
                                 : loc.joinWeatherGPT,
                             style: theme.textTheme.bodySmall?.copyWith(
                               color: cs.onSurfaceVariant,
                             ),
                           ),
                          const SizedBox(height: 24),
                          if (!_isLogin) ...[
                            TextField(
                              controller: _nameController,
                              decoration: InputDecoration(
                                labelText: loc.name,
                                prefixIcon: const Icon(Icons.person_outline_rounded),
                              ),
                              textInputAction: TextInputAction.next,
                            ),
                            const SizedBox(height: 16),
                          ],
                          TextField(
                            controller: _emailController,
                            decoration: InputDecoration(
                              labelText: loc.email,
                              prefixIcon: const Icon(Icons.email_outlined),
                            ),
                            keyboardType: TextInputType.emailAddress,
                            textInputAction: TextInputAction.next,
                          ),
                          const SizedBox(height: 16),
                          TextField(
                            controller: _passwordController,
                            decoration: InputDecoration(
                              labelText: loc.password,
                              prefixIcon: const Icon(Icons.lock_outline),
                              suffixIcon: IconButton(
                                icon: Icon(
                                  _obscurePassword
                                      ? Icons.visibility_off_outlined
                                      : Icons.visibility_outlined,
                                ),
                                onPressed: () => setState(
                                  () => _obscurePassword = !_obscurePassword,
                                ),
                              ),
                            ),
                            obscureText: _obscurePassword,
                            textInputAction: TextInputAction.done,
                            onSubmitted: (_) => _submit(),
                          ),
                          const SizedBox(height: 24),
                          SizedBox(
                            width: double.infinity,
                            height: 52,
                            child: FilledButton(
                              onPressed: _isLoading ? null : _submit,
                              style: FilledButton.styleFrom(
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(16),
                                ),
                              ),
                              child: _isLoading
                                  ? const SizedBox(
                                      width: 22,
                                      height: 22,
                                      child: CircularProgressIndicator(
                                        strokeWidth: 2.5,
                                      ),
                                    )
                                  : Text(
                                      _isLogin ? loc.signIn : loc.signUp,
                                      style: const TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextButton(
                      onPressed: _isLoading ? null : _toggleMode,
                      child: Text(
                        _isLogin
                            ? loc.dontHaveAccount
                            : loc.alreadyHaveAccount,
                        style: TextStyle(
                          fontWeight: FontWeight.w600,
                          color: cs.primary,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}