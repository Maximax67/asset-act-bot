import logging
from decimal import Decimal
from typing import Any

from num2words import num2words  # type: ignore[import-untyped]

from bot.utils.formatters import fmt_number, money_to_words

logger = logging.getLogger(__name__)


def build_variables_for_owner(
    data: dict[str, Any],
    dept: dict[str, str],
) -> dict[str, Any]:
    """Construct the full variables payload for one owner's document.

    Args:
        data: Owner entry from parse_assets() — contains 'items', 'tot_qty', 'tot_sum'
        dept: Department dict from load_departments()

    Returns:
        Dict ready to be sent as {"variables": ...} in the API request body
    """
    tot_qty: int = int(data.get("tot_qty", 0))
    tot_sum: Decimal = data.get("tot_sum", Decimal("0.00"))

    receiver_position = dept.get("receiver_position", "")
    receiver_name = dept.get("receiver_formatted", "")

    if not receiver_position:
        logger.warning(
            f"Department '{dept.get('code', '')}' has no receiver_position; "
            "ReceiverPosition will be empty in the document"
        )
    if not receiver_name:
        logger.warning(
            f"Department '{dept.get('code', '')}' has no receiver name; "
            "ReceiverName will be empty in the document"
        )

    items = [
        {
            "name": str(item.get("name", "")),
            "inventory": str(item.get("inventory", "")),
            "unit": str(item.get("unit", "")),
            "qty": str(int(item.get("qty", 0))),
            "unit_price": (
                fmt_number(item["unit_price"])
                if item.get("unit_price") is not None
                else ""
            ),
            "sum": (fmt_number(item["sum"]) if item.get("sum") is not None else ""),
            "note": str(item.get("note", "")),
        }
        for item in data.get("items", [])
    ]

    return {
        # Totals
        "TotalQuantityWords": num2words(tot_qty, lang="uk"),
        "TotalQuantityNumeric": str(tot_qty),
        "TotalSumNumeric": fmt_number(tot_sum),
        "TotalSumWords": money_to_words(tot_sum, lang="uk"),
        # Director (responsible person in the department)
        "SecondDirectorPosition": dept.get("position", ""),
        "SecondDirectorName": dept.get("formatted_name", ""),
        # Receiver
        "ReceiverPosition": receiver_position,
        "ReceiverName": receiver_name,
        # Convenience alias used in some templates
        "Val": fmt_number(tot_sum),
        # Item table rows
        "items": items,
    }
