import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from preflight import MAX_INPUT_BYTES, MAX_MEASUREMENT_PLACES, RULESET, RULESETS, validate_batch

ROOT = Path(__file__).resolve().parent


def item(**overrides):
    return {
        "name": "Synthetic item",
        "quantity": 2,
        "weightKg": Decimal("0.1"),
        "unitPrice": 10,
        "hsCode": "0000.00.00.00",
        **overrides,
    }


def parcel(**overrides):
    return {
        "weightKg": 2,
        "lengthCm": 60,
        "widthCm": 21,
        "heightCm": 9,
        "items": [item()],
        **overrides,
    }


class PreflightTests(unittest.TestCase):
    def codes(self, sample):
        return {entry["code"] for entry in validate_batch(sample)}

    def test_parcel_count(self):
        for count in (0, 1, 100, 101):
            with self.subTest(count=count):
                expected = set() if 1 <= count <= 100 else {"PARCEL_COUNT"}
                self.assertEqual(self.codes({"parcels": [parcel()] * count}), expected)

    def test_item_count(self):
        for count in (0, 1, 5, 6):
            with self.subTest(count=count):
                expected = set() if 1 <= count <= 5 else {"ITEM_COUNT"}
                self.assertEqual(self.codes({"parcels": [parcel(items=[item()] * count)]}), expected)

    def test_parcel_weight(self):
        self.assertEqual(self.codes({"parcels": [parcel(weightKg=2)]}), set())
        for weight in (0, True, "2", Decimal("2.001")):
            with self.subTest(weight=weight):
                self.assertIn("PARCEL_WEIGHT", self.codes({"parcels": [parcel(weightKg=weight)]}))

    def test_dimensions(self):
        for sides in ((60, 21, 9), (1, 9, 14)):
            sample = parcel(lengthCm=sides[0], widthCm=sides[1], heightCm=sides[2])
            self.assertEqual(self.codes({"parcels": [sample]}), set())
        for sides in ((Decimal("60.001"), 14, 9), (60, 21, Decimal("9.001")),
                      (Decimal("13.99"), 9, 1), (14, Decimal("8.99"), 1)):
            with self.subTest(sides=sides):
                sample = parcel(lengthCm=sides[0], widthCm=sides[1], heightCm=sides[2])
                self.assertEqual(self.codes({"parcels": [sample]}), {"DIMENSION_LIMITS"})

    def test_quantity_and_required_types(self):
        for quantity in (False, "2", -1, 0, Decimal("1.1")):
            with self.subTest(quantity=quantity):
                self.assertIn("ITEM_QUANTITY", self.codes({"parcels": [parcel(items=[item(quantity=quantity)])]}))
        self.assertEqual(self.codes({"parcels": [parcel(items=[item(quantity=Decimal("2.0"))])]}), set())
        sample = parcel(widthCm=None, items=[item(name=" ", weightKg="0.1", unitPrice=True)])
        self.assertEqual(self.codes({"parcels": [sample]}),
                         {"DIMENSION_NUMBER", "ITEM_NAME", "ITEM_WEIGHT", "ITEM_UNIT_PRICE"})

    def test_item_weight_is_per_line_and_decimal(self):
        items = [item(quantity=8), item(weightKg=Decimal("0.2"))]
        self.assertEqual(self.codes({"parcels": [parcel(weightKg=Decimal("0.3"), items=items)]}), set())
        items.append(item(weightKg=Decimal("1e-50")))
        self.assertEqual(self.codes({"parcels": [parcel(weightKg=Decimal("0.3"), items=items)]}),
                         {"ITEM_WEIGHT_TOTAL"})

    def test_precise_equal_totals_pass(self):
        items = [
            item(weightKg=Decimal("0.33333333333333333333333333333")),
            item(weightKg=Decimal("0.66666666666666666666666666667")),
        ]
        sample = parcel(weightKg=1, items=items,
                        lengthCm=Decimal("59.99999999999999999999999999999"),
                        widthCm=Decimal("21.00000000000000000000000000001"))
        self.assertEqual(self.codes({"parcels": [sample]}), set())

    def test_measurement_precision_limit(self):
        tiny = Decimal(f"1e-{MAX_MEASUREMENT_PLACES}")
        sample = parcel(weightKg=tiny, items=[item(weightKg=tiny)])
        self.assertEqual(self.codes({"parcels": [sample]}), set())

        too_precise = Decimal(f"1e-{MAX_MEASUREMENT_PLACES + 1}")
        sample = parcel(weightKg=too_precise, heightCm=too_precise, items=[item(weightKg=too_precise)])
        self.assertEqual(self.codes({"parcels": [sample]}),
                         {"PARCEL_WEIGHT", "DIMENSION_NUMBER", "ITEM_WEIGHT"})

    def test_ccc_is_format_only(self):
        for ccc, expected in (("0000.00.00.00", set()), ("00000000000", {"CCC_CHECK_DIGIT_UNVERIFIED"}),
                              (None, {"CCC_MISSING"}), (" ", {"CCC_MISSING"}),
                              ("123456789", {"CCC_FORMAT"}), ("123456789012", {"CCC_FORMAT"}),
                              ("123456789X", {"CCC_FORMAT"}), (1234567890, {"CCC_FORMAT"})):
            with self.subTest(ccc=ccc):
                self.assertEqual(self.codes({"parcels": [parcel(items=[item(hsCode=ccc)])]}), expected)

    def test_mail_type_selection_and_legacy_output(self):
        old = {"parcels": [parcel(items=[item(hsCode=None, weightKg=1)])]}
        explicit = {**old, "mailType": "epacket"}
        expected = {"ruleset": RULESET, "status": "warn", "issues": [
            {"path": "$.parcels[0].items[0].hsCode", "code": "CCC_MISSING", "level": "warn"}
        ]}
        self.assertEqual(self.run_cli(json.dumps(old).encode()).stdout, json.dumps(expected) + "\n")
        self.assertEqual(self.run_cli(json.dumps(explicit).encode()).stdout, json.dumps(expected) + "\n")
        old["parcels"][0]["mailType"] = "ems"
        self.assertEqual(self.codes(old), {"CCC_MISSING"})
        self.assertEqual(self.codes(explicit), {"CCC_MISSING", "MAIL_FIELD_SCOPE"})
        misplaced = {"mailType": "ems", "destinationCountry": "JP",
                     "parcels": [parcel(destinationCountry="JP")]}
        self.assertEqual(validate_batch(misplaced),
                         [{"path": "$.destinationCountry", "code": "MAIL_FIELD_SCOPE", "level": "fail"}])
        for selector in (None, False, 1, [], {}, "", "EMS", " ems", "PRIVATE_SELECTOR"):
            with self.subTest(selector=selector):
                result = self.run_cli(json.dumps({**old, "mailType": selector}).encode())
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["issues"],
                                 [{"path": "$.mailType", "code": "MAIL_TYPE", "level": "fail"}])
                self.assertNotIn("PRIVATE_SELECTOR", result.stdout + result.stderr)

    def test_international_service_limits_are_route_specific(self):
        cases = (
            ("ems", {"destinationCountry": "AU"}, 20, 105, 200),
            ("ems", {"destinationCountry": "US"}, 30, 152, 274),
            ("ems", {"destinationCountry": "DE"}, 30, 150, 300),
            ("international-parcel", {"destinationCountry": "DE", "transport": "air"}, 30, 105, 200),
            ("international-parcel", {"destinationCountry": "KR", "transport": "air"}, 20, 150, 300),
            ("international-parcel", {"destinationCountry": "SG", "transport": "air"}, 30, 150, 300),
            ("international-parcel", {"destinationCountry": "SG", "transport": "surface"}, 20, 150, 300),
            ("international-parcel", {"destinationCountry": "CA", "transport": "surface"}, 20, 150, 300),
            ("international-parcel", {"destinationCountry": "FR", "transport": "surface"}, 20, 150, 300),
            ("international-parcel", {"destinationCountry": "PR", "transport": "sal"}, 20, 105, 200),
        )
        for service, route, weight, longest, total in cases:
            with self.subTest(service=service, route=route):
                width = (total - longest - 2) // 2
                height = Decimal(total - longest) / 2 - width
                package = parcel(**route, weightKg=weight, lengthCm=height,
                                 widthCm=longest, heightCm=width)
                batch = {"mailType": service, "parcels": [package]}
                self.assertEqual(self.codes(batch), set())
                self.assertEqual(self.codes({**batch, "parcels": [
                    {**package, "weightKg": Decimal(weight) + Decimal("0.001"),
                     "lengthCm": height + Decimal("0.001")}
                ]}), {"PARCEL_WEIGHT", "DIMENSION_LIMITS"})
                self.assertEqual(self.codes({**batch, "parcels": [
                    {**package, "widthCm": Decimal(longest) + Decimal("0.001"), "heightCm": 10}
                ]}), {"DIMENSION_LIMITS"})

    def test_unknown_and_invalid_routes(self):
        shipment = parcel(destinationCountry="JP", transport="sal", weightKg=80,
                          lengthCm=300, items=[item(hsCode=None)])
        batch = {"mailType": "international-parcel", "parcels": [shipment]}
        self.assertEqual(self.codes(batch), {"ROUTE_LIMITS_UNCHECKED"})
        shipment["items"] = [item(weightKg=81)]
        self.assertEqual(self.codes(batch), {"ROUTE_LIMITS_UNCHECKED", "ITEM_WEIGHT_TOTAL"})
        shipment.update(destinationCountry="jp", transport=[])
        self.assertEqual(self.codes(batch), {"DESTINATION_COUNTRY", "TRANSPORT", "ITEM_WEIGHT_TOTAL"})
        shipment.update(transport="air", items=[item()])
        for country in ("TW", "CN", "UK", "EU", "XX", "ZZ"):
            with self.subTest(country=country):
                shipment["destinationCountry"] = country
                expected = "DESTINATION_OUT_OF_SCOPE" if country in ("TW", "CN") else "DESTINATION_COUNTRY"
                self.assertEqual(self.codes(batch), {expected})
        shipment.update(destinationCountry="JP", transport="sal", weightKg=Decimal("1e9999999"))
        self.assertEqual(self.codes(batch), {"ROUTE_LIMITS_UNCHECKED", "ITEM_WEIGHT_TOTAL_UNCHECKED"})

    def test_parcel_minimum_without_route_limits(self):
        shipment = parcel(destinationCountry="JP", transport="sal",
                          lengthCm=Decimal("13.8"), widthCm=Decimal("8.8"), heightCm=1)
        batch = {"mailType": "international-parcel", "parcels": [shipment]}
        self.assertEqual(self.codes(batch), {"ROUTE_LIMITS_UNCHECKED"})
        shipment["widthCm"] = Decimal("8.799")
        self.assertEqual(self.codes(batch), {"ROUTE_LIMITS_UNCHECKED", "DIMENSION_LIMITS"})

    def test_validate_batch_preserves_decimal_input_contract(self):
        self.assertEqual(self.codes({"parcels": [parcel(weightKg=1.5)]}), {"PARCEL_WEIGHT"})
        self.assertEqual(self.codes({"parcels": [parcel(weightKg=Decimal("1.5"))]}), set())

    def test_ems_document_and_goods_inputs(self):
        shipment = parcel(destinationCountry="JP", weightKg=3, contentType="documents")
        del shipment["items"]
        batch = {"mailType": "ems", "parcels": [shipment]}
        self.assertEqual(self.codes(batch), set())
        self.assertEqual(self.codes({**batch, "parcels": [
            {**shipment, "destinationCountry": "BR", "weightKg": 1000}
        ]}), {"ROUTE_LIMITS_UNCHECKED"})
        shipment["items"] = [item()]
        self.assertEqual(self.codes(batch), {"DOCUMENT_ITEMS"})
        shipment["items"] = []
        self.assertEqual(self.codes(batch), set())
        shipment["contentType"] = None
        self.assertEqual(self.codes(batch), {"CONTENT_TYPE"})
        shipment["contentType"] = "goods"
        shipment["items"] = [item(weightKg=Decimal("0.075"), hsCode="unverified")] * 40
        self.assertEqual(self.codes(batch), set())
        shipment["items"].append(item())
        self.assertEqual(self.codes(batch), {"ITEM_COUNT"})

    def test_domestic_profiles_do_not_apply_customs_rules(self):
        shipment = parcel(domesticProfile="standard", weightKg=20, lengthCm=70, widthCm=45, heightCm=35,
                          items=[item(hsCode=None)])
        batch = {"mailType": "domestic-parcel", "parcels": [shipment]}
        self.assertEqual(self.codes(batch), set())
        shipment["domesticProfile"] = "restricted-area"
        self.assertEqual(self.codes(batch), {"DIMENSION_LIMITS"})
        shipment["heightCm"] = 5
        self.assertEqual(self.codes(batch), set())
        shipment.update(domesticProfile="indivisible", weightKg=30, lengthCm=150, widthCm=50, heightCm=25)
        self.assertEqual(self.codes(batch), {"INDIVISIBLE_ELIGIBILITY_UNCHECKED"})
        shipment.update(weightKg=Decimal("30.001"), heightCm=Decimal("25.001"))
        self.assertEqual(self.codes(batch), {"INDIVISIBLE_ELIGIBILITY_UNCHECKED", "PARCEL_WEIGHT", "DIMENSION_LIMITS"})
        shipment["domesticProfile"] = None
        self.assertEqual(self.codes(batch), {"DOMESTIC_PROFILE"})
        shipment.update(domesticProfile="standard", weightKg=True, widthCm="5", transport="air")
        self.assertEqual(self.codes(batch), {"MAIL_FIELD_SCOPE", "PARCEL_WEIGHT", "DIMENSION_NUMBER"})

    def test_new_service_report_rulesets(self):
        for service in ("ems", "international-parcel", "domestic-parcel"):
            with self.subTest(service=service):
                result = self.run_command(str(ROOT / "examples" / f"{service}.json"))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout),
                                 {"ruleset": RULESETS[service], "status": "pass", "issues": []})

    def run_cli(self, payload):
        with tempfile.NamedTemporaryFile(
            dir=os.environ.get("EPACKET_TEST_TMPDIR"), suffix=".json", delete=False
        ) as file:
            source = Path(file.name)
            self.addCleanup(source.unlink, missing_ok=True)
            file.write(payload)
        return self.run_command(str(source))

    def run_command(self, *args):
        return subprocess.run(
            [sys.executable, "-B", str(ROOT / "preflight.py"), *args],
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_cli_pass_warn_fail(self):
        batch = json.loads((ROOT / "examples" / "batch.json").read_text(encoding="utf-8"))
        product = batch["parcels"][0]["items"][0]
        for ccc, status, code in (("0000000000", "pass", 0), (None, "warn", 0), ("bad", "fail", 1)):
            with self.subTest(status=status):
                product["hsCode"] = ccc
                result = self.run_cli(json.dumps(batch).encode("utf-8-sig"))
                self.assertEqual(result.returncode, code)
                self.assertEqual(result.stderr, "")
                report = json.loads(result.stdout)
                self.assertEqual((report["ruleset"], report["status"]), (RULESET, status))

    def test_cli_accepts_exact_json_totals(self):
        result = self.run_cli(b"""{
          "parcels": [{"weightKg": 2, "lengthCm": 1e-27, "widthCm": 50,
            "heightCm": 39.999999999999999999999999999, "items": [
              {"name": "A", "quantity": 1, "unitPrice": 1, "weightKg": 1e-28, "hsCode": "0000000000"},
              {"name": "B", "quantity": 2.0, "unitPrice": 1, "weightKg": 1, "hsCode": "0000000000"},
              {"name": "C", "quantity": 1e2, "unitPrice": 1,
                "weightKg": 0.9999999999999999999999999999, "hsCode": "0000000000"}
            ]}]
        }""")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["status"], "pass")

    def test_cli_treats_large_json_integer_as_a_rule_failure(self):
        result = self.run_cli(b'{"parcels":[{"weightKg":1' + b"0" * 4300 + b"}]}")
        self.assertEqual(result.returncode, 1)
        codes = {entry["code"] for entry in json.loads(result.stdout)["issues"]}
        self.assertIn("PARCEL_WEIGHT", codes)

    def test_cli_usage(self):
        self.assertEqual(self.run_command("--help").returncode, 0)
        for args in ((), ("first.json", "second.json")):
            result = self.run_command(*args)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")

    def test_input_errors_and_reports_never_echo_payload(self):
        canary = "PRIVATE_INPUT_CANARY"
        malformed = (
            b'{"parcels": [], "parcels": []}',
            b'{"value": NaN}',
            b'{"value": 1e999999999999999999999}',
            b"[" * 10_000 + b"]" * 10_000,
            b"\xff",
            f'{{"name":"{canary}"'.encode(),
            b" " * (MAX_INPUT_BYTES + 1),
        )
        for index, payload in enumerate(malformed):
            with self.subTest(index=index):
                result = self.run_cli(payload)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn(canary, result.stderr)
        missing = self.run_command(str(ROOT / f"{canary}.json"))
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn(canary, missing.stdout + missing.stderr)
        result = self.run_cli(json.dumps({"parcels": [{"weightKg": canary, "address": canary}]}).encode())
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(canary, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
