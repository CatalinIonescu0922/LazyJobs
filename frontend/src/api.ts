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
  source_url: string;
  kind: string;
  status: string;
  reason: string;
  extraction: string;
  posting_count: number;
  last_refreshed_at: string | null;
};

export type Job = {
  id: number;
  title: string;
  company: string;
  logo_url: string;
  locations: string[];
  work_mode: string;
  experience_level: string | null;
  employment_type: string;
  description: string;
  url: string;
  apply_url: string;
  posted_at: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  source: string;
};

export type JobFilters = {
  query?: string;
  location?: string;
  mode?: string;
  days?: number | null;
};

export type JobSearchResult = {
  jobs: Job[];
  refreshed: boolean;
  match_scope: string;
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

export function addSource(url: string): Promise<Source> {
  return api<Source>("/api/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, kind: "career" }),
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

export function listJobs(filters: JobFilters = {}): Promise<JobSearchResult> {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.location) params.set("location", filters.location);
  if (filters.mode) params.set("mode", filters.mode);
  if (filters.days) params.set("days", String(filters.days));
  const suffix = params.toString();
  return api<JobSearchResult>(`/api/jobs${suffix ? `?${suffix}` : ""}`);
}

export function searchJobs(filters: JobFilters = {}): Promise<JobSearchResult> {
  return api<JobSearchResult>("/api/jobs/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...filters, refresh: true }),
  });
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

export type CompanyCounts = { total: number; feed: number; none: number; unchecked: number };

export type FeedCard = {
  source_id: number;
  name: string;
  provider: string;
  provider_label: string;
  slug: string;
  status: string;
  reason: string;
  jobs: number;
  last_refreshed_at: string | null;
  domain: string;
  logo_url: string;
  careers_url: string;
};

export type CompanyCard = {
  id: number;
  name: string;
  postings: number;
  status: string;
  provider: string;
  provider_label: string;
  slug: string;
  domain: string;
  logo_url: string;
  checked_at: string | null;
  jobs: number | null;
  source_status: string | null;
};

export type CompaniesResponse = {
  counts: CompanyCounts;
  feeds: FeedCard[];
  companies: CompanyCard[];
  total_matching: number;
};

export type CompanyStatusFilter = "all" | "feed" | "none" | "unchecked";

export type CompaniesParams = {
  status: CompanyStatusFilter;
  search: string;
  limit: number;
  offset: number;
};

export function listCompanies({ status, search, limit, offset }: CompaniesParams): Promise<CompaniesResponse> {
  const params = new URLSearchParams({ status, limit: String(limit), offset: String(offset) });
  if (search) params.set("search", search);
  return api<CompaniesResponse>(`/api/companies?${params}`);
}

export function companiesQuery(params: CompaniesParams) {
  return queryOptions({
    queryKey: ["companies", params],
    queryFn: () => listCompanies(params),
    retry: false,
    staleTime: 60_000,
  });
}
