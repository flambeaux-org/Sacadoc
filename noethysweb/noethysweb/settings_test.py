#  Test settings — inherits from settings.py and overrides only what's needed for testing.
#  Never use this file in production.

import os

from noethysweb.settings import *  # noqa: F401, F403

# Hardcoded dummy key — safe because this file is never used in production.
SECRET_KEY = "test-secret-key-not-for-production-only-used-in-pytest"

# Keep debug off so debug_toolbar is NOT injected (it requires a real HTTP client).
DEBUG = True

# Named SQLite file so --reuse-db can reuse the schema across local runs.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.path.join(BASE_DIR, "test.sqlite3"),  # noqa: F405
        "TEST": {
            "NAME": os.path.join(BASE_DIR, "test.sqlite3"),
        }
    }
}

# Use an in-memory email backend so no real emails are sent during tests.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# Disable django-axes brute-force lockout — it would block repeated test logins.
AXES_ENABLED = False

# Remove axes from the authentication backend pipeline.
AUTHENTICATION_BACKENDS = [
    "core.backends.EmailModelBackend",
]

# Remove axes middleware (requires AXES_ENABLED or it raises an error).
MIDDLEWARE = [m for m in MIDDLEWARE if "axes" not in m]  # noqa: F405

# Speed up password hashing in tests (MD5 instead of bcrypt/PBKDF2).
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Explicitly disable Turnstile captcha — settings_production.py (imported by base
# settings) may have re-enabled it. Must be set here, after the wildcard import.
TURNSTILE_ENABLE = False
