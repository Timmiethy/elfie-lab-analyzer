import sys
import json
import asyncio
from pathlib import Path
sys.path.insert(0, '.')
from app.workers.pipeline import _normalize_observations
from app.services.analyte_resolver import AnalyteResolver
from app.services.ucum import UcumEngine
from app.services.metric_resolver import MetricResolver
from app.services.rule_engine import RuleEngine

def main():
    debug_files = list(Path('../artifacts/debug').glob('*_vlm_extraction.json'))
    if not debug_files: print('No debug files found')
    with open(debug_files[-1]) as f:
        data = json.load(f)
    patient_context_dict = {"patient_id": "test", "age_years": 40, "sex": "male", "pregnancy_status": False}
    an = AnalyteResolver()
    mr = MetricResolver(Path('../data/metric_definitions/core_metrics.json'))
    ue = UcumEngine()
    obs = _normalize_observations(data, analyte_resolver=an, ucum_engine=ue, metric_resolver=mr, patient_context=patient_context_dict)
    for o in obs: print(o.get('raw_analyte_label'), o.get('support_state'), o.get('suppression_reasons'))
    re = RuleEngine(metric_resolver=mr)
    fn = re.evaluate(obs, patient_context_dict)
    for f in fn: print(f.get('rule_id'), getattr(f, 'suppression_reason', f.get('suppression_reason')))

main()
