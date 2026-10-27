import { queryOptions } from "@tanstack/react-query";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // The body is not JSON; fall back to the status text below.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (response.status === 401 && window.location.pathname !== "/sign-in") {
    window.location.assign("/sign-in");
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export type Me = {
  id: number;
  email: string;
  name: string;
  avatar_url: string;
};

export type Profile = {
  id: number;
  cv_filename: string;
  full_name: string;
  headline: string;
  summary: string;
  titles: string[];
  skills: string[];
  years_experience: number;
  country: string;
  city: string;
  salary_currency: string;
  preferred_locations: string[];
  remote_only: boolean;
  min_salary: number;
  extra_keywords: string[];
  has_cv: boolean;
};

export type Source = {
  id: number;
  domain: string;
  kind: string;
  status: string;
  reason: string;
  extraction: string;
  posting_count: number;
  last_refreshed_at: string | null;
};

// A 401 means signed out, which is an answer, not a failure worth retrying.
export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: () => api<Me>("/api/auth/me"),
  retry: false,
});

export const profileQuery = queryOptions({
  queryKey: ["profile"],
  queryFn: () => api<Profile>("/api/profile"),
  retry: false,
});

export const sourcesQuery = queryOptions({
  queryKey: ["sources"],
  queryFn: () => api<Source[]>("/api/sources"),
  retry: false,
});

export function discoverSources(kind: string): Promise<{ created: number; proposed: number }> {
  return api(`/api/sources/discover?kind=${encodeURIComponent(kind)}`, { method: "POST" });
}

export function addSource(domain: string): Promise<Source> {
  return api<Source>("/api/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ domain, kind: "board" }),
  });
}

export function updateSource(id: number, enabled: boolean): Promise<Source> {
  return api<Source>(`/api/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export function refreshSource(id: number): Promise<{ added: number; failed: number; status: string }> {
  return api(`/api/sources/${id}/refresh`, { method: "POST" });
}

export type ProfileUpdate = Omit<
  Profile,
  "id" | "cv_filename" | "has_cv"
>;

export function updateProfile(update: ProfileUpdate): Promise<Profile> {
  return api<Profile>("/api/profile", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
}

export function uploadCv(file: File): Promise<Profile> {
  const body = new FormData();
  body.append("file", file);
  return api<Profile>("/api/profile/cv", { method: "POST", body });
}

export function logout(): Promise<void> {
  return api<void>("/api/auth/logout", { method: "POST" });
}
