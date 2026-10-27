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

// A 401 means signed out, which is an answer, not a failure worth retrying.
export const meQuery = queryOptions({
  queryKey: ["me"],
  queryFn: () => api<Me>("/api/auth/me"),
  retry: false,
});

export function logout(): Promise<void> {
  return api<void>("/api/auth/logout", { method: "POST" });
}
