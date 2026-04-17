import json
from pathlib import Path

# Parsed from the prompt tables
METRICS_DATA = [
    # Hematology / CBC / differential
    (1, "WBC", "10^9/L", "4.0–10.0", ["age"]),
    (2, "RBC", "10^12/L", "F 4.0–5.4; M 4.5–6.1", ["age", "sex"]),
    (3, "Hemoglobin", "g/dL", "F 11.5–15.5; M 13.0–17.0", ["age", "sex"]),
    (4, "Hematocrit", "%", "F 36–48; M 40–55", ["age", "sex"]),
    (5, "MCV", "fL", "80–100", ["age"]),
    (6, "MCH", "pg", "27–31", ["age"]),
    (7, "MCHC", "g/dL", "32–36", ["age"]),
    (8, "RDW-CV", "%", "12–15", ["age"]),
    (9, "Platelets", "10^9/L", "150–400", ["age"]),
    (10, "MPV", "fL", "7.0–9.0", ["age"]),
    (11, "Neutrophils, absolute", "10^9/L", "2.5–7.0", ["age"]),
    (12, "Lymphocytes, absolute", "10^9/L", "1.0–4.8", ["age"]),
    (13, "Monocytes, absolute", "10^9/L", "0.2–0.8", ["age"]),
    (14, "Eosinophils, absolute", "10^9/L", "<0.5", ["age"]),
    (15, "Basophils, absolute", "10^9/L", "<0.3", ["age"]),
    (16, "Immature granulocytes, absolute", "10^9/L", "<0.1", ["age"]),
    (17, "NRBC, absolute", "10^9/L", "<0.01", ["age"]),
    (18, "ESR", "mm/h", "M<50: <15; M≥50: <20; F<50: <20; F≥50: <30", ["age", "sex"]),

    # Chemistry / renal / liver / minerals
    (19, "Glucose, fasting", "mg/dL", "70–100", ["fasting", "age"]),
    (20, "Sodium", "mmol/L", "135–145", ["age"]),
    (21, "Potassium", "mmol/L", "3.7–5.2", ["age"]),
    (22, "Chloride", "mmol/L", "96–106", ["age"]),
    (23, "CO2 / bicarbonate", "mmol/L", "23–29", ["age"]),
    (24, "Calcium, total", "mg/dL", "8.5–10.2", ["age"]),
    (25, "Calcium, ionized", "mmol/L", "1.05–1.30", ["age"]),
    (26, "Phosphorus", "mg/dL", "3.0–4.5", ["age"]),
    (27, "Magnesium", "mmol/L", "0.65–1.05", ["age"]),
    (28, "BUN", "mg/dL", "6–20", ["age"]),
    (29, "Creatinine", "mg/dL", "general 0.6–1.3; sex-specific lab override preferred", ["age", "sex"]),
    (30, "eGFR", "mL/min/{1.73_m2}", "report-specific; do not hardcode one normal", ["age", "sex", "equation"]),
    (31, "Uric acid", "mg/dL", "M 4.0–8.5; F 2.7–7.3", ["age", "sex"]),
    (32, "Total protein", "g/dL", "6.0–8.3", ["age"]),
    (33, "Albumin", "g/dL", "3.4–5.4", ["age"]),
    (34, "Globulin", "g/dL", "lab-specific", ["age"]),
    (35, "A/G ratio", "1", "lab-specific", ["age"]),
    (36, "Bilirubin, total", "mg/dL", "0.1–1.2", ["age"]),
    (37, "Bilirubin, direct", "mg/dL", "lab-specific", ["age"]),
    (38, "Bilirubin, indirect", "mg/dL", "lab-specific", ["age"]),
    (39, "AST / SGOT", "U/L", "8–33", ["age"]),
    (40, "ALT / SGPT", "U/L", "4–36", ["age"]),
    (41, "ALP", "U/L", "20–130", ["age"]),
    (42, "GGT", "U/L", "lab-specific", ["age", "sex"]),
    (43, "Anion gap", "mmol/L", "lab-specific", ["method"]),
    (44, "Osmolality, serum", "mOsm/kg", "lab-specific", ["age"]),
    (45, "Lactate", "mmol/L", "lab-specific", ["specimen", "timing"]),
    (46, "Amylase", "U/L", "lab-specific", ["age"]),
    (47, "Lipase", "U/L", "lab-specific", ["age"]),
    (48, "CK / CPK", "U/L", "lab-specific", ["age", "sex"]),
    (49, "LDH", "U/L", "lab-specific", ["age"]),
    (50, "Ammonia", "µg/dL", "lab-specific", ["specimen", "timing"]),

    # Lipids / diabetes / cardiometabolic
    (51, "Total cholesterol", "mg/dL", "<200", ["fasting status"]),
    (52, "HDL-C", "mg/dL", ">60", ["sex", "fasting status"]),
    (53, "LDL-C", "mg/dL", "<100", ["diabetes/CVD context"]),
    (54, "Triglycerides", "mg/dL", "<150", ["fasting status"]),
    (55, "Non-HDL cholesterol", "mg/dL", "guideline-specific", ["CVD risk"]),
    (56, "VLDL-C", "mg/dL", "lab-specific", ["fasting status"]),
    (57, "LDL/HDL ratio", "1", "lab-/guideline-specific", ["sex", "CVD risk"]),
    (58, "Total cholesterol / HDL ratio", "1", "lab-/guideline-specific", ["sex", "CVD risk"]),
    (59, "ApoB", "mg/dL", "guideline-specific", ["CVD risk"]),
    (60, "ApoA1", "mg/dL", "lab-/guideline-specific", ["sex"]),
    (61, "ApoB/ApoA1 ratio", "1", "lab-/guideline-specific", ["sex", "CVD risk"]),
    (62, "Lipoprotein(a)", "mg/dL", "lab-/guideline-specific", ["assay", "ethnicity"]),
    (63, "HbA1c", "%", "report- or guideline-specific", ["diabetes status"]),
    (64, "HbA1c", "mmol/mol", "report- or guideline-specific", ["diabetes status"]),
    (65, "Insulin, fasting", "µIU/mL", "lab-specific", ["fasting"]),
    (66, "HOMA-IR", "1", "calculated", ["fasting"]),
    (67, "Fructosamine", "µmol/L", "lab-specific", ["albumin status"]),
    (68, "Microalbumin, urine", "mg/L", "report-specific", ["specimen"]),
    (69, "Urine albumin/creatinine ratio (ACR)", "mg/g{creat}", "report-/guideline-specific", ["specimen", "sex"]),
    (70, "Protein/creatinine ratio (PCR)", "mg/g{creat}", "report-/guideline-specific", ["specimen"]),

    # Iron / thyroid / vitamins
    (71, "Iron, serum", "µg/dL", "lab-specific", ["sex", "fasting"]),
    (72, "TIBC", "µg/dL", "lab-specific", ["sex"]),
    (73, "Transferrin", "mg/dL", "lab-specific", ["sex"]),
    (74, "Transferrin saturation", "%", "M 20–50; F 15–50", ["sex"]),
    (75, "Ferritin", "ng/mL", "M 12–300; F 10–150", ["age", "sex", "inflammation"]),
    (76, "Vitamin B12", "ng/L", "180–914", ["age"]),
    (77, "Folate", "µg/L", "≥4.0", ["age"]),
    (78, "25-OH Vitamin D", "ng/mL", "lab-/guideline-specific", ["age", "pregnancy"]),
    (79, "TSH", "µU/mL", "0.5–5.0", ["age", "pregnancy"]),
    (80, "Free T4", "ng/dL", "0.8–1.9", ["age", "pregnancy"]),
    (81, "Total T4", "µg/dL", "4.5–11.7", ["age", "pregnancy"]),
    (82, "Free T3", "pg/dL", "130–450", ["age"]),
    (83, "Total T3", "ng/dL", "60–180", ["age"]),
    (84, "Anti-TPO Ab", "IU/mL", "assay-specific", ["assay"]),
    (85, "CRP", "mg/dL", "<0.3", ["age", "sex"]),
    (86, "hs-CRP", "mg/L", "assay-/risk-specific", ["CVD risk"]),
    (87, "PT", "s", "lab-specific", ["reagent"]),
    (88, "INR", "1", "~0.8–1.2 if not anticoagulated", ["anticoagulation"]),
    (89, "aPTT", "s", "lab-specific", ["reagent"]),
    (90, "Fibrinogen", "mg/dL", "lab-specific", ["pregnancy", "inflammation"]),
    (91, "D-dimer", "ng/mL FEU", "lab-specific", ["assay", "age-adjusted use"]),
    (92, "Troponin I", "ng/L", "assay-specific", ["assay"]),
    (93, "Troponin T", "ng/L", "assay-specific", ["assay"]),
    (94, "BNP", "pg/mL", "assay-specific", ["age", "renal function"]),
    (95, "NT-proBNP", "pg/mL", "assay-/age-specific", ["age", "renal function"]),

    # Urinalysis — chemistry / physical
    (96, "Color", "text", "pale yellow to dark yellow", ["hydration", "drugs"]),
    (97, "Clarity / appearance", "text", "clear", ["specimen"]),
    (98, "Specific gravity", "1", "1.005–1.030", ["hydration"]),
    (99, "pH", "1", "4.6–8.0", ["diet", "specimen"]),
    (100, "Protein, urine dipstick", "qual", "negative / not detectable", ["specimen"]),
    (101, "Glucose, urine", "qual", "negative / not detectable", ["specimen"]),
    (102, "Ketones, urine", "qual", "negative / not detectable", ["specimen"]),
    (103, "Bilirubin, urine", "qual", "negative / not detectable", ["specimen"]),
    (104, "Blood / hemoglobin, urine", "qual", "negative / not detectable", ["specimen"]),
    (105, "Nitrite, urine", "qual", "negative / not detectable", ["specimen"]),
    (106, "Leukocyte esterase", "qual", "negative / not detectable", ["specimen"]),
    (107, "Urobilinogen", "EU/dL", "lab-specific / normal trace only", ["specimen"]),

    # Urinalysis — microscopy / sediment
    (108, "RBC, urine microscopy", "/HPF", "none normally found", ["specimen", "sex"]),
    (109, "WBC, urine microscopy", "/HPF", "none normally found", ["specimen"]),
    (110, "Squamous epithelial cells", "/HPF", "none to few / lab-specific", ["specimen quality"]),
    (111, "Renal epithelial cells", "/HPF", "none / lab-specific", ["specimen"]),
    (112, "Transitional epithelial cells", "/HPF", "none / lab-specific", ["specimen"]),
    (113, "Bacteria", "qual", "none", ["specimen quality"]),
    (114, "Yeast", "qual", "none", ["specimen"]),
    (115, "Mucus", "qual", "none to trace / lab-specific", ["specimen"]),
    (116, "Hyaline casts", "/LPF", "none to few / lab-specific", ["specimen"]),
    (117, "Granular casts", "/LPF", "none", ["specimen"]),
    (118, "Crystals", "qual", "none / lab-specific type", ["specimen", "pH"]),
    (119, "Urine albumin", "mg/L", "lab-specific", ["specimen"]),
    (120, "Urine creatinine", "mg/dL", "lab-specific", ["specimen"]),
    (121, "ACR", "mg/g{creat}", "report-/guideline-specific", ["specimen", "sex"]),

    # Common infectious / screening / qualitative reportables
    (122, "HBsAg", "qual", "negative / nonreactive", ["assay"]),
    (123, "Anti-HBs", "mIU/mL", "assay-/immunity-threshold specific", ["vaccination status"]),
    (124, "Anti-HBc IgM", "qual", "negative / nonreactive", ["assay"]),
    (125, "Anti-HCV", "qual", "negative / nonreactive", ["assay"]),
    (126, "HIV Ag/Ab", "qual", "negative / nonreactive", ["assay"]),
    (127, "HAV IgM", "qual", "negative / nonreactive", ["assay"]),
    (128, "RPR / VDRL", "qual or titer", "nonreactive", ["assay"]),
    (129, "Dengue NS1", "qual", "negative / nonreactive", ["assay", "endemicity"]),
    (130, "Stool occult blood / FIT", "qual", "negative", ["assay"]),
    (131, "hCG, pregnancy", "IU/L", "context-/method-specific", ["sex", "age", "pregnancy"]),
]

metrics = []

def infer_result_type(unit):
    if unit == "text": return "text"
    if unit in ["qual", "qual or titer"]: return "qualitative"
    return "numeric"

for m in METRICS_DATA:
    row_id, name, unit, fallback_ref, context_keys = m
    
    # Very basic parsing to establish seed default reference profiles
    profiles = []
    
    # We create a placeholder 'canonical_default' profile 
    profiles.append({
        "profile_id": f"fallback_{row_id}_01",
        "metric_id": f"metric_{row_id:03d}",
        "source_type": "canonical_default",
        "applies_to": {
            "sex": None,
            "age_low": None,
            "age_high": None,
            "pregnancy": None,
            "specimen": None,
            "method": None,
            "analyzer": None
        },
        "ref_low": None,  # Advanced parse can be done manually later
        "ref_high": None,
        "ref_text": fallback_ref,
        "comparator_policy": None,
        "priority": 5
    })

    metrics.append({
        "metric_id": f"metric_{row_id:03d}",
        "canonical_name": name,
        "loinc_candidates": [],
        "aliases": [name.lower()],
        "specimen": None,
        "result_type": infer_result_type(unit),
        "canonical_unit_ucum": unit if infer_result_type(unit) == "numeric" else None,
        "accepted_report_units": [],
        "conversion_rule_id": None,
        "sex_applicability": ["M", "F", "O"] if "sex" in context_keys else None,
        "age_applicability": None,
        "pregnancy_applicability": True if "pregnancy" in context_keys else None,
        "method_scope": None,
        "analyzer_scope": None,
        "default_reference_profiles": profiles,
        "qualitative_expected_values": ["negative", "nonreactive", "none", "clear", "pale yellow"] if infer_result_type(unit) in ["qualitative", "text"] else []
    })

output_dir = Path("data/metric_definitions")
output_dir.mkdir(parents=True, exist_ok=True)
with open(output_dir / "core_metrics.json", "w", encoding="utf-8") as f:
    json.dump(metrics, f, indent=2)

print("Generated data/metric_definitions/core_metrics.json")
