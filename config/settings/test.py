"""
With these settings, tests run faster.
"""

from .base import *  # noqa: F403
from .base import TEMPLATES
from .base import env

# Django 5.1's Context.__copy__ uses ``copy(super())``, which raises on
# Python 3.14 while Django's test client stores rendered templates. Keep this
# compatibility shim test-only; production rendering is unchanged.
import sys

if sys.version_info >= (3, 14):
    from django.template.context import Context

    def _python314_context_copy(self):
        duplicate = object.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        duplicate.render_context = self.render_context
        if hasattr(self, "template"):
            duplicate.template = self.template
        return duplicate

    Context.__copy__ = _python314_context_copy

# Keep SQLite as the default local test database, but allow the concurrency
# suite to run against a real PostgreSQL database when explicitly requested.
# Example:
# TEST_DATABASE_URL=postgresql://booking_test:***@127.0.0.1:5432/booking_test
TEST_DATABASE_URL = env("TEST_DATABASE_URL", default="")
if TEST_DATABASE_URL:
    DATABASES["default"] = env.db_url_config(TEST_DATABASE_URL)

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="XSVS8GMz48D8ysA1142bJEKljCGWU3DKv8lqviUFyr0NocUKULwnaUNSlWjyb3Bl",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#test-runner
TEST_RUNNER = "django.test.runner.DiscoverRunner"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# DEBUGGING FOR TEMPLATES
# ------------------------------------------------------------------------------
TEMPLATES[0]["OPTIONS"]["debug"] = True  # type: ignore[index]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "http://media.testserver/"
# Your stuff...
# ------------------------------------------------------------------------------
