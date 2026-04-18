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
/** How often the client advances its synthetic progress bar when the backend
 *  doesn't emit fine-grained pipeline substeps (common in the trusted-PDF
 *  lane where `step` flips from `preflight` → `lineage_persist`). */
const SYNTHETIC_TICK_MS = 400;
/** Target duration of the synthetic progress animation between "pending"
 *  and "completed" for a real backend job. Backend now emits per-stage
 *  `step` updates (jobs.current_step), so synthetic progress is only a
 *  between-step smoother. Set long enough to avoid pegging at 95% while
 *  hard PDFs (2 min) finish. */
const SYNTHETIC_TOTAL_MS = 45000;

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
  unsupported: 'Unsupported',
};

const KNOWN_BACKEND_STEPS: Record<string, number> = {
  preflight: 0,
  lane_selection: 1,
  extraction: 2,
  extraction_qa: 2,
  observation_build: 2,
  analyte_mapping: 3,
  ucum_conversion: 3,
  panel_reconstruction: 3,
  rule_evaluation: 3,
  severity_assignment: 3,
  nextstep_assignment: 3,
  patient_artifact: 4,
  clinician_artifact: 4,
  lineage_persist: 4,
};

/** Map a known backend step to a display-stage index. Returns null when the
 *  step is unknown (e.g. raw status strings like "running") so the caller
 *  can fall back to synthetic progress instead of snapping to the last
 *  stage like the previous implementation did. */
function displayStageIndexFromStep(step: string): number | null {
  if (!step) return null;
  const idx = KNOWN_BACKEND_STEPS[step];
  return idx === undefined ? null : idx;
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
  /** Monotonic client-side synthetic progress in range [0, 1]. Used when
   *  the backend does not expose fine-grained pipeline substeps. */
  const [syntheticProgress, setSyntheticProgress] = useState(0);
  const startedAtRef = useRef<number>(Date.now());

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
      setSyntheticProgress(1);
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

  // Synthetic progress ticker: drives the UI smoothly from 0 → ~0.95 over
  // SYNTHETIC_TOTAL_MS even when the backend only emits coarse statuses
  // ("pending" → "running" → "completed"). Capped below 1 until the poll
  // loop confirms completion, so the UI never claims success prematurely.
  useEffect(() => {
    if (error) return undefined;
    const tick = window.setInterval(() => {
      const elapsed = Date.now() - startedAtRef.current;
      // Ease-out cubic so early stages feel responsive and late stages slow
      // down, mimicking real pipeline behavior where late phases are heavier.
      const raw = Math.min(elapsed / SYNTHETIC_TOTAL_MS, 1);
      const eased = 1 - Math.pow(1 - raw, 3);
      // Keep capped at 0.95 until the backend confirms completion.
      setSyntheticProgress((prev) => Math.max(prev, Math.min(eased, 0.95)));
    }, SYNTHETIC_TICK_MS);
    return () => window.clearInterval(tick);
  }, [error]);

  const currentStep = status?.step ?? '';
  const backendStageIndex = displayStageIndexFromStep(currentStep);
  const syntheticStageIndex = Math.min(
    Math.floor(syntheticProgress * DISPLAY_STAGES.length),
    DISPLAY_STAGES.length - 1,
  );
  // Prefer the backend step when it names a real pipeline stage; otherwise
  // fall back to the synthetic ticker. Never regress the displayed stage.
  const activeStageIndex = Math.max(
    backendStageIndex ?? syntheticStageIndex,
    syntheticStageIndex,
  );
  const isImageBeta = laneType === 'image_beta';
  // Progress percent blends the stage-based view (so it snaps cleanly
  // when a known backend step arrives) with the synthetic ticker (so it
  // moves between polls instead of freezing). Uses whichever is greater.
  const stagePercent = Math.round(
    ((activeStageIndex + 1) / DISPLAY_STAGES.length) * 100,
  );
  const syntheticPercent = Math.round(syntheticProgress * 100);
  const progressPercent = Math.min(
    100,
    Math.max(stagePercent, syntheticPercent),
  );
  const circleRadius = 92;
  const circumference = 2 * Math.PI * circleRadius;
  const dashOffset =
    circumference - (Math.min(progressPercent, 100) / 100) * circumference;
  const backendLabel = currentStep
    ? BACKEND_STEP_LABELS[currentStep] ?? DISPLAY_STAGES[activeStageIndex]
    : DISPLAY_STAGES[activeStageIndex];

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
