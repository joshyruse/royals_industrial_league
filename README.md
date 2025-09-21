# Royals Industrial League — Django Starter

A minimal Django project that lets players log in, set availability, see schedule, and lets the captain build/publish a lineup for 3 singles + 3 doubles (9 players).

## Quickstart
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py seed_demo
python manage.py runserver
```

# Royals Industrial League Webapp

A full-featured Django web application for managing a tennis league.  
Players can log in, set availability, view schedules, and track results.  
Captains can build and publish lineups, manage subs, and record scores.  
Admins can manage schedules, rosters, and season results.  

The UI is built with a custom purple-themed design, featuring light/dark mode, glassy tables, sticky headers, row highlights, and toast notifications.

---

## Features
- **Player tools**: Availability, match results, profile management.
- **Captain tools**: Fixture details, lineup builder, sub planning, results entry.
- **Admin tools**: Manage schedules, rosters, scores, season snapshots.
- **Notifications**: Notification bell, list view, mark-all-read.
- **Theming**: Dark/light toggle, purple-accented design, responsive layout.
- **Security**: CSP hardened, login lockouts (`django-axes`), health check endpoint.
- **Observability**: Sentry hooks (server + optional browser).
- **Deployment ready**: Split settings (`dev.py` / `prod.py`), Dockerfile, Compose, `/healthz`.

---

## Quickstart (Local Dev)

```bash
# 1. Clone and set up environment
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Copy environment template
cp .env.example .env

# 3. Run migrations & create a superuser
python manage.py migrate
python manage.py createsuperuser

# 4. (Optional) seed demo data
python manage.py seed_demo

# 5. Start development server
python manage.py runserver
```

Access at: <http://127.0.0.1:8000/>

---

## Environment Variables

See `.env.example` for a full list. Key vars:

- `DJANGO_SETTINGS_MODULE` → e.g. `royals_industrial_league.settings.dev` or `.prod`
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED`
- DB connection vars (`DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`)
- Sentry: `SENTRY_DSN` (server), `SENTRY_BROWSER_DSN` (optional browser)

---

## Theming

- All theme rules live in `static/css/theme.css`.
- Supports light/dark mode toggle.
- Glass-styled tables with sticky headers.
- Row hover highlight (pale purple in light mode, deep purple in dark).
- Toast notifications (green = success, red = error).

---

## Observability

- `/healthz` returns JSON with app/db status.
- Errors auto-report to Sentry if `SENTRY_DSN` is set.
- Browser errors can report if `SENTRY_BROWSER_DSN` is set (conditional include in `base.html`).

---

## Deployment Notes

- **Settings**: Split into `base.py`, `dev.py`, and `prod.py`.
- **Static files**: Served with WhiteNoise. `collectstatic` must run in prod.
- **Dockerfile**: Included for container builds.
  - Default binds to `$PORT` (Render-compatible).
  - Runs `collectstatic` during build.
- **docker-compose.yml**: Included for local dev with Postgres.
- **Render**: Supports native or Docker deploy. Configure env vars in dashboard.

---

## Security

- Strict CSP (`django-csp`): no inline scripts/styles.
- `django-axes` lockouts after failed logins.
- Secure cookies (`SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HttpOnly).
- X-Frame-Options, Referrer-Policy, Permissions-Policy set.
- Custom error pages (`404.html`, `500.html`).
- `robots.txt` disallows indexing until launch.

---

## Tests

Run with pytest:

```bash
pytest
```

Included smoke tests:
- `tests/test_healthz.py`: verifies health endpoint.
- `tests/test_auth.py`: basic login/logout flow (to add).
- Future: coverage for captain tools, lineup builder, subs, etc.

---

## Roadmap

- Finalize unfinished captain/admin tools.
- Expand player stats & playoff eligibility.
- Add analytics/logging integration.
- CI/CD pipeline.
- Production deployment on Render.