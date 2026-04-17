import { useEffect, useState } from 'react';
import { getJobStatus } from '../../services/api';
import type { JobStatus, LaneType } from '../../types';
import {
  PageChrome,
  PillBadge,
  SurfaceCard,
} from '../common';
import {
  STITCH_COLORS,
  STITCH_RADIUS,
  pageCardStyle,
} from '../common/system';

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_ATTEMPTS = 180;

const BACKEND_STEP_LABELS: Record<string, string> = {
  preflight: 'Upload received',
  lane_selection: 'Checking file format',
  extraction: 'Reading supported rows',
  extraction_qa: 'Validating extracted rows',
  observation_build: 'Building structured observations',
  analyte_mapping: 'Matching lab values',
  ucum_conversion: 'Normalizing units',
  panel_reconstruction: 'Reconstructing panels',
  rule_evaluation: 'Evaluating support rules',
  severity_assignment: 'Assigning severity classes',
  nextstep_assignment: 'Determining next-step classes',
  patient_artifact: 'Building your summary',
  clinician_artifact: 'Rendering clinician summary',
  lineage_persist: 'Saving provenance data',
};

const DISPLAY_STAGES = [
  'Upload received',
  'Checking file format',
  'Reading supported rows',
  'Matching lab values',
  'Building your summary',
] as const;

const LANE_LABELS: Record<LaneType, string> = {
  trusted_pdf: 'Trusted PDF',
  image_beta: 'Image beta',
  structured: 'Structured',
};

function displayStageIndex(step: string): number {
  if (!step) {
    return 0;
  }

  if (step === 'preflight') {
    return 0;
  }

  if (step === 'lane_selection') {
    return 1;
  }

  if (['extraction', 'extraction_qa', 'observation_build'].includes(step)) {
    return 2;
  }

  if (
    [
      'analyte_mapping',
      'ucum_conversion',
      'panel_reconstruction',
      'rule_evaluation',
      'severity_assignment',
      'nextstep_assignment',
    ].includes(step)
  ) {
    return 3;
  }

  return 4;
}

interface Props {
  jobId: string;
  laneType: LaneType;
  onCompleted: () => void;
  onFailed: (message: string) => void;
}

export default function Processing({
  jobId,
  laneType,
  onCompleted,
  onFailed,
}: Props) {
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let attemptsSoFar = 0;
    let finished = false;
    let timeoutId: number | null = null;
    const abortController = new AbortController();

    const finishWithFailure = (message: string) => {
      if (finished) return;
      finished = true;
      setError(message);
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      abortController.abort();
      onFailed(message);
    };

    const finishWithSuccess = () => {
      if (finished) return;
      finished = true;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      abortController.abort();
      onCompleted();
    };

    const poll = async () => {
      if (finished) return;

      attemptsSoFar += 1;
      if (attemptsSoFar > MAX_POLL_ATTEMPTS) {
        finishWithFailure(
          'Processing took too long. Please try again later or upload another file.',
        );
        return;
      }

      try {
        const response = await getJobStatus(jobId);
        if (finished || abortController.signal.aborted) return;

        if (!response.ok) {
          throw new Error(`Status check failed with ${response.status}`);
        }

        const data: JobStatus = await response.json();
        if (finished || abortController.signal.aborted) return;

        setStatus(data);

        const normalizedStatus = data.status.toLowerCase();
        if (
          ['completed', 'done', 'success', 'partial'].includes(normalizedStatus)
        ) {
          finishWithSuccess();
          return;
        }

        if (
          ['failed', 'error', 'dead_letter', 'dead_lettered'].includes(normalizedStatus)
        ) {
          finishWithFailure(
            'Processing failed. Please try uploading a different file or contact support.',
          );
          return;
        }

        const delay = Math.min(1000 * Math.pow(1.5, attemptsSoFar - 1), 10000);
        timeoutId = window.setTimeout(() => { void poll(); }, delay);
      } catch (statusError: any) {
        if (!abortController.signal.aborted) {
          finishWithFailure(
            statusError instanceof Error ? statusError.message : 'Failed to check job status.',
          );
        }
      }
    };

    void poll();

    return () => {
      finished = true;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      abortController.abort();
    };
  }, [jobId, onCompleted, onFailed]);

  const currentStep = status?.step ?? '';
  const activeStageIndex = displayStageIndex(currentStep);
  const isImageBeta = laneType === 'image_beta';
  const progressPercent = Math.round(
    ((activeStageIndex + 1) / DISPLAY_STAGES.length) * 100,
  );
  const circleRadius = 92;
  const circumference = 2 * Math.PI * circleRadius;
  const dashOffset =
    circumference - (Math.min(progressPercent, 100) / 100) * circumference;
  const backendLabel = currentStep
    ? BACKEND_STEP_LABELS[currentStep] ?? 'Running support checks'
    : 'Running support checks';

  if (error) {
    return (
      <PageChrome
        compact
        title="Analyzing Report"
        subtitle="The processing run did not complete."
        rightSlot={<PillBadge tone="neutral">Retry required</PillBadge>}
      >
        <div
          role="alert"
          style={{
            ...pageCardStyle({
              marginTop: '1rem',
              padding: '1rem',
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
            }),
          }}
        >
          {error}
        </div>
      </PageChrome>
    );
  }

  return (
    <PageChrome
      compact
      title="Analyzing Report"
      subtitle="Checking supported rows."
      rightSlot={
        isImageBeta ? (
          <PillBadge tone="beta">{LANE_LABELS[laneType]}</PillBadge>
        ) : undefined
      }
      contentMaxWidth={980}
    >
      <div className="stitch-processing-layout stitch-enter" style={{ marginTop: '0.9rem' }}>
        <SurfaceCard
          style={{
            padding: '1.35rem 1rem 1.2rem',
            background:
              'linear-gradient(180deg, rgba(255,255,255,0.99) 0%, rgba(255,246,248,0.94) 100%)',
          }}
        >
          <div
            style={{
              position: 'relative',
              width: 220,
              height: 220,
              margin: '0 auto 1.15rem',
            }}
          >
            <svg
              viewBox="0 0 220 220"
              style={{ width: '100%', height: '100%', display: 'block' }}
            >
              <circle
                cx="110"
                cy="110"
                r={circleRadius}
                fill="none"
                stroke={STITCH_COLORS.surfaceHigh}
                strokeWidth="10"
              />
              <circle
                cx="110"
                cy="110"
                r={circleRadius}
                fill="none"
                stroke={STITCH_COLORS.pink}
                strokeWidth="12"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                style={{
                  transform: 'rotate(-90deg)',
                  transformOrigin: '50% 50%',
                  transition: 'stroke-dashoffset 200ms ease',
                }}
              />
            </svg>
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <div
                style={{
                  width: 46,
                  height: 46,
                  borderRadius: 14,
                  backgroundColor: 'rgba(255, 21, 112, 0.12)',
                  color: STITCH_COLORS.pink,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.15rem',
                  fontWeight: 700,
                  marginBottom: '0.45rem',
                }}
              >
                ▣
              </div>
              <span
                style={{
                  fontSize: '2.6rem',
                  fontWeight: 800,
                  color: STITCH_COLORS.textHeading,
                  letterSpacing: '-0.05em',
                }}
              >
                {progressPercent}%
              </span>
            </div>
          </div>

          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              padding: '0.45rem 0.8rem',
              borderRadius: STITCH_RADIUS.pill,
              backgroundColor: STITCH_COLORS.surfaceWhite,
              border: `1px solid ${STITCH_COLORS.borderGhost}`,
              marginBottom: '1rem',
              fontSize: '0.8rem',
              fontWeight: 700,
              color: STITCH_COLORS.textHeading,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                backgroundColor: STITCH_COLORS.pink,
                display: 'inline-block',
              }}
            />
            {backendLabel}
          </div>

          <div className="stitch-flow">
            {DISPLAY_STAGES.map((stage, index) => {
              const isDone = index < activeStageIndex;
              const isActive = index === activeStageIndex;

              return (
                <div
                  key={stage}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.9rem',
                    color: isActive
                      ? STITCH_COLORS.textHeading
                      : STITCH_COLORS.textSecondary,
                    fontWeight: isActive ? 700 : 600,
                  }}
                >
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: STITCH_RADIUS.pill,
                      backgroundColor: isDone
                        ? '#6BFE9C'
                        : isActive
                          ? 'rgba(255, 21, 112, 0.12)'
                          : STITCH_COLORS.surfaceLow,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: isDone
                        ? STITCH_COLORS.navy
                        : isActive
                          ? STITCH_COLORS.pink
                          : STITCH_COLORS.textMuted,
                      flexShrink: 0,
                    }}
                  >
                    {isDone ? (
                      <span aria-hidden="true">✓</span>
                    ) : isActive ? (
                      <span
                        aria-hidden="true"
                        style={{
                          width: 16,
                          height: 16,
                          borderRadius: '50%',
                          border: `2px solid ${STITCH_COLORS.pink}`,
                          borderTopColor: 'transparent',
                          display: 'inline-block',
                          animation: 'spin 900ms linear infinite',
                        }}
                      />
                    ) : (
                      <span aria-hidden="true">•</span>
                    )}
                  </div>
                  <span>{stage}</span>
                </div>
              );
            })}
          </div>
        </SurfaceCard>

        <SurfaceCard
          style={{
            padding: '1rem',
            backgroundColor: STITCH_COLORS.surfaceLow,
            boxShadow: 'none',
          }}
        >
          <p
            style={{
              margin: '0 0 0.24rem',
              fontSize: '0.74rem',
              fontWeight: 800,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
              color: STITCH_COLORS.textMuted,
            }}
          >
            What to expect
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '0.94rem',
              fontWeight: 700,
              lineHeight: 1.45,
              color: STITCH_COLORS.textHeading,
            }}
          >
            {isImageBeta
              ? 'Image uploads may return a partial preview.'
              : 'We are checking the report row by row before summarizing it.'}
          </p>

          <div className="stitch-divider" style={{ margin: '0.85rem 0' }} />

          <ul className="stitch-helper-list">
            <li>Only supported rows move into the patient summary.</li>
            <li>Unsupported or unreadable rows stay visible instead of being hidden.</li>
            <li>{backendLabel}. This usually takes a few seconds.</li>
          </ul>
        </SurfaceCard>
      </div>
    </PageChrome>
  );
}