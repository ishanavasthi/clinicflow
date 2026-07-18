/** Thin client for the ClinicFlow FastAPI server. */
import type { Department, FAQ, TokenResponse } from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
