# Verify the resolver changes work for all three problematic labels
import sys, os
sys.path.insert(0, os.path.join(os.getcwd()))
os.environ.setdefault("ELFIE_LOINC_PATH", "data/loinc")

from app.services.analyte_resolver import AnalyteResolver

resolver = AnalyteResolver()
ctx = {
    "family_adapter_id": "innoquest_bilingual_general",
    "specimen_context": "serum",
    "language_id": "en",
}

# Label 1: Apolipoprotein A1 with mojibake Chinese
label1 = "Apolipoprotein A1 è½½è"‚è›‹ç™½ A1"
r1 = resolver.resolve(label1, context=ctx)
print(f"Label1 normalized: {r1['normalized_label']!r}")
print(f"Label1 support_state: {r1['support_state']}")
print(f"Label1 accepted: {r1.get('accepted_candidate')}")

# Label 2: Triglyceride with mojibake Chinese
label2 = "Triglyceride ä¸‰é…¸ç"˜æ²¹é…¯"
r2 = resolver.resolve(label2, context=ctx)
print(f"\nLabel2 normalized: {r2['normalized_label']!r}")
print(f"Label2 support_state: {r2['support_state']}")
print(f"Label2 accepted: {r2.get('accepted_candidate')}")

# Label 3: Total bilirubin (mojibake only)
label3 = "æ€»çº¢èƒ†ç´ "
r3 = resolver.resolve(label3, context=ctx)
print(f"\nLabel3 normalized: {r3['normalized_label']!r}")
print(f"Label3 support_state: {r3['support_state']}")
print(f"Label3 accepted: {r3.get('accepted_candidate')}")

# Summary
print("\n=== SUMMARY ===")
for name, r in [("Label1", r1), ("Label2", r2), ("Label3", r3)]:
    status = "PASS" if r["support_state"] == "supported" else "FAIL"
    print(f"  {name}: {status} (support_state={r['support_state']})")
