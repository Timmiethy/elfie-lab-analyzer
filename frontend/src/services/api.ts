/** API client for Elfie Labs Analyzer backend. */

const BASE_URL = '/api';

export async function uploadFile(file: File): Promise<Response> {
  const formData = new FormData();
  formData.append('file', file);
  return fetch(`${BASE_URL}/upload`, { method: 'POST', body: formData });
}

export async function getJobStatus(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/jobs/${jobId}/status`);
}

export async function getPatientArtifact(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/artifacts/${jobId}/patient`);
}

export async function getClinicianArtifact(jobId: string): Promise<Response> {
  return fetch(`${BASE_URL}/artifacts/${jobId}/clinician`);
}
