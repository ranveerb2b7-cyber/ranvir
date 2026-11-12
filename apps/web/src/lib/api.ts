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

async function accessToken(): Promise<string | null> {
  const {
    data: { session },
  } = await supabaseBrowser().auth.getSession();
  return session?.access_token ?? null;
}

/** Multipart upload with progress reporting (fetch cannot report upload progress). */
export async function apiUpload<T>(
  path: string,
  file: File,
  orgId: string,
  onProgress: (fraction: number) => void,
): Promise<T> {
  const token = await accessToken();
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${publicConfig.apiUrl}${path}`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("X-Organization-Id", orgId);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onerror = () =>
      reject(new ApiError({ title: "Network error: the upload did not reach the server.", status: 0, code: "network_error" }));
    xhr.onload = async () => {
      const response = new Response(xhr.responseText, { status: xhr.status, statusText: xhr.statusText });
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText) as T);
      else reject(new ApiError(await parseProblem(response)));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

/** Downloads an authenticated file (e.g. CSV export) and saves it in the browser. */
export async function apiDownload(path: string, orgId: string | null, fallbackName: string): Promise<void> {
  const token = await accessToken();
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (orgId) headers["X-Organization-Id"] = orgId;
  const response = await fetch(`${publicConfig.apiUrl}${path}`, { headers });
  if (!response.ok) throw new ApiError(await parseProblem(response));
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}
