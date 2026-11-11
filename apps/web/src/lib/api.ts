"use client";

import { publicConfig } from "@/lib/config";
import { supabaseBrowser } from "@/lib/supabase/client";

/** RFC 9457 problem details returned by the SellerScope API. */
export interface Problem {
  title: string;
  status: number;
  code: string;
  detail?: string;
  errors?: { loc: (string | number)[]; msg: string }[];
}

export class ApiError extends Error {
  constructor(public readonly problem: Problem) {
    super(problem.detail ?? problem.title);
  }
  get status() {
    return this.problem.status;
  }
  get code() {
    return this.problem.code;
  }
}

export async function parseProblem(response: Response): Promise<Problem> {
  try {
    const body = (await response.json()) as Partial<Problem>;
    return {
      title: body.title ?? response.statusText,
      status: body.status ?? response.status,
      code: body.code ?? "http_error",
      detail: body.detail ?? body.errors?.map((e) => e.msg).join("; "),
      errors: body.errors,
    };
  } catch {
    return { title: response.statusText || "Request failed", status: response.status, code: "http_error" };
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  /** Organization the request acts on (sent as X-Organization-Id). */
  orgId?: string | null;
}

/** Calls the API with the current session's access token. Throws ApiError on failure. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const {
    data: { session },
  } = await supabaseBrowser().auth.getSession();
  const headers: Record<string, string> = {};
  if (session) headers.Authorization = `Bearer ${session.access_token}`;
  if (options.orgId) headers["X-Organization-Id"] = options.orgId;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(`${publicConfig.apiUrl}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (!response.ok) throw new ApiError(await parseProblem(response));
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
