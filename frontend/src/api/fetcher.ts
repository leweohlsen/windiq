/** Fetch wrapper for the generated orval client: throws on non-2xx so
 * react-query surfaces the failure, and unwraps the JSON body. */
export async function customFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    throw new Error(`${options?.method ?? "GET"} ${url} failed (HTTP ${res.status})`);
  }
  return (await res.json()) as T;
}
