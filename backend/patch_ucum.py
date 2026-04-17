import sys
import re

with open('app/services/ucum/__init__.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Fix normalize_unit
text = text.replace(
    'return " ".join(str(unit or "").strip().lower().split())',
    'return " ".join(str(unit or "").strip().lower().replace("²", "2").replace("{1.73_m2}", "1.73 m2").split())'
)

# Add missing allowed keys
new_supported = '''    @staticmethod
    def _supported_units() -> dict[str, str]:
        return {
            "mg/dl": "mg/dL",
            "%": "%",
            "mmol/l": "mmol/L",
            "umol/l": "umol/L",
            "mmol/mol": "mmol/mol",
            "g/l": "g/L",
            "g/dl": "g/dL",
            "mg/l": "mg/L",
            "ng/ml": "ng/mL",
            "u/l": "U/L",
            "miu/l": "mIU/L",
            "ml/min/1.73 m2": "mL/min/{1.73_m2}",
            "ml/min/1.73m2": "mL/min/{1.73_m2}",
            "-": "1",
            "1": "1"
        }'''
text = re.sub(r'    @staticmethod\n    def _supported_units\(\) -> dict\[str, str\]:[\s\S]+?\}', new_supported, text)

text = text.replace(
    'molar_factors: dict[str, float] = {"mmol/l": 0.001}',
    'molar_factors: dict[str, float] = {"mmol/l": 0.001, "umol/l": 0.000001}'
)

with open('app/services/ucum/__init__.py', 'w', encoding='utf-8') as f:
    f.write(text)

