/**
 * Typed fetch wrapper around the Django API.
 *
 * Every backend failure arrives in the same error envelope, so this module turns
 * any non-2xx response, and any transport failure, into an `ApiError` carrying a
 * code, a dispatcher-readable message and optionally the form field to blame.
 */

import type { TripPlan, TripPlanRequest } from "../types/trip";

const CONFIGURED_BASE_URL = import.meta.env.VITE_API_BASE_URL;
const BASE_URL = (CONFIGURED_BASE_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");

/**
 * A deployed bundle with no `VITE_API_BASE_URL` falls back to localhost, which in
 * a browser means the visitor's own machine. Every request then fails as a
 * network error and the copy blames their connection for a misconfigured build.
 * Naming the real cause costs one branch.
 */
const MISCONFIGURED = import.meta.env.PROD && !CONFIGURED_BASE_URL;

/** A cold free-tier instance can take ~60s. Past this, something is wrong. */
const REQUEST_TIMEOUT_MS = 90_000;

export class ApiError extends Error {
  readonly code: string;
  readonly field: string | null;

  constructor(code: string, message: string, field: string | null = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.field = field;
  }
}

type ErrorEnvelope = {
  error?: { code?: string; message?: string; field?: string | null };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (MISCONFIGURED) {
    throw new ApiError(
      "NOT_CONFIGURED",
      "This site isn't pointed at its planning service yet. VITE_API_BASE_URL was not set when it was built.",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "TimeoutError") {
      throw new ApiError(
        "TIMEOUT",
        "The planning service didn't answer in time. It may still be waking up, so try again.",
      );
    }
    throw new ApiError(
      "NETWORK_ERROR",
      "We couldn't reach the planning service. Check your connection and try again.",
    );
  }

  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    const envelope = (body ?? {}) as ErrorEnvelope;
    throw new ApiError(
      envelope.error?.code ?? "INTERNAL_ERROR",
      envelope.error?.message ?? "Something went wrong planning that trip. Please try again.",
      envelope.error?.field ?? null,
    );
  }

  return body as T;
}

/** Wakes the free-tier backend. A failure here is not fatal. */
export async function checkHealth(): Promise<boolean> {
  try {
    await request<{ status: string }>("/api/v1/health");
    return true;
  } catch {
    return false;
  }
}

export function planTrip(payload: TripPlanRequest): Promise<TripPlan> {
  return request<TripPlan>("/api/v1/trips/plan", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
