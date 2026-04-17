/** API client for Elfie Labs Analyzer backend. */

import { supabase } from '../lib/supabase';

const BASE_URL = '/api';

async function authHeaders(): Promise<HeadersInit> {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  if (!session?.access_token) {
    return {};
  }
  return { Authorization: `Bearer ${session.access_token}` };
}

export async function uploadFile(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append('file', file);
  return fetch(`${BASE_URL}/upload`, {
    method: 'POST',
    body: formData,
    headers: await authHeaders(),
  });
}

export async function getJobStatus(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/jobs/${jobId}/status`, {
    headers: await authHeaders(),
  });
}

export async function getPatientArtifact(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/artifacts/${jobId}/patient`, {
    headers: await authHeaders(),
  });
}

export async function getClinicianArtifact(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/artifacts/${jobId}/clinician`, {
    headers: await authHeaders(),
  });
}

export async function getClinicianPdf(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/artifacts/${jobId}/clinician/pdf`, {
    headers: await authHeaders(),
  });
}
