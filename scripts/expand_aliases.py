"""Expand core_metrics.json aliases and add missing metrics."""
import json, pathlib, sys

p = pathlib.Path('data/metric_definitions/core_metrics.json')
d = json.load(open(p, encoding='utf-8'))

add_aliases = {
    'METRIC-0001': ['wbc count', 'white blood cells', 'white blood cell count', 'leukocytes'],
    'METRIC-0002': ['rbc count', 'red blood cells', 'red blood cell count', 'erythrocytes'],
    'METRIC-0003': ['hb', 'hgb', 'haemoglobin'],
    'METRIC-0004': ['hct', 'pcv', 'packed cell volume'],
    'METRIC-0008': ['rdw cv', 'rdw-cv', 'rdw'],
    'METRIC-0009': ['platelet count', 'platelets', 'plt', 'platelet'],
    'METRIC-0018': ['esr', 'erythrocyte sedimentation rate'],
    'METRIC-0011': ['neutrophils', 'neutrophil', 'neutrophils percent', 'absolute neutrophil count', 'anc', 'neutrophils absolute', 'neutrophil count'],
    'METRIC-0012': ['lymphocytes', 'lymphocyte', 'lymphocytes percent', 'absolute lymphocyte count', 'lymphocyte count'],
    'METRIC-0013': ['monocytes', 'monocyte', 'monocytes percent', 'absolute monocyte count'],
    'METRIC-0014': ['eosinophils', 'eosinophil', 'eosinophils percent', 'absolute eosinophil count'],
    'METRIC-0015': ['basophils', 'basophil', 'basophils percent', 'absolute basophil count'],
    'METRIC-0019': ['fasting blood sugar', 'fbs', 'fasting plasma glucose', 'fpg'],
    'METRIC-0024': ['calcium', 'ca', 'serum calcium'],
    'METRIC-0028': ['urea', 'blood urea', 'blood urea nitrogen', 'bun', 'serum urea'],
    'METRIC-0051': ['cholesterol', 'total cholesterol', 'cholesterol total', 'serum cholesterol'],
    'METRIC-0052': ['hdl', 'hdl-c', 'hdl c', 'hdl cholesterol', 'high density lipoprotein cholesterol'],
    'METRIC-0053': ['ldl', 'ldl-c', 'ldl c', 'ldl cholesterol', 'direct ldl', 'low density lipoprotein cholesterol'],
    'METRIC-0054': ['triglycerides', 'triglyceride', 'tg', 'tgs'],
    'METRIC-0056': ['vldl', 'vldl-c', 'vldl c', 'very low density lipoprotein'],
    'METRIC-0057': ['ldl hdl ratio', 'ldl/hdl ratio', 'ldl to hdl ratio'],
    'METRIC-0058': ['chol hdl ratio', 'chol/hdl ratio', 'total cholesterol hdl ratio', 'cholesterol hdl ratio', 'total cholesterol/hdl ratio'],
    'METRIC-0063': ['hemoglobin a1c', 'haemoglobin a1c', 'hb a1c', 'a1c', 'hba1c'],
    'METRIC-0036': ['bilirubin', 'bilirubin total', 'total bilirubin', 'serum bilirubin'],
    'METRIC-0037': ['direct bilirubin', 'bilirubin direct', 'conjugated bilirubin', 'bilirubin conjugated'],
    'METRIC-0038': ['indirect bilirubin', 'bilirubin indirect', 'unconjugated bilirubin', 'bilirubin unconjugated', 'delta bilirubin', 'bilirubin delta'],
    'METRIC-0039': ['sgot', 'ast', 'aspartate aminotransferase', 'ast sgot'],
    'METRIC-0040': ['sgpt', 'alt', 'alanine aminotransferase', 'alt sgpt'],
    'METRIC-0079': ['tsh', 'thyroid stimulating hormone', 'tsh thyroid stimulating hormone'],
    'METRIC-0081': ['t4', 'total t4', 'thyroxine', 't4 thyroxine'],
    'METRIC-0083': ['t3', 'total t3', 'triiodothyronine', 't3 triiodothyronine'],
    'METRIC-0068': ['microalbumin', 'microalbumin urine', 'urine microalbumin', 'microalbumin per urine volume'],
    'METRIC-0071': ['iron', 'serum iron', 'fe'],
    'METRIC-0072': ['tibc', 'total iron binding capacity', 'total iron-binding capacity'],
    'METRIC-0074': ['transferrin saturation', 'tsat', 'transferrin sat'],
    'METRIC-0076': ['vitamin b12', 'b12', 'cobalamin', 'vit b12'],
    'METRIC-0078': ['25 oh vitamin d', '25-oh vitamin d', '25 hydroxy vitamin d', 'vitamin d', '25-hydroxyvitamin d', 'vit d'],
    'METRIC-0098': ['specific gravity', 'sg', 'urine specific gravity'],
    'METRIC-0099': ['ph', 'urine ph'],
    'METRIC-0100': ['urine protein', 'protein urine', 'urine albumin dipstick', 'protein'],
    'METRIC-0101': ['urine glucose', 'glucose urine', 'glucose'],
    'METRIC-0102': ['urine ketone', 'ketone', 'ketones', 'urine ketones'],
    'METRIC-0103': ['urine bilirubin', 'bilirubin urine'],
    'METRIC-0105': ['nitrite', 'urine nitrite'],
    'METRIC-0107': ['urobilinogen', 'urine urobilinogen'],
    'METRIC-0108': ['rbc urine', 'urine rbc', 'red cells', 'red blood cells urine'],
    'METRIC-0109': ['wbc urine', 'urine wbc', 'pus cells'],
    'METRIC-0110': ['epithelial cells', 'squamous epithelial cells', 'epithelial'],
    'METRIC-0118': ['crystals', 'urine crystals'],
    'METRIC-0122': ['hbsag', 'hbs ag', 'hepatitis b surface antigen'],
    'METRIC-0126': ['hiv', 'hiv ag', 'hiv i ii', 'hiv i and ii', 'hiv ag ab', 'hiv i ii ab ag'],
    'METRIC-0096': ['colour', 'color'],
    'METRIC-0097': ['clarity', 'appearance', 'clarity appearance'],
}

found = {m['metric_id']: m for m in d}
for mid, adds in add_aliases.items():
    m = found.get(mid)
    if not m:
        continue
    cur = set(a.lower() for a in m.get('aliases', []))
    for a in adds:
        cur.add(a.lower())
    m['aliases'] = sorted(cur)

existing_ids = {m['metric_id'] for m in d}

def add_metric(mid, canon, unit, aliases, result_type='numeric'):
    if mid in existing_ids:
        return
    d.append({
        'metric_id': mid,
        'canonical_name': canon,
        'loinc_candidates': [],
        'aliases': aliases,
        'result_type': result_type,
        'canonical_unit_ucum': unit,
        'accepted_report_units': [unit],
        'default_reference_profiles': [{
            'profile_id': 'REF-' + mid.split('-')[1] + '-01',
            'metric_id': mid,
            'source_type': 'canonical_default',
            'target_unit_ucum': unit,
            'applies_to': {},
            'reference_text': 'see printed range',
            'priority': 100,
        }],
    })

add_metric('METRIC-0132', 'PSA', 'ng/mL', ['psa', 'prostate specific antigen', 'psa total', 'psa prostate specific antigen total', 'prostate-specific antigen'])
add_metric('METRIC-0133', 'IgE', 'IU/mL', ['ige', 'immunoglobulin e', 'total ige'])
add_metric('METRIC-0134', 'Homocysteine', 'micromol/L', ['homocysteine', 'homocysteine serum', 'hcy'])
add_metric('METRIC-0135', 'Hb A', '%', ['hb a', 'hba', 'hemoglobin a', 'adult hemoglobin a'])
add_metric('METRIC-0136', 'Hb A2', '%', ['hb a2', 'hba2', 'hemoglobin a2'])
add_metric('METRIC-0137', 'Foetal Hb', '%', ['foetal hb', 'fetal hb', 'hbf', 'foetal hemoglobin', 'fetal hemoglobin', 'hemoglobin f'])
add_metric('METRIC-0138', 'P2 Peak', '%', ['p2 peak', 'p2'])
add_metric('METRIC-0139', 'P3 Peak', '%', ['p3 peak', 'p3'])
add_metric('METRIC-0140', 'F Concentration', '%', ['f concentration'])
add_metric('METRIC-0141', 'A2 Concentration', '%', ['a2 concentration'])
add_metric('METRIC-0142', 'CHOL/HDL Ratio', 'ratio', ['chol/hdl ratio', 'chol hdl ratio'])
add_metric('METRIC-0143', 'A/G Ratio', 'ratio', ['a/g ratio', 'ag ratio', 'a g ratio', 'albumin globulin ratio', 'albumin/globulin ratio'])
add_metric('METRIC-0144', 'Mean Blood Glucose', 'mg/dL', ['mean blood glucose', 'mbg', 'estimated average glucose', 'eag'])
add_metric('METRIC-0145', 'Casts', '/hpf', ['casts', 'cast', 'urine casts', 'hyaline casts', 'granular casts'])
add_metric('METRIC-0146', 'Amorphous Material', 'text', ['amorphous material', 'amorphous', 'amorphous deposits'], result_type='qualitative')

json.dump(d, open(p, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
json.dump(d, open('backend/metric_definitions/core_metrics.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('wrote', len(d), 'metrics')
