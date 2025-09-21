import os
from django.core.asgi import get_asgi_application

# Default to production settings when an ASGI server (Uvicorn, Daphne) imports this
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "royals_industrial_league.settings.prod")

application = get_asgi_application()