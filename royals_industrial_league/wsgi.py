import os
from django.core.wsgi import get_wsgi_application

# Default to production settings when a server process (Gunicorn, uWSGI) imports this
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "royals_industrial_league.settings.prod")

application = get_wsgi_application()