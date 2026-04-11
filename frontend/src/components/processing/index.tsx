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
  STITCH_SHADOWS,
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
    let intervalId: number | null = null;

    const finishWithFailure = (message: string) => {
      if (finished) {
        return;
      }
      finished = true;
      setError(message);
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
      onFailed(message);
    };

    const finishWithSuccess = () => {
      if (finished) {
        return;
      }
      finished = true;
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
      onCompleted();
    };

    const poll = async () => {
      if (finished) {
        return;
      }

      attemptsSoFar += 1;
      if (attemptsSoFar > MAX_POLL_ATTEMPTS) {
        finishWithFailure(
          'Processing took too long. Please try again later or upload another file.',
        );
        return;
      }

      try {
        const response = await getJobStatus(jobId);
        if (!response.ok) {
          throw new Error(`Status check failed with ${response.status}`);
        }

        const data: JobStatus = await response.json();
        setStatus(data);

        const normalizedStatus = data.status.toLowerCase();
        if (
          normalizedStatus === 'completed' ||
          normalizedStatus === 'done' ||
          normalizedStatus === 'success'
        ) {
          finishWithSuccess();
          return;
        }

        if (
          normalizedStatus === 'failed' ||
          normalizedStatus === 'error' ||
          normalizedStatus === 'dead_letter'
        ) {
          finishWithFailure(
            'Processing failed. Please try uploading a different file or contact support.',
          );
        }
      } catch (statusError) {
        finishWithFailure(
          statusError instanceof Error
            ? statusError.message
            : 'Failed to check job status.',
        );
      }
    };

    void poll();
    intervalId = window.setInterval(() => {
      void poll();
    }, POLL_INTERVAL_MS);

    return () => {
      finished = true;
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
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
  const backendLabel =
    BACKEND_STEP_LABELS[currentStep] ?? 'Running support checks';

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
    >
      <SurfaceCard
        style={{
          padding: '1.4rem 1rem 1.25rem',
          marginTop: '0.9rem',
        }}
      >
        <div
          style={{
            position: 'relative',
            width: 220,
            height: 220,
            margin: '0 auto 1.3rem',
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

        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
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
                    position: 'relative',
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

      <div
        style={{
          marginTop: '1rem',
          backgroundColor: STITCH_COLORS.navy,
          borderRadius: STITCH_RADIUS.md,
          padding: '1rem',
          color: STITCH_COLORS.surfaceWhite,
          boxShadow: STITCH_SHADOWS.lift,
        }}
      >
        <div style={{ display: 'flex', gap: '0.85rem' }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 14,
              backgroundColor: STITCH_COLORS.pink,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1.1rem',
              flexShrink: 0,
            }}
          >
            ⚡
          </div>
          <div>
            <p
              style={{
                margin: 0,
                fontSize: '0.78rem',
                fontWeight: 800,
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              {isImageBeta ? 'Image beta active' : 'Support checks active'}
            </p>
            <p
              style={{
                margin: '0.35rem 0 0',
                fontSize: '0.9rem',
                lineHeight: 1.55,
                color: 'rgba(255,255,255,0.78)',
              }}
            >
              {isImageBeta
                ? 'Photo and screenshot uploads may return a partial preview only. Unsupported or unreadable rows will stay visible instead of being hidden.'
                : 'We validate support row by row before values are summarized. Only supported rows move into the patient artifact.'}
            </p>
          </div>
        </div>
      </div>

      <p
        style={{
          margin: '1rem 0 0',
          fontSize: '0.8rem',
          color: STITCH_COLORS.textSecondary,
          lineHeight: 1.55,
          textAlign: 'center',
        }}
      >
        {backendLabel}. Processing may take a few seconds.
      </p>
    </PageChrome>
  );
}
