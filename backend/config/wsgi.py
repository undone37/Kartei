"""
WSGI config for kartei project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()

# the web server refuses to start with the example key from .env.example or a short one: with a known SECRET_KEY,
# anyone could forge session cookies and read the stored passwords (LDAP, SMTP, ...)
from django.conf import settings  # noqa: E402

if not settings.DEBUG and (settings.SECRET_KEY.startswith("change-me") or len(settings.SECRET_KEY) < 32):
    raise RuntimeError("SECRET_KEY is the example value or shorter than 32 characters: set a long random one in .env "
                       "(e.g. python3 -c 'import secrets; print(secrets.token_urlsafe(50))')")
