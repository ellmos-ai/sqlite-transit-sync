"""Validate the synthetic BACH compatibility contract without contacting BACH."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

SCHEMA = "sqlite-transit-sync.bach-compatibility-fixtures.v1"
REPORT_SCHEMA = "sqlite-transit-sync.bach-compatibility-report.v1"
REQUIRED = (
    "input_contract",
    "expected_bach_semantics",
    "standalone_result",
    "intentional_deviation",
    "migration_risk",
)


def compare_fixtures(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        raise ValueError("fixture schema mismatch")
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("fixtures must contain scenarios")
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict) or not isinstance(scenario.get("name"), str):
            raise ValueError("scenario must have a name")
        missing = [key for key in REQUIRED if key not in scenario]
        if missing:
            raise ValueError(f"scenario {scenario.get('name')!r} missing {missing}")
        expected = scenario["expected_bach_semantics"]
        if not isinstance(expected, dict) or expected.get("status") != "awaiting_authorized_reference":
            raise ValueError(f"scenario {scenario['name']!r} is not blocked")
        results.append(
            {
                "name": scenario["name"],
                "status": "blocked_no_authorized_bach_golden",
                "input_contract": scenario["input_contract"],
                "expected_bach_semantics": expected,
                "standalone_result": scenario["standalone_result"],
                "intentional_deviation": scenario["intentional_deviation"],
                "migration_risk": scenario["migration_risk"],
            }
        )
    return {
        "schema": REPORT_SCHEMA,
        "status": "blocked_no_authorized_bach_golden",
        "fixture_count": len(results),
        "scenarios": results,
        "adapter_recommendation": "do_not_implement",
        "migration_recommendation": (
            "Obtain an authorized BACH golden result for every scenario, compare exact semantics, "
            "and resolve all differences before implementing an adapter."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "golden" / "bach_compatibility_fixtures.json",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = compare_fixtures(args.input)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
