import re
from decimal import Decimal, ROUND_HALF_UP

from num2words import num2words  # type: ignore[import-untyped]

from app.core.settings import settings


def fmt_number(val: Decimal) -> str:
    """Format a Decimal as a localised number string.

    Uses THOUSAND_SEPARATOR and DECIMAL_SEPARATOR from settings.
    Example (Ukrainian): 1 234,56
    """
    q = val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Python's f-string always uses ',' for thousands and '.' for decimal
    s = f"{q:,.2f}"
    # Swap using a sentinel to avoid double-replacement
    s = (
        s.replace(",", "\x00T\x00")
        .replace(".", "\x00D\x00")
        .replace("\x00T\x00", settings.THOUSAND_SEPARATOR)
        .replace("\x00D\x00", settings.DECIMAL_SEPARATOR)
    )
    return s + (settings.CURRENCY_SUFFIX or "")


def money_to_words(amount: Decimal, lang: str = "uk") -> str:
    """Convert a monetary Decimal to its Ukrainian words representation.

    Example: Decimal("1234.56") → "одна тисяча двісті тридцять чотири грн. 56 коп."
    """
    q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_kop = int((q * 100).to_integral_value(rounding=ROUND_HALF_UP))
    hryv = total_kop // 100
    kop = total_kop % 100

    def _form_for(n: int, forms: tuple[str, str, str]) -> str:
        """Select the correct Ukrainian grammatical form for a number."""
        n = abs(int(n))
        if n % 10 == 1 and n % 100 != 11:
            return forms[0]
        if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
            return forms[1]
        return forms[2]

    if hryv == 0:
        hryv_words = "нуль"
    else:
        thousands = hryv // 1000
        rest = hryv % 1000
        parts: list[str] = []
        if thousands:
            parts.append(num2words(thousands, lang=lang))
            parts.append(_form_for(thousands, ("тисяча", "тисячі", "тисяч")))
        if rest:
            parts.append(num2words(rest, lang=lang))
        hryv_words = " ".join(parts)

    # num2words uses masculine gender for 1 and 2; Ukrainian currency uses feminine
    hryv_words = re.sub(r"\bодин\b", "одна", hryv_words)
    hryv_words = re.sub(r"\bдва\b", "дві", hryv_words)

    return f"{hryv_words} грн. {kop:02d} коп."


def format_ukrainian_name(full_name: str) -> str:
    """Transform 'Іваненко Іван Іванович' → 'Іван ІВАНЕНКО'.

    Raises ValueError if the name has fewer than 2 parts.
    """
    parts = full_name.strip().split()
    if len(parts) < 2:
        raise ValueError(f"Name must have at least 2 parts: '{full_name}'")
    last_name = parts[0].upper()
    first_name = parts[1]
    return f"{first_name} {last_name}"
