/** API client for Elfie Labs Analyzer backend.
 *
 * When the backend is unreachable (network error) or returns a non-OK
 * response, these helpers fall back to deterministic mocked responses
 * built from the preview fixtures. This lets the UI/UX flows be walked
 * end-to-end without a live backend, purely for manual UX testing.
 *
 * Opt-out: set `VITE_DISABLE_API_MOCK=true` to disable the fallback.
 */

import { supabase } from '../lib/supabase';
import {
  getPreviewFixture,
  type PreviewVariant,
} from '../fixtures/stitchPreviewData';
import type { JobStatus, UploadResponse } from '../types';

const BASE_URL = '/api';

const MOCK_DISABLED =
  typeof import.meta !== 'undefined' &&
  import.meta.env?.VITE_DISABLE_API_MOCK === 'true';

const MOCK_JOB_PREFIX = 'mock-';
const MOCK_LANE: UploadResponse['lane_type'] = 'trusted_pdf';

// Rotate through preview variants so each upload feels distinct.
const MOCK_VARIANTS: PreviewVariant[] = [
  'fully_supported',
  'partially_supported',
  'could_not_assess',
];
let mockCallCounter = 0;

function variantForJobId(jobId: string): PreviewVariant {
  // Deterministic: derive variant from the job id so the same mock job
  // returns the same artifact across status/artifact calls.
  const hash = Array.from(jobId).reduce(
    (acc, ch) => (acc * 31 + ch.charCodeAt(0)) >>> 0,
    0,
  );
  return MOCK_VARIANTS[hash % MOCK_VARIANTS.length];
}

function isMockJobId(jobId: string): boolean {
  return jobId.startsWith(MOCK_JOB_PREFIX);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function blobResponse(body: string, contentType: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': contentType },
  });
}

async function authHeaders(): Promise<HeadersInit> {
  try {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (!session?.access_token) {
      return {};
    }
    return { Authorization: `Bearer ${session.access_token}` };
  } catch {
    return {};
  }
}

async function tryFetch(
  input: RequestInfo,
  init?: RequestInit,
): Promise<Response | null> {
  if (MOCK_DISABLED) {
    return fetch(input, init);
  }
  try {
    const response = await fetch(input, init);
    // Treat non-OK as "backend unavailable" for UX testing.
    if (!response.ok) {
      return null;
    }
    return response;
  } catch {
    return null;
  }
}

function mockUploadResponse(): Response {
  mockCallCounter += 1;
  const jobId = `${MOCK_JOB_PREFIX}${Date.now()}-${mockCallCounter}`;
  const body: UploadResponse = {
    job_id: jobId,
    status: 'accepted',
    lane_type: MOCK_LANE,
    message: 'Mock upload accepted (backend unavailable; using preview data).',
  };
  return jsonResponse(body, 202);
}

// Simulated pipeline steps so the processing screen animates through stages.
const MOCK_STEPS = [
  'preflight',
  'lane_selection',
  'extraction',
  'analyte_mapping',
  'patient_artifact',
] as const;

const mockJobProgress = new Map<string, number>();

function mockJobStatusResponse(jobId: string): Response {
  const prior = mockJobProgress.get(jobId) ?? -1;
  const next = Math.min(prior + 1, MOCK_STEPS.length - 1);
  mockJobProgress.set(jobId, next);

  const isDone = next >= MOCK_STEPS.length - 1;
  const body: JobStatus = {
    job_id: jobId,
    status: isDone ? 'completed' : 'running',
    step: MOCK_STEPS[next],
    lane_type: MOCK_LANE,
  };
  return jsonResponse(body);
}

function mockPatientArtifactResponse(jobId: string): Response {
  const variant = isMockJobId(jobId) ? variantForJobId(jobId) : 'fully_supported';
  const fixture = getPreviewFixture(variant, 'en');
  return jsonResponse(fixture.patientArtifact);
}

function mockClinicianArtifactResponse(jobId: string): Response {
  const variant = isMockJobId(jobId) ? variantForJobId(jobId) : 'fully_supported';
  const fixture = getPreviewFixture(variant, 'en');
  return jsonResponse(fixture.clinicianArtifact);
}

function mockClinicianPdfResponse(): Response {
  // Minimal placeholder PDF-ish payload so the download path exercises the UI.
  const placeholder =
    '%PDF-1.4\n% Mock clinician PDF (backend unavailable)\n%%EOF';
  return blobResponse(placeholder, 'application/pdf');
}

export async function uploadFile(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await tryFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
    headers: await authHeaders(),
  });
  return response ?? mockUploadResponse();
}

export async function getJobStatus(jobId: string): Promise<Response> {
  if (isMockJobId(jobId)) {
    return mockJobStatusResponse(jobId);
  }
  const response = await tryFetch(`${BASE_URL}/jobs/${jobId}/status`, {
    headers: await authHeaders(),
  });
  return response ?? mockJobStatusResponse(jobId);
}

export async function getPatientArtifact(jobId: string): Promise<Response> {
  if (isMockJobId(jobId)) {
    return mockPatientArtifactResponse(jobId);
  }
  const response = await tryFetch(`${BASE_URL}/artifacts/${jobId}/patient`, {
    headers: await authHeaders(),
  });
  return response ?? mockPatientArtifactResponse(jobId);
}

export async function getClinicianArtifact(jobId: string): Promise<Response> {
  if (isMockJobId(jobId)) {
    return mockClinicianArtifactResponse(jobId);
  }
  const response = await tryFetch(`${BASE_URL}/artifacts/${jobId}/clinician`, {
    headers: await authHeaders(),
  });
  return response ?? mockClinicianArtifactResponse(jobId);
}

export async function getClinicianPdf(jobId: string): Promise<Response> {
  if (isMockJobId(jobId)) {
    return mockClinicianPdfResponse();
  }
  const response = await tryFetch(`${BASE_URL}/artifacts/${jobId}/clinician/pdf`, {
    headers: await authHeaders(),
  });
  return response ?? mockClinicianPdfResponse();
}
