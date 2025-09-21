# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

EXPOSE 10000

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . /app/

RUN DJANGO_SETTINGS_MODULE=royals_industrial_league.settings.prod python manage.py collectstatic --noinput
# forcing for Render
CMD ["bash", "-lc", "gunicorn royals_industrial_league.wsgi:application -b 0.0.0.0:${PORT:-10000} -w 3"]