import { useEffect, useRef, useState } from 'react';
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
  lane_selection: 'Checking format',
  extraction: 'Reading rows',
  extraction_qa: 'Validating rows',
  observation_build: 'Building observations',
  analyte_mapping: 'Matching values',
  ucum_conversion: 'Normalizing units',
  panel_reconstruction: 'Reconstructing panels',
  rule_evaluation: 'Evaluating rules',
  severity_assignment: 'Assigning severity',
  nextstep_assignment: 'Determining next steps',
  patient_artifact: 'Building summary',
  clinician_artifact: 'Rendering clinician view',
  lineage_persist: 'Saving provenance',
};

const DISPLAY_STAGES = [
  'Upload received',
  'Checking format',
  'Reading rows',
  'Matching values',
  'Building summary',
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
  const [smoothProgress, setSmoothProgress] = useState(0);
  const targetProgressRef = useRef(4);
  const completedRef = useRef(false);

  // Smooth tween loop. Eases toward target each frame so bar glides instead of jumping.
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(now - last, 80);
      last = now;
      setSmoothProgress((curr) => {
        const target = targetProgressRef.current;
        if (Math.abs(target - curr) < 0.05) return target;
        // exponential ease; faster near the end when completed
        const rate = completedRef.current ? 0.012 : 0.0028;
        const next = curr + (target - curr) * (1 - Math.exp(-rate * dt));
        return next;
      });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Fake forward creep independent of backend steps so bar always moves.
  useEffect(() => {
    const start = performance.now();
    const id = window.setInterval(() => {
      if (completedRef.current) return;
      const elapsed = (performance.now() - start) / 1000;
      // Asymptotic curve: ramps toward ~92% over ~45s, never stalls.
      const creep = 92 * (1 - Math.exp(-elapsed / 18));
      if (creep > targetProgressRef.current) {
        targetProgressRef.current = creep;
      }
    }, 120);
    return () => window.clearInterval(id);
  }, []);

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
      completedRef.current = true;
      targetProgressRef.current = 100;
      if (intervalId !== null) {
        window.clearInterval(intervalId);
      }
      // Let bar visually reach 100 before swapping view
      window.setTimeout(() => onCompleted(), 420);
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
          normalizedStatus === 'success' ||
          normalizedStatus === 'partial'
        ) {
          finishWithSuccess();
          return;
        }

        if (
          normalizedStatus === 'failed' ||
          normalizedStatus === 'error' ||
          normalizedStatus === 'dead_letter' ||
          normalizedStatus === 'dead_lettered'
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

  // Backend stage sets a floor so bar at least reflects real progress.
  useEffect(() => {
    const floor = ((activeStageIndex + 1) / DISPLAY_STAGES.length) * 90;
    if (floor > targetProgressRef.current && !completedRef.current) {
      targetProgressRef.current = floor;
    }
  }, [activeStageIndex]);

  const progressPercent = Math.min(100, Math.round(smoothProgress));
  const circleRadius = 92;
  const circumference = 2 * Math.PI * circleRadius;
  const dashOffset =
    circumference - (Math.min(smoothProgress, 100) / 100) * circumference;
  const backendLabel = currentStep
    ? BACKEND_STEP_LABELS[currentStep] ?? 'Running checks'
    : 'Running checks';

  if (error) {
    return (
      <PageChrome
        compact
        title="Analyzing Report"
        subtitle="Processing did not complete."
        rightSlot={<PillBadge tone="neutral">Retry required</PillBadge>}
      >
        <div
          role="alert"
          style={{
            ...pageCardStyle({
              marginTop: '1.1rem',
              padding: '1.15rem',
              backgroundColor: STITCH_COLORS.errorBg,
              color: STITCH_COLORS.errorText,
              fontSize: '0.94rem',
              lineHeight: 1.55,
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
      <div className="stitch-enter" style={{ marginTop: '1rem' }}>
        {/* ==================== SINGLE SECTION: PROGRESS ==================== */}
        <SurfaceCard
          style={{
            padding: '1.75rem 1.25rem 1.5rem',
            background:
              'linear-gradient(180deg, rgba(255,255,255,0.99) 0%, rgba(255,246,248,0.94) 100%)',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              position: 'relative',
              width: 200,
              height: 200,
              margin: '0 auto 1.25rem',
            }}
          >
            <svg
              viewBox="0 0 220 220"
              style={{
                width: '100%',
                height: '100%',
                display: 'block',
                animation: 'spin 6s linear infinite',
              }}
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
                  transition: 'stroke-dashoffset 120ms linear',
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
              <span
                style={{
                  fontSize: '2.4rem',
                  fontWeight: 800,
                  color: STITCH_COLORS.textHeading,
                  letterSpacing: '-0.05em',
                }}
              >
                {progressPercent}%
              </span>
              <span
                style={{
                  marginTop: 4,
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  color: STITCH_COLORS.pink,
                }}
              >
                {backendLabel}
              </span>
            </div>
          </div>

          <div
            className="stitch-flow"
            style={{ gap: '0.45rem', textAlign: 'left', maxWidth: 420, margin: '0 auto' }}
          >
            {DISPLAY_STAGES.map((stage, index) => {
              const isDone = index < activeStageIndex;
              const isActive = index === activeStageIndex;
              return (
                <div
                  key={stage}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.85rem',
                    padding: '0.5rem 0.75rem',
                    borderRadius: STITCH_RADIUS.md,
                    backgroundColor: isActive
                      ? 'rgba(255, 21, 112, 0.06)'
                      : 'transparent',
                    color: isActive
                      ? STITCH_COLORS.textHeading
                      : STITCH_COLORS.textSecondary,
                    fontWeight: isActive ? 700 : 600,
                    fontSize: '0.9rem',
                  }}
                >
                  <div
                    style={{
                      width: 26,
                      height: 26,
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
                      fontSize: '0.78rem',
                    }}
                  >
                    {isDone ? (
                      <span aria-hidden="true">✓</span>
                    ) : isActive ? (
                      <span
                        aria-hidden="true"
                        style={{
                          width: 12,
                          height: 12,
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

          <p
            style={{
              margin: '1.1rem auto 0',
              maxWidth: 460,
              fontSize: '0.84rem',
              lineHeight: 1.55,
              color: STITCH_COLORS.textSecondary,
            }}
          >
            {isImageBeta
              ? 'Image uploads may return a partial preview. '
              : 'Checking each row before summarizing. '}
            Only supported rows enter the summary; unsupported rows stay visible.
            Usually a few seconds.
          </p>
        </SurfaceCard>
      </div>
    </PageChrome>
  );
}
