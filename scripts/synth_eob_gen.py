#!/usr/bin/env python3
"""Generate synthetic EOB claim data for LumiClaim."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "samples" / "claims_struct.json"

CPT_CATALOG: Sequence[dict[str, Any]] = (
    {"code": "99212", "billed_range": (120.0, 180.0)},
    {"code": "99213", "billed_range": (150.0, 260.0)},
    {"code": "99214", "billed_range": (220.0, 380.0)},
    {"code": "99215", "billed_range": (320.0, 520.0)},
    {"code": "97110", "billed_range": (110.0, 180.0)},
    {"code": "97530", "billed_range": (250.0, 420.0)},
    {"code": "93000", "billed_range": (80.0, 160.0)},
    {"code": "85025", "billed_range": (45.0, 95.0)},
    {"code": "80053", "billed_range": (60.0, 140.0)},
    {"code": "G0283", "billed_range": (55.0, 110.0)},
)

MODIFIERS = ("25", "59", "76", "RT", "LT", "KX", "GP", "57", "91", "79")

SCENARIOS: Sequence[dict[str, Any]] = (
    {
        "name": "baseline",
        "allowed_ratio": (0.65, 0.82),
        "insurer_ratio": (0.55, 0.75),
        "patient_ratio": (0.12, 0.25),
        "features": set(),
    },
    {
        "name": "deductible",
        "allowed_ratio": (0.6, 0.8),
        "insurer_ratio": (0.3, 0.45),
        "patient_ratio": (0.3, 0.45),
        "features": {"deductible"},
    },
    {
        "name": "duplicate_mod",
        "allowed_ratio": (0.62, 0.8),
        "insurer_ratio": (0.5, 0.7),
        "patient_ratio": (0.18, 0.3),
        "features": {"duplicate"},
    },
    {
        "name": "missing_adjustments",
        "allowed_ratio": (0.58, 0.78),
        "insurer_ratio": (0.45, 0.68),
        "patient_ratio": (0.2, 0.35),
        "features": {"missing_adjustments"},
    },
    {
        "name": "rebundled",
        "allowed_ratio": (0.6, 0.8),
        "insurer_ratio": (0.5, 0.72),
        "patient_ratio": (0.16, 0.3),
        "features": {"rebundle"},
    },
    {
        "name": "high_allowed",
        "allowed_ratio": (0.72, 0.88),
        "insurer_ratio": (0.6, 0.8),
        "patient_ratio": (0.1, 0.22),
        "features": set(),
    },
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic EOB data")
    parser.add_argument("--seed", type=int, default=42, help="Seed for deterministic output")
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA_PATH,
        help="Path to write the merged claims_struct.json",
    )
    args = parser.parse_args()

    rng = random.Random(args.seed)

    if not args.output.parent.exists():
        raise SystemExit(f"Output directory {args.output.parent} does not exist")

    if args.output.exists():
        with args.output.open("r", encoding="utf-8") as handle:
            existing: Dict[str, Any] = json.load(handle)
    else:
        existing = {}

    synthetic: Dict[str, List[dict[str, Any]]] = {}
    for index, doc_num in enumerate(range(3, 23), start=0):
        scenario = SCENARIOS[index % len(SCENARIOS)]
        doc_id = f"EOB-{doc_num:03d}"
        synthetic[doc_id] = build_document(doc_id, scenario, rng)

    merged = dict(sorted({**existing, **synthetic}.items(), key=lambda item: item[0]))

    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, sort_keys=False)
        handle.write("\n")

    print(f"Wrote {len(synthetic)} synthetic documents to {args.output}")


def build_document(doc_id: str, scenario: dict[str, Any], rng: random.Random) -> List[dict[str, Any]]:
    """Create a new synthetic EOB structure."""

    features = scenario["features"]
    num_lines = rng.randint(2, 4)

    service_lines = generate_service_lines(doc_id, num_lines, scenario, rng, features)

    totals = compute_totals(service_lines, features)
    tot_row = build_total_row(doc_id, totals, features, rng)

    return service_lines + [tot_row]


def generate_service_lines(
    doc_id: str,
    num_lines: int,
    scenario: dict[str, Any],
    rng: random.Random,
    features: Iterable[str],
) -> List[dict[str, Any]]:
    """Generate individual service lines with scenario-conditioned variations."""

    features = set(features)
    lines: List[dict[str, Any]] = []

    if "duplicate" in features and num_lines >= 2:
        base_entry = rng.choice(CPT_CATALOG)
        cpt_choices = [base_entry for _ in range(2)]
        remaining_pool = [entry for entry in CPT_CATALOG if entry is not base_entry]
        while len(cpt_choices) < num_lines:
            cpt_choices.append(rng.choice(remaining_pool))
    else:
        cpt_choices = rng.sample(CPT_CATALOG, num_lines)

    for index, catalog_entry in enumerate(cpt_choices, start=1):
        line_id = f"L{index}"
        billed = round(rng.uniform(*catalog_entry["billed_range"]), 2)
        allowed = round(billed * rng.uniform(*scenario["allowed_ratio"]), 2)

        insurer_ratio = rng.uniform(*scenario["insurer_ratio"])
        insurer_paid = round(allowed * insurer_ratio, 2)

        max_patient = max(billed - insurer_paid, 0.0)
        patient_base = allowed * rng.uniform(*scenario["patient_ratio"])
        patient_resp = round(min(patient_base, max_patient), 2)

        if "missing_adjustments" in features:
            reduction_factor = rng.uniform(0.05, 0.25)
            patient_resp = round(min(patient_resp * reduction_factor, max_patient), 2)

        adjustments_total = round(billed - insurer_paid - patient_resp, 2)
        if adjustments_total < 0:
            patient_resp = round(billed - insurer_paid, 2)
            adjustments_total = 0.0

        adjustments = build_adjustments(adjustments_total, features, rng)

        modifier = rng.choice(MODIFIERS)
        if "duplicate" in features:
            if index == 1 and modifier == "76":
                # Ensure the first duplicate line keeps a distinct modifier.
                alternative = [m for m in MODIFIERS if m != "76"]
                modifier = rng.choice(alternative)
            if index == 2:
                # Force a second modifier to highlight duplicate billing pattern.
                modifier = "76"

        line = {
            "line_id": line_id,
            "page": rng.randint(2, 4),
            "cell_id": random_cell_id(rng),
            "cpt": catalog_entry["code"],
            "modifier": modifier,
            "billed": round(billed, 2),
            "allowed": round(allowed, 2),
            "insurer_paid": round(insurer_paid, 2),
            "adjustments": adjustments,
            "patient_resp": round(patient_resp, 2),
        }

        lines.append(line)

    return lines


def build_adjustments(total: float, features: Iterable[str], rng: random.Random) -> List[dict[str, Any]]:
    """Split adjustment totals into labeled buckets with scenario-specific quirks."""

    features = set(features)
    adjustments: List[dict[str, Any]] = []

    known_total = round(total, 2)
    unknown_total = 0.0

    if "missing_adjustments" in features and total > 0:
        unknown_total = round(total * rng.uniform(0.35, 0.5), 2)
        known_total = round(total - unknown_total, 2)

    buckets: list[tuple[str, float]] = []

    if "rebundle" in features and known_total > 0:
        rebundle_amt = round(min(known_total, total * 0.25), 2)
        if rebundle_amt > 0:
            buckets.append(("rebundle", rebundle_amt))
            known_total = round(known_total - rebundle_amt, 2)

    if "deductible" in features and known_total > 0:
        deductible_amt = round(min(known_total, total * 0.2 + rng.uniform(10.0, 40.0)), 2)
        deductible_amt = min(deductible_amt, known_total)
        if deductible_amt > 0:
            buckets.append(("deductible credit", deductible_amt))
            known_total = round(known_total - deductible_amt, 2)

    if known_total > 0:
        buckets.append(("contractual", round(known_total, 2)))

    # Ensure the numeric amounts add up to the intended total (minus unknown portion).
    numeric_sum = round(sum(amount for _, amount in buckets), 2)
    delta = round(total - unknown_total - numeric_sum, 2)
    if buckets and abs(delta) >= 0.01:
        label, amount = buckets[-1]
        buckets[-1] = (label, round(amount + delta, 2))

    for label, amount in buckets:
        if amount > 0:
            adjustments.append({"type": label, "amount": round(amount, 2)})

    if unknown_total > 0 or "missing_adjustments" in features:
        adjustments.append({"type": "unclassified", "amount": None})

    return adjustments


def compute_totals(lines: Sequence[dict[str, Any]], features: Iterable[str]) -> dict[str, Any]:
    features = set(features)

    totals: dict[str, Any] = {
        "billed": 0.0,
        "allowed": 0.0,
        "insurer_paid": 0.0,
        "patient_resp": 0.0,
        "adjustments_by_type": defaultdict(float),
        "has_unknown": False,
    }

    for line in lines:
        totals["billed"] += float(line.get("billed", 0.0))
        totals["allowed"] += float(line.get("allowed", 0.0))
        totals["insurer_paid"] += float(line.get("insurer_paid", 0.0))
        totals["patient_resp"] += float(line.get("patient_resp", 0.0))

        for adj in line.get("adjustments", []):
            amount = adj.get("amount")
            if amount is None:
                totals["has_unknown"] = True
            else:
                totals["adjustments_by_type"][adj.get("type", "other")] += float(amount)

    totals["billed"] = round(totals["billed"], 2)
    totals["allowed"] = round(totals["allowed"], 2)
    totals["insurer_paid"] = round(totals["insurer_paid"], 2)
    totals["patient_resp"] = round(totals["patient_resp"], 2)

    return totals


def build_total_row(
    doc_id: str,
    totals: dict[str, Any],
    features: Iterable[str],
    rng: random.Random,
) -> dict[str, Any]:
    features = set(features)
    adjustments_list: List[dict[str, Any]] = []

    for adj_type, amount in sorted(totals["adjustments_by_type"].items()):
        if amount > 0:
            adjustments_list.append({"type": adj_type, "amount": round(amount, 2)})

    if totals["has_unknown"]:
        adjustments_list.append({"type": "unclassified", "amount": None})

    total_adjustments_value = round(
        sum(item["amount"] for item in adjustments_list if item["amount"] is not None), 2
    )

    # Derive allowed amount from billed minus contractual adjustments when available.
    contractual_amount = next(
        (item["amount"] for item in adjustments_list if item.get("type") == "contractual"),
        None,
    )
    if contractual_amount is not None:
        allowed = round(totals["billed"] - contractual_amount, 2)
    else:
        allowed = totals["allowed"]

    total_row = {
        "line_id": "TOTAL",
        "page": rng.randint(2, 4),
        "cell_id": random_cell_id(rng),
        "cpt": "",
        "modifier": "",
        "billed": totals["billed"],
        "allowed": round(allowed, 2),
        "insurer_paid": totals["insurer_paid"],
        "adjustments": adjustments_list,
        "patient_resp": totals["patient_resp"],
    }

    # Record aggregate adjustments when none were captured numerically.
    if not adjustments_list and total_adjustments_value > 0:
        total_row["adjustments"].append(
            {"type": "contractual", "amount": round(total_adjustments_value, 2)}
        )

    return total_row


def random_cell_id(rng: random.Random) -> str:
    table_id = rng.randint(2, 6)
    row = rng.randint(4, 18)
    col = rng.randint(2, 6)
    return f"tbl{table_id}:R{row}C{col}"


if __name__ == "__main__":
    main()
