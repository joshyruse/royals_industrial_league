from urllib.parse import urljoin
from django.conf import settings
from django.templatetags.static import static

def absolute_url(path: str) -> str:
    base = getattr(settings, "PUBLIC_BASE_URL", "http://localhost:8000")
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))

def absolute_static(path: str) -> str:
    return absolute_url(static(path))