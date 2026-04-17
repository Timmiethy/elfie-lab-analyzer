#!/usr/bin/env python3
"""Diagnostic: identify where analytes fail to resolve."""

import json
import sys
from pathlib import Path

# Common OCR variations that labs produce
TEST_CASES = [
    # Hematology
    ("WBC", "hematology"),
    ("White blood cell count", "hematology"),
    ("WBC Count", "hematology"),
    ("RBC", "hematology"),
    ("Red Blood Cell", "hematology"),
    ("Hemoglobin", "hematology"),
    ("HGB", "hematology"),
    ("Hemoglobin A1c", "glycemia"),
    ("HbA1C", "glycemia"),
    ("HBA1C", "glycemia"),
    ("Hb A1c", "glycemia"),
    ("A1C", "glycemia"),

    # Chemistry
    ("Glucose, Fasting", "glycemia"),
    ("Fasting Glucose", "glycemia"),
    ("Blood Glucose", "glycemia"),
    ("Glucose (Fasting)", "glycemia"),
    ("Glucose-Fasting", "glycemia"),

    ("Sodium, Na", "chemistry"),
    ("Na+", "chemistry"),
    ("Sodium (Na)", "chemistry"),

    ("Potassium, K", "chemistry"),
    ("K+", "chemistry"),
    ("Potassium (K)", "chemistry"),

    ("Creatinine", "chemistry"),
    ("CREAT", "chemistry"),
    ("Creat.", "chemistry"),

    ("eGFR", "chemistry"),
    ("eGFR (CKD-EPI)", "chemistry"),
    ("eGFR ckd epi", "chemistry"),
    ("Estimated GFR", "chemistry"),

    ("Total Cholesterol", "lipids"),
    ("Cholesterol, Total", "lipids"),
    ("Total Chol", "lipids"),

    ("LDL", "lipids"),
    ("LDL-C", "lipids"),
    ("LDL Cholesterol", "lipids"),
    ("Low Density Lipoprotein", "lipids"),

    ("HDL", "lipids"),
    ("HDL-C", "lipids"),
    ("HDL Cholesterol", "lipids"),

    ("Triglycerides", "lipids"),
    ("Trig", "lipids"),

    # Edge cases
    ("Glucose  (fasting)", "glycemia"),  # double space
    ("GLUCOSE,FASTING", "glycemia"),  # no space after comma
    ("glucose-fasting", "glycemia"),  # dash instead of comma
    ("wbc/l", "hematology"),  # with unit
    ("rbc count [est]", "hematology"),  # with estimation flag
    ("Hemoglobin A1c (NGSP)", "glycemia"),  # with calibration
    ("LDL-C (calc)", "lipids"),  # with qualifierSon
    ("INR", "coagulation"),  # coagulation test
    ("PT", "coagulation"),  # prothrombin time
    ("aPTT", "coagulation"),  # activated PT
    ("Platelets", "hematology"),
    ("Plt", "hematology"),
]


def main():
    # Load alias table
    alias_path = Path(__file__).parent / "data" / "alias_tables" / "launch_scope_analyte_aliases.json"
    with open(alias_path) as f:
        alias_data = json.load(f)

    analytes = alias_data.get("analytes", [])
    print(f"Loaded {len(analytes)} analytes from alias table\n")

    # Build quick lookup
    canonical_set = {a["canonical_label"] for a in analytes}
    alias_set = set()
    for a in analytes:
        alias_set.update(a.get("aliases", []))

    print(f"Canonical labels: {len(canonical_set)}")
    print(f"All aliases (with duplicates): {len(alias_set)}")
    print()

    # Test normalization
    from app.services.analyte_resolver import _normalize_text

    print("=" * 80)
    print("NORMALIZATION FRAGILITY TEST")
    print("=" * 80)

    failures = []
    for raw_label, expected_panel in TEST_CASES:
        normalized = _normalize_text(raw_label)

        # Check if normalized matches any alias
        found = normalized in alias_set or normalized in canonical_set

        if not found:
            failures.append((raw_label, normalized, expected_panel))
            status = "❌ FAIL"
        else:
            status = "✓ PASS"

        print(f"{status:8} | '{raw_label}' -> '{normalized}'")

    print()
    print("=" * 80)
    print(f"RESULTS: {len(TEST_CASES) - len(failures)}/{len(TEST_CASES)} tests passed")
    print(f"Failures: {len(failures)}")
    print("=" * 80)

    if failures:
        print("\nFAILED CASES:")
        for raw, normalized, panel in failures:
            print(f"  Raw: '{raw}'")
            print(f"  Normalized: '{normalized}'")
            print(f"  Expected panel: {panel}")

            # Find similar analytes
            similar = [a for a in analytes if panel in a.get("panel_key", "")]
            if similar:
                print(f"  Available in {panel}:")
                for s in similar[:3]:
                    print(f"    - {s['canonical_label']} (aliases: {', '.join(s['aliases'][:3])})")
            print()

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
