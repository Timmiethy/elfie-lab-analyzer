import { useEffect, useMemo, useState } from 'react';
import Upload from './components/upload';
import Processing from './components/processing';
import PatientArtifact from './components/patient_artifact';
import ClinicianShare from './components/clinician_share';
import GuidedAsk from './components/guided_ask';
import {
  PageChrome,
  PillBadge,
  PrimaryButton,
  SecondaryButton,
  SurfaceCard,
} from './components/common';
import { STITCH_COLORS } from './components/common/system';
import type { LaneType, PatientArtifact as PatientArtifactType } from './types';
import { getPatientArtifact } from './services/api';
import {
  getPreviewFixture,
  listPreviewFixtures,
  type PreviewLanguage,
  type PreviewVariant,
} from './fixtures/stitchPreviewData';

type AppState =
  | 'upload'
  | 'processing'
  | 'patient_artifact'
  | 'preview_selector'
  | 'guided_ask'
  | 'clinician_share';

type Notice = {
  tone: 'success' | 'error';
  text: string;
} | null;

const CLINICIAN_SHARE_ENABLED = false;
const PREVIEW_FIXTURE_ENABLED = true;
const PREVIEW_QUERY_VALUE = 'fixtures';

function previewRouteRequested(): boolean {
  if (!PREVIEW_FIXTURE_ENABLED || typeof window === 'undefined') {
    return false;
  }

  const params = new URLSearchParams(window.location.search);
  return params.get('preview') === PREVIEW_QUERY_VALUE;
}

function App() {
  const previewModeRequested = previewRouteRequested();
  const [state, setState] = useState<AppState>(
    previewModeRequested ? 'preview_selector' : 'upload',
  );
  const [jobId, setJobId] = useState<string | null>(null);
  const [laneType, setLaneType] = useState<LaneType | null>(null);
  const [notice, setNotice] = useState<Notice>(null);
  const [artifact, setArtifact] = useState<PatientArtifactType | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);
  const [previewVariant, setPreviewVariant] =
    useState<PreviewVariant>('fully_supported');
  const [previewLanguage, setPreviewLanguage] =
    useState<PreviewLanguage>('en');

  const previewFixture = useMemo(
    () => getPreviewFixture(previewVariant, previewLanguage),
    [previewLanguage, previewVariant],
  );

  const handleJobStarted = (newJobId: string, newLaneType: LaneType) => {
    setNotice(null);
    setArtifact(null);
    setArtifactError(null);
    setJobId(newJobId);
    setLaneType(newLaneType);
    setState('processing');
  };

  const handleProcessingCompleted = () => {
    setState('patient_artifact');
  };

  const handleProcessingFailed = (message: string) => {
    setNotice({ tone: 'error', text: message });
    setArtifact(null);
    setArtifactError(null);
    setJobId(null);
    setLaneType(null);
    setState(previewModeRequested ? 'preview_selector' : 'upload');
  };

  const handleNavigateBack = () => {
    setArtifact(null);
    setArtifactError(null);
    setJobId(null);
    setLaneType(null);
    setState(previewModeRequested ? 'preview_selector' : 'upload');
  };

  const handleReturnToArtifact = () => {
    setState('patient_artifact');
  };

  useEffect(() => {
    if (state !== 'patient_artifact' || !jobId) {
      return;
    }

    let cancelled = false;

    const fetchArtifact = async () => {
      try {
        const response = await getPatientArtifact(jobId);
        if (!response.ok) {
          throw new Error(
            `Failed to load patient artifact (status ${response.status}).`,
          );
        }

        const data: PatientArtifactType = await response.json();
        if (!cancelled) {
          setArtifact(data);
          setArtifactError(null);
        }
      } catch (fetchError) {
        if (!cancelled) {
          setArtifactError(
            fetchError instanceof Error
              ? fetchError.message
              : 'Failed to load patient artifact.',
          );
        }
      }
    };

    void fetchArtifact();

    return () => {
      cancelled = true;
    };
  }, [jobId, state]);

  if (state === 'preview_selector') {
    const fixtures = listPreviewFixtures();

    return (
      <PageChrome
        compact
        title="Preview Fixtures"
        subtitle="Developer-only fixture selector for reviewing result surfaces while backend artifact routes remain stubbed."
        rightSlot={<PillBadge tone="neutral">Preview mode</PillBadge>}
      >
        <div
          style={{
            marginTop: '0.9rem',
            display: 'flex',
            flexDirection: 'column',
            gap: '0.9rem',
          }}
        >
          {fixtures.map((fixture) => (
            <SurfaceCard
              key={`${fixture.language}_${fixture.variant}`}
              style={{ padding: '1rem' }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'flex-start',
                  gap: '0.75rem',
                }}
              >
                <div>
                  <p
                    style={{
                      margin: '0 0 0.25rem',
                      fontSize: '0.76rem',
                      fontWeight: 800,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: STITCH_COLORS.textMuted,
                    }}
                  >
                    {fixture.language.toUpperCase()} ·{' '}
                    {fixture.variant.replace(/_/g, ' ')}
                  </p>
                  <p
                    style={{
                      margin: 0,
                      fontSize: '0.92rem',
                      lineHeight: 1.55,
                      color: STITCH_COLORS.textSecondary,
                    }}
                  >
                    {fixture.patientArtifact.support_banner.replace(/_/g, ' ')}
                    {fixture.hasComparableHistory
                      ? ' · comparable history present'
                      : ' · no comparable history'}
                  </p>
                </div>
                <PillBadge
                  tone={
                    fixture.patientArtifact.support_banner === 'fully_supported'
                      ? 'trusted'
                      : fixture.patientArtifact.support_banner ===
                          'partially_supported'
                        ? 'beta'
                        : 'neutral'
                  }
                >
                  {fixture.patientArtifact.overall_severity}
                </PillBadge>
              </div>

              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.6rem',
                  marginTop: '0.9rem',
                }}
              >
                <PrimaryButton
                  onClick={() => {
                    setPreviewVariant(fixture.variant);
                    setPreviewLanguage(fixture.language);
                    setJobId(null);
                    setState('patient_artifact');
                  }}
                >
                  Open patient summary
                </PrimaryButton>
                <SecondaryButton
                  onClick={() => {
                    setPreviewVariant(fixture.variant);
                    setPreviewLanguage(fixture.language);
                    setJobId(null);
                    setState('clinician_share');
                  }}
                >
                  Open clinician summary
                </SecondaryButton>
              </div>
            </SurfaceCard>
          ))}
        </div>

        <div
          style={{
            marginTop: '1rem',
            backgroundColor: STITCH_COLORS.errorBg,
            color: STITCH_COLORS.errorText,
            borderRadius: 24,
            padding: '1rem',
          }}
        >
          <p
            style={{
              margin: '0 0 0.3rem',
              fontSize: '0.76rem',
              fontWeight: 800,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            Preview mode
          </p>
          <p style={{ margin: 0, fontSize: '0.9rem', lineHeight: 1.6 }}>
            These screens use typed local fixtures. The live backend artifact
            routes remain stubbed, so preview mode is the honest way to review
            post-processing UI right now.
          </p>
        </div>

        <SecondaryButton
          onClick={() => setState('upload')}
          style={{ marginTop: '1rem' }}
        >
          Try the live upload flow
        </SecondaryButton>
      </PageChrome>
    );
  }

  if (state === 'processing' && jobId && laneType) {
    return (
      <Processing
        jobId={jobId}
        laneType={laneType}
        onCompleted={handleProcessingCompleted}
        onFailed={handleProcessingFailed}
      />
    );
  }

  if (state === 'patient_artifact') {
    const currentArtifact = jobId ? artifact : previewFixture.patientArtifact;
    const clinicianShareAvailable = jobId
      ? CLINICIAN_SHARE_ENABLED
      : Boolean(previewFixture.clinicianArtifact);

    if (artifactError) {
      return (
        <PageChrome
          compact
          title="Unable to load summary"
          subtitle="The patient artifact could not be loaded."
          rightSlot={<PillBadge tone="neutral">Load error</PillBadge>}
        >
          <div
            role="alert"
            style={{
              marginTop: '1rem',
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
              borderRadius: 24,
              padding: '1rem',
            }}
          >
            {artifactError}
          </div>
          <SecondaryButton
            onClick={handleNavigateBack}
            style={{ marginTop: '1rem' }}
          >
            Try another file
          </SecondaryButton>
        </PageChrome>
      );
    }

    if (!currentArtifact) {
      return (
        <PageChrome
          compact
          title="Loading summary"
          subtitle="Waiting for the patient artifact."
          rightSlot={<PillBadge tone="neutral">Loading</PillBadge>}
        >
          <SurfaceCard style={{ marginTop: '1rem', padding: '1rem' }}>
            <p
              style={{
                margin: 0,
                fontSize: '0.92rem',
                color: STITCH_COLORS.textSecondary,
              }}
            >
              Loading your summary...
            </p>
          </SurfaceCard>
        </PageChrome>
      );
    }

    return (
      <PatientArtifact
        artifact={currentArtifact}
        onNavigateBack={handleNavigateBack}
        onViewClinicianShare={
          clinicianShareAvailable ? () => setState('clinician_share') : undefined
        }
        onViewGuidedAsk={() => setState('guided_ask')}
      />
    );
  }

  if (state === 'clinician_share') {
    if (jobId) {
      if (!CLINICIAN_SHARE_ENABLED) {
        setState('patient_artifact');
        return null;
      }

      return (
        <ClinicianShare
          jobId={jobId}
          supportBanner={artifact?.support_banner}
          patientArtifact={artifact ?? undefined}
          onNavigateBack={handleReturnToArtifact}
        />
      );
    }

    return (
      <ClinicianShare
        previewArtifact={previewFixture.clinicianArtifact}
        supportBanner={previewFixture.patientArtifact.support_banner}
        patientArtifact={previewFixture.patientArtifact}
        onNavigateBack={handleReturnToArtifact}
      />
    );
  }

  if (state === 'guided_ask') {
    const effectiveLanguage = jobId
      ? artifact?.language_id === 'vi'
        ? 'vi'
        : 'en'
      : previewFixture.language;

    return (
      <GuidedAsk
        language={effectiveLanguage}
        onNavigateBack={handleReturnToArtifact}
      />
    );
  }

  return <Upload onJobStarted={handleJobStarted} notice={notice} />;
}

export default App;
