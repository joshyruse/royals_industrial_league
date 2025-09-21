# league/templatetags/phonefmt.py
from django import template

register = template.Library()

@register.filter
def us_format_e164(e164: str) -> str:
    """
    Very simple formatter for US numbers like '+13175141441' -> '+1 (317) 514-1441'.
    If it doesn't look like +1XXXXXXXXXX, returns the original.
    """
    if not e164 or not e164.startswith("+1") or len(e164) < 12:
        return e164 or ""
    # +1 (XXX) XXX-XXXX
    area = e164[2:5]
    pre = e164[5:8]
    last = e164[8:12]
    return f"+1 ({area}) {pre}-{last}"