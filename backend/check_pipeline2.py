import sys, json, asyncio
from pathlib import Path
sys.path.insert(0, '.')
from app.workers.pipeline import _normalize_observations
from app.services.analyte_resolver import AnalyteResolver
from app.services.ucum import UcumEngine
from app.services.metric_resolver import MetricResolver
from app.services.rule_engine import RuleEngine
from app.services.observation_builder import ObservationBuilder

def main():
    debug_files = list(Path('../artifacts/debug').glob('3f7b9b7e*.json'))
    if not debug_files: print('No debug files found')
    with open(debug_files[-1]) as f:
        data = json.load(f)
    print("VLM extracted rows:", len(data))
    patient_context_dict = {"patient_id": "test", "age_years": 40, "sex": "male", "pregnancy_status": False}
    obs_built = ObservationBuilder().build(data)
    print("Built observations:", len(obs_built))
    obs = _normalize_observations(obs_built, analyte_resolver=AnalyteResolver(), ucum_engine=UcumEngine(), metric_resolver=MetricResolver(Path('../data/metric_definitions/core_metrics.json')), patient_context=patient_context_dict)
    for o in obs: print(o.get('raw_analyte_label'), o.get('support_state'), o.get('suppression_reasons'))
    re = RuleEngine(metric_resolver=MetricResolver(Path('../data/metric_definitions/core_metrics.json')))
    fn = re.evaluate(obs, patient_context_dict)
    for f in fn: print(f.get('rule_id'), getattr(f, 'suppression_reason', f.get('suppression_reason')))

main()
