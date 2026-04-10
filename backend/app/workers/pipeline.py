"""Job pipeline orchestrator (blueprint section 3.1 flow).

Steps:
1. upload enters API
2. preflight classifies input lane
3. trusted PDF lane or image beta lane selected
4. extraction runs
5. extraction QA runs
6. provisional observations created
7. analyte mapping and abstention run
8. UCUM validation and canonicalization run
9. panel reconstruction runs
10. deterministic rules fire
11. deterministic severity and next-step assignment runs
12. structured patient artifact renders
13. clinician-share artifact renders
14. lineage and benchmark telemetry persist
"""

from enum import Enum


class PipelineStep(str, Enum):
    PREFLIGHT = "preflight"
    LANE_SELECTION = "lane_selection"
    EXTRACTION = "extraction"
    EXTRACTION_QA = "extraction_qa"
    OBSERVATION_BUILD = "observation_build"
    ANALYTE_MAPPING = "analyte_mapping"
    UCUM_CONVERSION = "ucum_conversion"
    PANEL_RECONSTRUCTION = "panel_reconstruction"
    RULE_EVALUATION = "rule_evaluation"
    SEVERITY_ASSIGNMENT = "severity_assignment"
    NEXTSTEP_ASSIGNMENT = "nextstep_assignment"
    PATIENT_ARTIFACT = "patient_artifact"
    CLINICIAN_ARTIFACT = "clinician_artifact"
    LINEAGE_PERSIST = "lineage_persist"


class PipelineOrchestrator:
    """Orchestrate the full processing pipeline for a job."""

    async def run(self, job_id: str) -> dict:
        raise NotImplementedError
