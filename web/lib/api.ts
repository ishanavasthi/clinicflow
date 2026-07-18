/** Thin client for the ClinicFlow FastAPI server. */
import type {
  CallDetailData,
  CallListItem,
  Department,
  FAQ,
  TokenResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Absolute URL for a server-served media path (e.g. a recording). */
export function mediaUrl(path: string): string {
  return `${API_URL}${path}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response had no JSON body; keep the status text
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function fetchToken(
  role: "caller" | "observer",
  room?: string,
): Promise<TokenResponse> {
  return request<TokenResponse>("/token", {
    method: "POST",
    body: JSON.stringify({ role, room }),
  });
}

export function fetchDepartments(): Promise<Department[]> {
  return request<Department[]>("/departments");
}

export function fetchFaqs(): Promise<FAQ[]> {
  return request<FAQ[]>("/faqs");
}

export function fetchCalls(): Promise<CallListItem[]> {
  return request<CallListItem[]>("/calls");
}

export function fetchCall(id: number): Promise<CallDetailData> {
  return request<CallDetailData>(`/calls/${id}`);
}

/** Upload a call recording blob. Returns the server URL to fetch it back. */
export async function uploadRecording(
  callId: number,
  blob: Blob,
): Promise<string> {
  const res = await fetch(`${API_URL}/calls/${callId}/recording`, {
    method: "POST",
    headers: { "Content-Type": blob.type || "audio/webm" },
    body: blob,
  });
  if (!res.ok) throw new Error("Recording upload failed");
  const data = (await res.json()) as { recording_url: string };
  return `${API_URL}${data.recording_url}`;
}

/** Patch a patient record with edited intake fields. */
export function updatePatient(
  patientId: number,
  fields: Record<string, string>,
): Promise<unknown> {
  return request(`/patients/${patientId}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
}
