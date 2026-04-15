import sys
sys.path.insert(0, 'backend')
from tests.unit.test_phase_40_v12_born_digital_parser import _parse_pdf, _assemble

artifacts = _parse_pdf('easy/seed_innoquest_dbticbm.pdf')
rows = _assemble(artifacts)

for r in rows:
    if 'creatinine' in r['raw_text'].lower() or 'hba1c' in r['raw_text'].lower():
        print(f"MATCH: {r['row_type']} -> {r['raw_text']}")
