"""Offline preflight checks for the legacy ePacket batch workflow."""

import json
import re
import sys
from decimal import Context, Decimal, DecimalException, Inexact, localcontext
from pathlib import Path

RULESET = "epacket-2023-08-preflight-v1"
MAX_INPUT_BYTES = 1024 * 1024
MAX_PARCELS = 100
MAX_ITEMS = 5
MAX_MEASUREMENT_PLACES = 128
DIMENSIONS = ("lengthCm", "widthCm", "heightCm")


def positive_number(value):
    if type(value) is int:
        return value > 0
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def positive_measurement(value):
    return positive_number(value) and (
        not isinstance(value, Decimal) or value.as_tuple().exponent >= -MAX_MEASUREMENT_PLACES
    )


def total_exceeds(values, limit):
    # Checked measurements have at most 128 fractional places, and the sum is below 1000.
    with localcontext(Context(prec=MAX_MEASUREMENT_PLACES + 3)) as context:
        context.traps[Inexact] = True
        return sum(values) > limit


def validate_batch(batch):
    issues = []

    def issue(path, code, level="fail"):
        issues.append({"path": path, "code": code, "level": level})

    parcels = batch.get("parcels") if isinstance(batch, dict) else None
    if not isinstance(parcels, list) or not 1 <= len(parcels) <= MAX_PARCELS:
        issue("$.parcels", "PARCEL_COUNT")
        return issues

    for index, parcel in enumerate(parcels):
        path = f"$.parcels[{index}]"
        if not isinstance(parcel, dict):
            issue(path, "PARCEL_OBJECT")
            continue

        weight = parcel.get("weightKg")
        valid_weight = positive_measurement(weight) and weight <= 2
        if not valid_weight:
            issue(f"{path}.weightKg", "PARCEL_WEIGHT")

        sides = []
        for field in DIMENSIONS:
            side = parcel.get(field)
            if positive_measurement(side):
                sides.append(side)
            else:
                issue(f"{path}.{field}", "DIMENSION_NUMBER")
        if len(sides) == len(DIMENSIONS):
            longest, next_longest, _ = sorted(sides, reverse=True)
            if longest > 60 or longest < 14 or next_longest < 9 or total_exceeds(sides, 90):
                issue(path, "DIMENSION_LIMITS")

        items = parcel.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
            issue(f"{path}.items", "ITEM_COUNT")
            continue

        line_weights = []
        for item_index, item in enumerate(items):
            item_path = f"{path}.items[{item_index}]"
            if not isinstance(item, dict):
                issue(item_path, "ITEM_OBJECT")
                continue

            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                issue(f"{item_path}.name", "ITEM_NAME")
            quantity = item.get("quantity")
            if not positive_number(quantity) or (
                isinstance(quantity, Decimal) and quantity != quantity.to_integral_value()
            ):
                issue(f"{item_path}.quantity", "ITEM_QUANTITY")
            if not positive_number(item.get("unitPrice")):
                issue(f"{item_path}.unitPrice", "ITEM_UNIT_PRICE")

            line_weight = item.get("weightKg")
            if positive_measurement(line_weight):
                line_weights.append(line_weight)
            else:
                issue(f"{item_path}.weightKg", "ITEM_WEIGHT")

            ccc = item.get("hsCode")
            ccc_path = f"{item_path}.hsCode"
            if ccc is None or (isinstance(ccc, str) and not ccc.strip()):
                issue(ccc_path, "CCC_MISSING", "warn")
            elif isinstance(ccc, str):
                compact = re.sub(r"[\s.\-]", "", ccc)
                if re.fullmatch(r"[0-9]{11}", compact):
                    issue(ccc_path, "CCC_CHECK_DIGIT_UNVERIFIED", "warn")
                elif not re.fullmatch(r"[0-9]{10}", compact):
                    issue(ccc_path, "CCC_FORMAT")
            else:
                issue(ccc_path, "CCC_FORMAT")

        if valid_weight and len(line_weights) == len(items) and (
            any(line > weight for line in line_weights) or total_exceeds(line_weights, weight)
        ):
            issue(f"{path}.items", "ITEM_WEIGHT_TOTAL")

    return issues


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("Non-JSON number")


def read_batch(path):
    with Path(path).open("rb") as source:
        data = source.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise ValueError("Input too large")
    return json.loads(
        data.decode("utf-8-sig"),
        parse_float=Decimal,
        parse_int=Decimal,
        parse_constant=reject_constant,
        object_pairs_hook=unique_object,
    )


def main(args):
    if args == ["--help"]:
        print("Usage: python preflight.py INPUT.json")
        return 0
    if len(args) != 1:
        print("Usage: python preflight.py INPUT.json", file=sys.stderr)
        return 2

    try:
        issues = validate_batch(read_batch(args[0]))
    except (OSError, ValueError, RecursionError, DecimalException):
        print("Input could not be processed. Provide one readable UTF-8 JSON file up to 1 MiB.", file=sys.stderr)
        return 2

    failed = any(item["level"] == "fail" for item in issues)
    status = "fail" if failed else "warn" if issues else "pass"
    print(json.dumps({"ruleset": RULESET, "status": status, "issues": issues}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
