import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from app.core.settings import settings
from bot.utils.formatters import format_ukrainian_name
from bot.utils.google_sheets import read_sheet_values

logger = logging.getLogger(__name__)

# Asset sheet columns (1-based)
COL_NAME: int = 3
COL_INVENTORY_NUMBER: int = 5
COL_UNIT: int = 6
COL_QUANTITY: int = 7
COL_PRICE: int = 9
COL_OWNERS: int = 10
COL_GENERATE_FLAG: int = 11

# Department sheet columns (1-based)
DEPT_COL_CODE: int = 1
DEPT_COL_POSITION: int = 2
DEPT_COL_FULLNAME: int = 3
DEPT_COL_RECEIVER_POSITION: int = 4
DEPT_COL_RECEIVER_FULLNAME: int = 5


def safe_get(row: list[Any], col: int, default: Any = "") -> Any:
    """Return the value at 1-based column *col* in *row*, or *default*."""
    if row is None:
        return default
    idx = col - 1
    if idx < 0 or idx >= len(row):
        return default
    val = row[idx]
    return val if val is not None else default


def is_row_empty(row: list[Any]) -> bool:
    if not row:
        return True
    return not any(str(cell).strip() for cell in row)


def parse_string_number(raw: Any) -> Decimal:
    """Parse a cell value into a Decimal, tolerating Ukrainian number formatting.

    Accepts spaces / non-breaking spaces as thousand separators, and commas as
    the decimal separator.

    Raises:
        ValueError: if the value cannot be parsed
    """
    if raw is None:
        raise ValueError("Empty numeric value (None)")
    s = (
        str(raw)
        .strip()
        .replace("\xa0", "")  # non-breaking space
        .replace(" ", "")
        .replace(",", ".")
    )
    if not s:
        raise ValueError("Empty numeric value after stripping")
    try:
        return Decimal(s)
    except Exception as exc:
        raise ValueError(f"Cannot parse '{raw}' as a number: {exc}") from exc


def quantize_money(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_required_fields(
    row: list[Any], field_definitions: list[tuple[int, str]]
) -> list[str]:
    """Return names of fields that are empty / missing."""
    return [
        name
        for col_idx, name in field_definitions
        if not str(safe_get(row, col_idx, "")).strip()
    ]


def parse_owner_token(tok: str) -> tuple[str, Optional[int], bool]:
    """Parse a single owner token.

    'DEPT-10' → ('DEPT', 10, True)   — explicit quantity
    'DEPT'    → ('DEPT', None, False) — implicit (whole row qty)
    """
    tok = tok.strip()
    m = re.match(r"^(.*?)-\s*([0-9]+)\s*$", tok)
    if m:
        return m.group(1).strip(), int(m.group(2)), True
    return tok, None, False


class ProcessingStats:
    def __init__(self) -> None:
        self.rows_processed: int = 0
        self.rows_skipped: int = 0
        self.owners_skipped: int = 0
        self.total_items_in_acts: int = 0
        self.total_value_generated: Decimal = Decimal("0.00")

    def skip_row(self) -> None:
        self.rows_skipped += 1

    def process_row(self) -> None:
        self.rows_processed += 1

    def skip_owner(self) -> None:
        self.owners_skipped += 1

    def add_item(self, value: Decimal) -> None:
        self.total_items_in_acts += 1
        self.total_value_generated += value

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_processed": self.rows_processed,
            "rows_skipped": self.rows_skipped,
            "owners_skipped": self.owners_skipped,
            "total_items_in_acts": self.total_items_in_acts,
            "total_value_generated": self.total_value_generated,
        }


def _parse_owner_tokens_from_string(owners_raw: str) -> list[str]:
    """Split a multi-line / comma-separated owner cell into individual tokens."""
    tokens: list[str] = []
    for line in str(owners_raw).split("\n"):
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                tokens.append(tok)
    return tokens


def _validate_and_parse_owner_tokens(
    tokens: list[str],
    row_qty: int,
    row_index: int,
) -> Optional[list[tuple[str, int, bool]]]:
    """Validate the token list and normalise to (code, qty, explicit) triples.

    Rules:
    - If ANY token is explicit (has '-N' suffix), ALL must be explicit and
      their quantities must sum to row_qty.
    - If all tokens are implicit, there must be exactly one (the whole row
      belongs to a single owner).

    Returns None if validation fails (caller should skip the row).
    """
    token_infos = [parse_owner_token(t) for t in tokens]
    any_explicit = any(explicit for _, _, explicit in token_infos)

    if any_explicit:
        if not all(explicit for _, _, explicit in token_infos):
            logger.error(
                f"Row {row_index}: mixed explicit and implicit owner quantities; skipping"
            )
            return None
        total_spec = sum(num for _, num, _ in token_infos if num)
        if total_spec != row_qty:
            logger.error(
                f"Row {row_index}: explicit owner quantities sum to {total_spec} "
                f"but row quantity is {row_qty}; skipping"
            )
            return None
        return token_infos  # type: ignore[return-value]

    # Implicit case — must be exactly one owner
    if len(token_infos) != 1:
        logger.error(
            f"Row {row_index}: {len(token_infos)} owners with no explicit quantities — "
            "ambiguous split; skipping"
        )
        return None
    code, _, _ = token_infos[0]
    return [(code, row_qty, True)]


def _resolve_owners_with_departments(
    token_infos: list[tuple[str, int, bool]],
    departments: dict[str, dict[str, str]],
    row_index: int,
    stats: ProcessingStats,
) -> list[tuple[str, int, dict[str, str]]]:
    """Map owner codes to department dicts; skip unknown codes."""
    result: list[tuple[str, int, dict[str, str]]] = []
    for code, qty, _ in token_infos:
        dept = departments.get(code.strip())
        if not dept:
            logger.error(
                f"Row {row_index}: owner code '{code}' not found in departments; skipping owner"
            )
            stats.skip_owner()
            continue
        result.append((code.strip(), qty, dept))
    return result


def _calculate_owner_amounts(
    owners_for_row: list[tuple[str, int, dict[str, Any]]],
    unit_price: Decimal,
    row_index: int,
) -> list[Decimal]:
    """Compute each owner's monetary share, adjusting the last for rounding."""
    sums = [quantize_money(unit_price * Decimal(qty)) for _, qty, _ in owners_for_row]
    total_qty = sum(qty for _, qty, _ in owners_for_row)
    expected = quantize_money(unit_price * Decimal(total_qty))

    if sum(sums) != expected:
        diff = expected - sum(sums)
        if settings.ALLOW_ROUNDING_ADJUST and sums:
            sums[-1] = quantize_money(sums[-1] + diff)
            logger.warning(
                f"Row {row_index}: rounding discrepancy of {diff} adjusted on last owner"
            )
        else:
            logger.warning(
                f"Row {row_index}: rounding discrepancy {diff} not adjusted "
                "(ALLOW_ROUNDING_ADJUST=false)"
            )
    return sums


def _extract_asset_row_data(
    row: list[Any],
    row_index: int,
    stats: ProcessingStats,
) -> Optional[dict[str, Any]]:
    """Parse and validate a single asset row.

    Returns a dict of extracted values, or None if the row should be skipped.
    """
    required = [
        (COL_NAME, "name"),
        (COL_INVENTORY_NUMBER, "inventory_number"),
        (COL_UNIT, "unit"),
        (COL_QUANTITY, "quantity"),
        (COL_PRICE, "price"),
        (COL_OWNERS, "owners"),
    ]
    missing = validate_required_fields(row, required)
    if missing:
        logger.error(
            f"Row {row_index}: missing required fields [{', '.join(missing)}]; skipping"
        )
        stats.skip_row()
        return None

    try:
        qty = int(parse_string_number(safe_get(row, COL_QUANTITY, "")))
        price = parse_string_number(safe_get(row, COL_PRICE, ""))

        if qty <= 0:
            logger.error(
                f"Row {row_index}: quantity must be positive (got {qty}); skipping"
            )
            stats.skip_row()
            return None

        return {
            "name": str(safe_get(row, COL_NAME, "")),
            "invnum": str(safe_get(row, COL_INVENTORY_NUMBER, "")),
            "unit": str(safe_get(row, COL_UNIT, "")).lower(),
            "qty": qty,
            "price": price,
            "unit_price": quantize_money(price / Decimal(qty)),
            "owners_raw": str(safe_get(row, COL_OWNERS, "")),
        }
    except ValueError as exc:
        logger.error(f"Row {row_index}: value error — {exc}; skipping")
        stats.skip_row()
        return None
    except Exception as exc:
        logger.error(f"Row {row_index}: unexpected parse error — {exc}; skipping")
        stats.skip_row()
        return None


def load_departments(sheets_svc: Any) -> dict[str, dict[str, str]]:
    """Load and parse the Departments sheet.

    Returns a dict keyed by department code.
    """
    rows = read_sheet_values(
        sheets_svc, settings.DEPARTMENTS_SHEET_ID, settings.DEPARTMENTS_SHEET_NAME
    )
    if not rows or len(rows) < 2:
        logger.warning("Departments sheet is empty or has no data rows (after header)")
        return {}

    depts: dict[str, dict[str, str]] = {}
    for i, row in enumerate(rows[1:], start=2):
        if is_row_empty(row):
            continue

        code = str(safe_get(row, DEPT_COL_CODE, "")).strip()
        if not code:
            continue

        fullname = str(safe_get(row, DEPT_COL_FULLNAME, "")).strip()
        if not fullname:
            logger.warning(
                f"Department row {i}: code '{code}' has no full name; skipping"
            )
            continue

        receiver_fullname = str(safe_get(row, DEPT_COL_RECEIVER_FULLNAME, "")).strip()

        try:
            formatted_name = format_ukrainian_name(fullname)
        except ValueError as exc:
            logger.warning(f"Department row {i}: {exc}; skipping row")
            continue

        try:
            receiver_formatted = (
                format_ukrainian_name(receiver_fullname) if receiver_fullname else ""
            )
        except ValueError:
            receiver_formatted = ""

        depts[code] = {
            "code": str(safe_get(row, DEPT_COL_CODE, "")),
            "position": str(safe_get(row, DEPT_COL_POSITION, "")),
            "fullname": fullname,
            "formatted_name": formatted_name,
            "receiver_position": str(safe_get(row, DEPT_COL_RECEIVER_POSITION, "")),
            "receiver_fullname": receiver_fullname,
            "receiver_formatted": receiver_formatted,
        }

    logger.info(f"Loaded {len(depts)} departments from sheet")
    return depts


def parse_assets(
    sheets_svc: Any,
    departments: dict[str, dict[str, str]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse the Assets sheet and group items by owner.

    Only rows where the GENERATE_FLAG column equals 'TRUE' (case-insensitive)
    are processed.

    Returns:
        (per_owner, stats_dict) where per_owner maps owner code →
        {dept, items, tot_qty, tot_sum}
    """
    rows = read_sheet_values(
        sheets_svc, settings.ASSETS_SHEET_ID, settings.ASSETS_SHEET_NAME
    )
    if not rows or len(rows) < 2:
        logger.info("Assets sheet has no data rows")
        return {}, ProcessingStats().to_dict()

    stats = ProcessingStats()
    per_owner: dict[str, dict[str, Any]] = {}

    for rindex, row in enumerate(rows[1:], start=2):
        if is_row_empty(row):
            continue

        # Check generation flag
        flag = str(safe_get(row, COL_GENERATE_FLAG, "")).strip().upper()
        if flag != "TRUE":
            stats.skip_row()
            continue

        asset = _extract_asset_row_data(row, rindex, stats)
        if not asset:
            continue

        tokens = _parse_owner_tokens_from_string(asset["owners_raw"])
        if not tokens:
            logger.error(f"Row {rindex}: owner cell is empty; skipping")
            stats.skip_row()
            continue

        token_infos = _validate_and_parse_owner_tokens(tokens, asset["qty"], rindex)
        if not token_infos:
            stats.skip_row()
            continue

        owners = _resolve_owners_with_departments(
            token_infos, departments, rindex, stats
        )
        if not owners:
            logger.info(f"Row {rindex}: all owner codes unresolved; skipping row")
            stats.skip_row()
            continue

        owner_sums = _calculate_owner_amounts(owners, asset["unit_price"], rindex)

        for (code, oqty, dept), osum in zip(owners, owner_sums):
            if code not in per_owner:
                per_owner[code] = {
                    "dept": dept,
                    "items": [],
                    "tot_qty": 0,
                    "tot_sum": Decimal("0.00"),
                }
            per_owner[code]["items"].append(
                {
                    "name": asset["name"],
                    "inventory": asset["invnum"],
                    "unit": asset["unit"],
                    "qty": oqty,
                    "unit_price": asset["unit_price"],
                    "sum": osum,
                    "note": "",
                }
            )
            per_owner[code]["tot_qty"] += oqty
            per_owner[code]["tot_sum"] += osum
            stats.add_item(osum)

        stats.process_row()

    logger.info(
        f"Assets parsed: rows_processed={stats.rows_processed}, "
        f"rows_skipped={stats.rows_skipped}, owners={len(per_owner)}, "
        f"total_items={stats.total_items_in_acts}"
    )
    return per_owner, stats.to_dict()
