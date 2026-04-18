/** API client for Elfie Labs Analyzer backend.
 *
 * Mock behavior (post-hardening):
 *
 *   - Default: fall back to mock fixtures **only when the backend is
 *     unreachable** (fetch itself rejects — DNS, connection refused,
 *     TLS error, CORS preflight failure). Any HTTP response from the
 *     backend (200, 401, 404, 500, 502…) is returned verbatim so the
 *     UI can render real errors instead of silently substituting a
 *     "fully supported" fixture.
 *
 *   - VITE_DISABLE_API_MOCK=true → never mock, even on network error.
 *     Use this during real dev/QA so any failure is visible.
 *
 *   - VITE_FORCE_MOCK=true → always mock, skip fetch entirely. Use this
 *     for UI-only demos with no backend running.
 *
 * Every mocked response is marked with:
 *   - HTTP header   X-Elfie-Mock: 1
 *   - JSON body     is_mocked: true      (best-effort)
 *
 * so the UI and any downstream test can detect and flag fake data.
 */

import { supabase } from '../lib/supabase';
import {
  getPreviewFixture,
  type PreviewVariant,
} from '../fixtures/stitchPreviewData';
import { markMocked } from '../components/common/mockBanner';
import type { JobStatus, UploadResponse } from '../types';

const API_ORIGIN = (
  (typeof import.meta !== 'undefined' ? import.meta.env?.VITE_API_URL : '') || ''
).replace(/\/+$/, '');
const BASE_URL = API_ORIGIN ? `${API_ORIGIN}/api` : '/api';

const ENV = typeof import.meta !== 'undefined' ? import.meta.env : undefined;

const MOCK_DISABLED = ENV?.VITE_DISABLE_API_MOCK === 'true';
const MOCK_FORCED = ENV?.VITE_FORCE_MOCK === 'true';

const MOCK_JOB_PREFIX = 'mock-';
const MOCK_LANE: UploadResponse['lane_type'] = 'trusted_pdf';

const MOCK_HEADERS = {
  'Content-Type': 'application/json',
  'X-Elfie-Mock': '1',
} as const;

// Rotate through preview variants so each upload feels distinct.
const MOCK_VARIANTS: PreviewVariant[] = [
  'fully_supported',
  'partially_supported',
  'could_not_assess',
];
let mockCallCounter = 0;

function variantForJobId(jobId: string): PreviewVariant {
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
  return new Response(JSON.stringify(body), { status, headers: MOCK_HEADERS });
}

function blobResponse(body: string, contentType: string, status = 200): Response {
  return new Response(body, {
    status,
    headers: { 'Content-Type': contentType, 'X-Elfie-Mock': '1' },
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

/**
 * Perform a fetch. Only returns null (→ caller falls back to mock) when the
 * backend is genuinely unreachable. HTTP errors (4xx/5xx) are returned as-is.
 */
async function realFetch(
  input: RequestInfo,
  init?: RequestInit,
): Promise<Response | null> {
  try {
    return await fetch(input, init);
  } catch (err) {
    if (import.meta.env.DEV) {
      // eslint-disable-next-line no-console
      console.warn('[api] network error — backend unreachable', input, err);
    }
    return null;
  }
}

function shouldUseMock(realResponse: Response | null): boolean {
  if (MOCK_FORCED) {
    markMocked('VITE_FORCE_MOCK=true');
    return true;
  }
  if (MOCK_DISABLED) return false;
  if (realResponse === null) {
    markMocked('backend unreachable (network error)');
    return true;
  }
  return false;
}

function mockUploadResponse(): Response {
  mockCallCounter += 1;
  const jobId = `${MOCK_JOB_PREFIX}${Date.now()}-${mockCallCounter}`;
  const body: UploadResponse = {
    job_id: jobId,
    status: 'pending',
    lane_type: MOCK_LANE,
    message: 'Mock upload accepted (backend unreachable; using preview data).',
    is_mocked: true,
  };
  return jsonResponse(body, 202);
}

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
    status: isDone ? 'completed' : 'pending',
    step: MOCK_STEPS[next],
    lane_type: MOCK_LANE,
    is_mocked: true,
  };
  return jsonResponse(body);
}

function mockPatientArtifactResponse(jobId: string): Response {
  const variant = isMockJobId(jobId) ? variantForJobId(jobId) : 'fully_supported';
  const fixture = getPreviewFixture(variant, 'en');
  return jsonResponse({ ...fixture.patientArtifact, is_mocked: true });
}

function mockClinicianArtifactResponse(jobId: string): Response {
  const variant = isMockJobId(jobId) ? variantForJobId(jobId) : 'fully_supported';
  const fixture = getPreviewFixture(variant, 'en');
  return jsonResponse({ ...fixture.clinicianArtifact, is_mocked: true });
}

function mockClinicianPdfResponse(): Response {
  const placeholder =
    '%PDF-1.4\n% Mock clinician PDF (backend unreachable)\n%%EOF';
  return blobResponse(placeholder, 'application/pdf');
}

// ---------------------------------------------------------------------------
// Public API helpers
// ---------------------------------------------------------------------------

export async function uploadFile(file: File): Promise<Response> {
  if (MOCK_FORCED) return mockUploadResponse();

  const formData = new FormData();
  formData.append('file', file);

  const response = await realFetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockUploadResponse();
  return response as Response;
}

export async function getJobStatus(jobId: string): Promise<Response> {
  if (isMockJobId(jobId) || MOCK_FORCED) return mockJobStatusResponse(jobId);

  const response = await realFetch(`${BASE_URL}/jobs/${jobId}/status`, {
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockJobStatusResponse(jobId);
  return response as Response;
}

export async function getPatientArtifact(jobId: string): Promise<Response> {
  if (isMockJobId(jobId) || MOCK_FORCED) return mockPatientArtifactResponse(jobId);

  const response = await realFetch(`${BASE_URL}/artifacts/${jobId}/patient`, {
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockPatientArtifactResponse(jobId);
  return response as Response;
}

export async function getClinicianArtifact(jobId: string): Promise<Response> {
  if (isMockJobId(jobId) || MOCK_FORCED) return mockClinicianArtifactResponse(jobId);

  const response = await realFetch(`${BASE_URL}/artifacts/${jobId}/clinician`, {
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockClinicianArtifactResponse(jobId);
  return response as Response;
}

export async function getClinicianPdf(jobId: string): Promise<Response> {
  if (isMockJobId(jobId) || MOCK_FORCED) return mockClinicianPdfResponse();

  const response = await realFetch(`${BASE_URL}/artifacts/${jobId}/clinician/pdf`, {
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockClinicianPdfResponse();
  return response as Response;
}

export async function getPatientPdf(jobId: string): Promise<Response> {
  if (isMockJobId(jobId) || MOCK_FORCED) return mockClinicianPdfResponse();

  const response = await realFetch(`${BASE_URL}/artifacts/${jobId}/patient/pdf`, {
    headers: await authHeaders(),
  });
  if (shouldUseMock(response)) return mockClinicianPdfResponse();
  return response as Response;
}

/** True if the given Response was produced by the local mock layer. */
export function isMockedResponse(response: Response): boolean {
  return response.headers.get('X-Elfie-Mock') === '1';
}
