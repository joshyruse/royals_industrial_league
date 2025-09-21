# league/emaildev.py
import os
from anymail.signals import pre_send
from django.dispatch import receiver

REDIRECT_TO = os.getenv("EMAIL_REDIRECT_TO")  # e.g. josh+dev@...
WHITELIST = {addr.strip().lower() for addr in os.getenv("EMAIL_WHITELIST", "").split(",") if addr.strip()}

@receiver(pre_send)
def redirect_recipients_in_dev(sender, message=None, **kwargs):
    """
    In dev: redirect all recipients to a safe inbox, unless whitelisted.
    Activate by setting EMAIL_REDIRECT_TO in env. Optionally set EMAIL_WHITELIST.
    """
    if not REDIRECT_TO:
        return  # feature off

    def needs_redirect(addresses):
        # True if any recipient is not whitelisted
        return any(a.lower() not in WHITELIST for a in addresses or [])

    # If any 'to' recipient isn't whitelisted, redirect entire message to REDIRECT_TO
    if needs_redirect(message.to):
        message.to = [REDIRECT_TO]
        message.cc = []
        message.bcc = []
        # Make it obvious in the subject
        if "[DEV-REDIRECT]" not in (message.subject or ""):
            message.subject = f"[DEV-REDIRECT] {message.subject or ''}".strip()