"""Offline preflight checks for Taiwan Post shipments."""

import json
import re
import sys
from decimal import Context, Decimal, DecimalException, Inexact, localcontext
from pathlib import Path

RULESET = "epacket-2023-08-preflight-v1"
RULESETS = {
    "epacket": RULESET,
    "ems": "twpost-ems-2026-11-v1",
    "international-parcel": "twpost-international-parcel-2026-11-v1",
    "domestic-parcel": "twpost-domestic-parcel-2026-11-v1",
}
SELECTOR_RULESET = "twpost-mail-type-v1"
MAX_INPUT_BYTES = 1024 * 1024
MAX_PARCELS = 100
MAX_ITEMS = 5
MAX_MEASUREMENT_PLACES = 128
DIMENSIONS = ("lengthCm", "widthCm", "heightCm")

# Route entries are (weight kg, longest side cm, length plus girth cm).
# The source tables and checked date are listed in README.md.
EMS_LIMITS = {
    "AU": (20, 105, 200),
    "CA": (30, 150, 300),
    "DE": (30, 150, 300),
    "GB": (30, 150, 300),
    "HK": (30, 150, 300),
    "JP": (30, 150, 300),
    "KR": (30, 150, 300),
    "MO": (20, 105, 200),
    "SG": (30, 150, 300),
    "US": (30, 152, 274),
}
PARCEL_LIMITS = {
    "air": {
        "AU": (20, 105, 200),
        "CA": (30, 150, 300),
        "DE": (30, 105, 200),
        "FR": (30, 105, 200),
        "GB": (30, 150, 300),
        "HK": (30, 150, 300),
        "JP": (30, 150, 300),
        "KR": (20, 150, 300),
        "MO": (30, 150, 300),
        "SG": (30, 150, 300),
        "US": (30, 152, 274),
    },
    "surface": {
        "AU": (20, 105, 200),
        "CA": (20, 150, 300),
        "FR": (20, 150, 300),
        "JP": (30, 150, 300),
        "MY": (10, 150, 300),
        "SG": (20, 150, 300),
        "TH": (30, 150, 300),
        "US": (30, 152, 274),
        "VN": (10, 150, 300),
    },
    "sal": {
        "CA": (20, 150, 300),
        "PR": (20, 105, 200),
        "US": (30, 152, 274),
    },
}
DOMESTIC_PROFILES = ("standard", "restricted-area", "indivisible")
PARCEL_SELECTORS = ("mailType", "destinationCountry", "transport", "domesticProfile", "contentType")


def positive_number(value):
    if type(value) is int:
        return value > 0
    return isinstance(value, Decimal) and value.is_finite() and value > 0


def positive_measurement(value):
    return positive_number(value) and (
        not isinstance(value, Decimal) or value.as_tuple().exponent >= -MAX_MEASUREMENT_PLACES
    )


def total_exceeds(values, limit):
    # The largest possible sum is 40 line weights below 1000 kg each.
    with localcontext(Context(prec=MAX_MEASUREMENT_PLACES + 5)) as context:
        context.traps[Inexact] = True
        return sum(values) > limit


def batch_mail_type(batch):
    if not isinstance(batch, dict) or "mailType" not in batch:
        return "epacket"
    mail_type = batch["mailType"]
    return mail_type if isinstance(mail_type, str) and mail_type in RULESETS else None


def route_limits(parcel, path, mail_type, issue):
    country = parcel.get("destinationCountry")
    valid_country = isinstance(country, str) and re.fullmatch(r"[A-Z]{2}", country)
    if not valid_country or country in ("EU", "UK", "XX", "ZZ"):
        issue(f"{path}.destinationCountry", "DESTINATION_COUNTRY")
        country = None
    elif country in ("TW", "CN"):
        issue(f"{path}.destinationCountry", "DESTINATION_OUT_OF_SCOPE")
        country = None

    if mail_type == "international-parcel":
        transport = parcel.get("transport")
        if not isinstance(transport, str) or transport not in PARCEL_LIMITS:
            issue(f"{path}.transport", "TRANSPORT")
            return None
        routes = PARCEL_LIMITS[transport]
    else:
        routes = EMS_LIMITS

    if country is None:
        return None
    limits = routes.get(country)
    if limits is None:
        issue(path, "ROUTE_LIMITS_UNCHECKED", "warn")
    return limits


def check_dimensions(parcel, path, mail_type, limits, domestic_profile, issue):
    sides = []
    for field in DIMENSIONS:
        side = parcel.get(field)
        if positive_measurement(side):
            sides.append(side)
        else:
            issue(f"{path}.{field}", "DIMENSION_NUMBER")
    if len(sides) != len(DIMENSIONS):
        return

    length, width, height = sorted(sides, reverse=True)
    if mail_type == "epacket":
        outside = length > 60 or length < 14 or width < 9 or total_exceeds(sides, 90)
    elif mail_type == "domestic-parcel":
        if domestic_profile is None:
            return
        if domestic_profile == "indivisible":
            outside = length > 150 or total_exceeds((length, width, width, height, height), 300)
        else:
            maximum = 120 if domestic_profile == "restricted-area" else 150
            outside = length > maximum or total_exceeds(sides, maximum)
        outside = outside or length < 14 or width < 9
    else:
        # Article 48 refers to the letter minimum, including its 2 mm tolerance.
        outside = mail_type == "international-parcel" and (
            length < Decimal("13.8") or width < Decimal("8.8")
        )
        if limits is not None:
            _, max_length, max_girth = limits
            outside = outside or length > max_length or total_exceeds(
                (length, width, width, height, height), max_girth
            )

    if outside:
        issue(path, "DIMENSION_LIMITS")


def check_items(parcel, path, mail_type, comparable_weight, issue):
    if mail_type == "ems":
        content_type = parcel.get("contentType", "goods")
        if content_type not in ("goods", "documents"):
            issue(f"{path}.contentType", "CONTENT_TYPE")
            return
        if content_type == "documents":
            if "items" in parcel and parcel["items"] != []:
                issue(f"{path}.items", "DOCUMENT_ITEMS")
            return

    items = parcel.get("items")
    max_items = MAX_ITEMS if mail_type == "epacket" else 40
    if not isinstance(items, list) or not 1 <= len(items) <= max_items:
        issue(f"{path}.items", "ITEM_COUNT")
        return

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

        if mail_type != "epacket":
            continue
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

    if comparable_weight is not None and comparable_weight >= 1000:
        issue(f"{path}.items", "ITEM_WEIGHT_TOTAL_UNCHECKED", "warn")
    elif comparable_weight is not None and len(line_weights) == len(items) and (
        any(line > comparable_weight for line in line_weights)
        or total_exceeds(line_weights, comparable_weight)
    ):
        issue(f"{path}.items", "ITEM_WEIGHT_TOTAL")


def validate_batch(batch):
    issues = []

    def issue(path, code, level="fail"):
        issues.append({"path": path, "code": code, "level": level})

    mail_type = batch_mail_type(batch)
    if mail_type is None:
        issue("$.mailType", "MAIL_TYPE")
        return issues

    parcels = batch.get("parcels") if isinstance(batch, dict) else None
    if not isinstance(parcels, list) or not 1 <= len(parcels) <= MAX_PARCELS:
        issue("$.parcels", "PARCEL_COUNT")
        return issues

    allowed_fields = {
        "epacket": (),
        "ems": ("destinationCountry", "contentType"),
        "international-parcel": ("destinationCountry", "transport"),
        "domestic-parcel": ("domesticProfile",),
    }[mail_type]
    explicit_mail_type = "mailType" in batch
    if explicit_mail_type:
        for field in PARCEL_SELECTORS[1:]:
            if field in batch:
                issue(f"$.{field}", "MAIL_FIELD_SCOPE")

    for index, parcel in enumerate(parcels):
        path = f"$.parcels[{index}]"
        if not isinstance(parcel, dict):
            issue(path, "PARCEL_OBJECT")
            continue

        if explicit_mail_type:
            for field in PARCEL_SELECTORS:
                if field in parcel and field not in allowed_fields:
                    issue(f"{path}.{field}", "MAIL_FIELD_SCOPE")

        limits = None
        domestic_profile = None
        if mail_type == "epacket":
            max_weight = 2
        elif mail_type == "domestic-parcel":
            domestic_profile = parcel.get("domesticProfile")
            if domestic_profile not in DOMESTIC_PROFILES:
                issue(f"{path}.domesticProfile", "DOMESTIC_PROFILE")
                domestic_profile = None
            elif domestic_profile == "indivisible":
                issue(f"{path}.domesticProfile", "INDIVISIBLE_ELIGIBILITY_UNCHECKED", "warn")
            max_weight = {
                "standard": 20,
                "restricted-area": 20,
                "indivisible": 30,
            }.get(domestic_profile)
        else:
            limits = route_limits(parcel, path, mail_type, issue)
            max_weight = limits[0] if limits else None

        weight = parcel.get("weightKg")
        valid_weight = positive_measurement(weight) and (max_weight is None or weight <= max_weight)
        if not valid_weight:
            issue(f"{path}.weightKg", "PARCEL_WEIGHT")
        check_dimensions(parcel, path, mail_type, limits, domestic_profile, issue)
        if mail_type != "domestic-parcel":
            check_items(parcel, path, mail_type, weight if valid_weight else None, issue)

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
        batch = read_batch(args[0])
        issues = validate_batch(batch)
    except (OSError, ValueError, RecursionError, DecimalException):
        print("Input could not be processed. Provide one readable UTF-8 JSON file up to 1 MiB.", file=sys.stderr)
        return 2

    failed = any(item["level"] == "fail" for item in issues)
    status = "fail" if failed else "warn" if issues else "pass"
    ruleset = RULESETS.get(batch_mail_type(batch), SELECTOR_RULESET)
    print(json.dumps({"ruleset": ruleset, "status": status, "issues": issues}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
