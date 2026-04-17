#!/usr/bin/env python3
"""Expand sparse alias table with common OCR variants."""

import json
from pathlib import Path
from typing import Set


def expand_aliases(canonical_label: str, existing_aliases: list) -> Set[str]:
    """Generate common aliases for a canonical label."""
    variants: Set[str] = set(existing_aliases)
    normalized_canonical = canonical_label.lower().strip()

    # Always include canonical
    variants.add(normalized_canonical)

    # Remove context words to find core term
    context_words = {"serum", "plasma", "blood", "urine", "level", "levels", "count"}
    tokens = normalized_canonical.split()
    core_tokens = [t for t in tokens if t not in context_words]

    # 1. Reversed token order (for "total cholesterol" -> "cholesterol total")
    if len(tokens) > 1:
        variants.add(" ".join(reversed(tokens)))

    # 2. Short forms based on first letters or common abbreviations
    if "glucose" in normalized_canonical:
        variants.update(["glucose", "blood glucose", "fasting glucose", "glucose fasting", "fbs"])

    if "hemoglobin a1c" in normalized_canonical or "hba1c" in normalized_canonical:
        variants.update(["hba1c", "hemoglobin a1c", "hb a1c", "a1c", "hba1c ngsp", "hba1c dcct", "hba1c ifcc"])

    if "hemoglobin" in normalized_canonical and "a1c" not in normalized_canonical:
        variants.update(["hemoglobin", "hb", "hgb", "hemoglobin g/dl", "hemoglobin g dl"])

    if normalized_canonical == "sodium":
        variants.update(["sodium", "na", "na+", "salt", "serum sodium", "s. sodium"])

    if normalized_canonical == "potassium":
        variants.update(["potassium", "k", "k+", "serum potassium", "s. potassium"])

    if normalized_canonical == "chloride":
        variants.update(["chloride", "cl", "cl-", "serum chloride", "s. chloride"])

    if "creatinine" in normalized_canonical:
        variants.update(["creatinine", "creat", "creat.", "crea", "s. creatinine", "serum creatinine"])

    if "egfr" in normalized_canonical or "gfr" in normalized_canonical:
        variants.update(["egfr", "egfr ckd epi", "egfr ckd-epi", "egfr cke epi", "gfr", "estimated gfr",
                        "estimated glomerular filtration rate", "egfr calc", "egfr calculated"])

    if "bun" in normalized_canonical or "urea nitrogen" in normalized_canonical:
        variants.update(["bun", "blood urea nitrogen", "serum urea nitrogen", "urea nitrogen"])

    if "total cholesterol" in normalized_canonical:
        variants.update(["total cholesterol", "cholesterol total", "total chol", "chol", "cholesterol"])

    if "ldl" in normalized_canonical:
        variants.update(["ldl", "ldl-c", "ldl-cholesterol", "ldl cholesterol",
                        "low density lipoprotein", "ldl c", "ldl calc", "ldl calculated"])

    if "hdl" in normalized_canonical:
        variants.update(["hdl", "hdl-c", "hdl-cholesterol", "hdl cholesterol",
                        "high density lipoprotein", "hdl c"])

    if "triglyceride" in normalized_canonical:
        variants.update(["triglycerides", "triglyceride", "trig", "trigs", "triglyceride level"])

    if "wbc" in normalized_canonical:
        variants.update(["wbc", "white blood cell", "white blood cells", "wbc count", "white cell count"])

    if "rbc" in normalized_canonical:
        variants.update(["rbc", "red blood cell", "red blood cells", "rbc count", "red cell count"])

    if "platelets" in normalized_canonical or "plt" in normalized_canonical:
        variants.update(["platelets", "plt", "platelet count", "platelet"])

    if "ast" in normalized_canonical or "sgot" in normalized_canonical:
        variants.update(["ast", "sgot", "aspartate aminotransferase"])

    if "alt" in normalized_canonical or "sgpt" in normalized_canonical:
        variants.update(["alt", "sgpt", "alanine aminotransferase"])

    # 3. Common modifiers
    if not any(mod in normalized_canonical for mod in ["fasting", "random", "2-hour"]):
        variants.add(f"{normalized_canonical} fasting")

    # 4. With common units removed but indicated
    variants.add(normalized_canonical.replace(" mg/dl", "").replace(" mmol/l", "").replace(" g/dl", ""))
    variants.add(normalized_canonical.replace(" %", "").replace(" mm/h", ""))

    # 5. With parenthetical qualifiers
    for qual in ["ngsp", "dcct", "ifcc", "ckd-epi", "epi", "calc", "calculated"]:
        if qual in normalized_canonical:
            variants.add(normalized_canonical.replace(f" {qual}", "").replace(f" ({qual})", ""))

    # 6. Abbreviations from first letters of multi-word terms
    if len(core_tokens) >= 2:
        initials = "".join([t[0] for t in core_tokens if t])
        if 1 < len(initials) <= 4:
            variants.add(initials.lower())

    # Clean up: remove empty strings
    return {v.strip() for v in variants if v.strip()}


def main():
    alias_file = Path(__file__).parent / "data" / "alias_tables" / "launch_scope_analyte_aliases.json"

    with open(alias_file) as f:
        data = json.load(f)

    # Expand each analyte's aliases
    for analyte in data.get("analytes", []):
        canonical = analyte.get("canonical_label", "")
        existing = analyte.get("aliases", [])

        expanded = expand_aliases(canonical, existing)
        analyte["aliases"] = sorted(list(expanded))

    # Write back with pretty formatting
    with open(alias_file, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"✓ Expanded {len(data.get('analytes', []))} analytes")

    # Report stats
    total_aliases = sum(len(a.get("aliases", [])) for a in data.get("analytes", []))
    avg_aliases = total_aliases / len(data.get("analytes", []))

    print(f"  Total aliases: {total_aliases}")
    print(f"  Average per analyte: {avg_aliases:.1f}")


if __name__ == "__main__":
    main()
