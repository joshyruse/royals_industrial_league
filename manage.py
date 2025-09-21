#!/usr/bin/env python
import os
import sys

if __name__ == "__main__":
    # --- Environment bootstrap ---
    # 1) Load dotenv files if python-dotenv is installed.
    #    Priority: explicit DJANGO_ENV file -> .env -> .dev.env fallback
    try:
        from dotenv import load_dotenv
        # If DJANGO_ENV is set and a matching file exists (e.g., ".prod.env"), load it first
        env_name = os.getenv("DJANGO_ENV")
        if env_name and os.path.exists(f".{env_name}.env"):
            load_dotenv(dotenv_path=f".{env_name}.env")
        # Load generic .env next (won't override existing vars)
        if os.path.exists(".env"):
            load_dotenv(dotenv_path=".env")
        # Finally, load .dev.env (for local developer defaults) if present
        if os.path.exists(".dev.env"):
            load_dotenv(dotenv_path=".dev.env")
    except Exception:
        # python-dotenv not installed or load failed; continue with raw environment
        pass

    # 2) Choose the Django settings module.
    #    Precedence: explicit DJANGO_SETTINGS_MODULE > DJANGO_ENV switch > default to dev
    settings_module = os.getenv("DJANGO_SETTINGS_MODULE")
    if not settings_module:
        env = os.getenv("DJANGO_ENV", "dev").lower()
        if env in ("prod", "production"):
            settings_module = "royals_industrial_league.settings.prod"
        elif env in ("test", "testing"):
            settings_module = "royals_industrial_league.settings.dev"  # adjust if you add a real test settings
        else:
            settings_module = "royals_industrial_league.settings.dev"
    print(f"Using settings module: {settings_module}")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)

    # 3) Run Django
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
