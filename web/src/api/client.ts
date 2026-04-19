const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public payload: unknown,
  ) {
    super(message);
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
  if (!res.ok) {
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      /* body not JSON — leave null */
    }
    const envelope = (payload as { error?: { code?: string; message?: string } })?.error;
    throw new ApiError(
      envelope?.code ?? `http_${res.status}`,
      envelope?.message ?? res.statusText,
      res.status,
      payload,
    );
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}
