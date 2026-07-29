// Generated forecast assets are gzip-compressed JSON (.json.gz) served as
// plain static files (GitHub Pages does not transparently decompress them
// on the fly), so we decompress in the browser using the native
// DecompressionStream API (supported in current Chrome, Firefox and
// Safari). Results are cached in memory for the life of the page.

const memoryCache = new Map<string, unknown>();
const inFlight = new Map<string, Promise<unknown>>();

export class FetchError extends Error {
  constructor(
    message: string,
    public readonly url: string,
    public readonly status?: number
  ) {
    super(message);
    this.name = "FetchError";
  }
}

function supportsDecompressionStream(): boolean {
  return typeof DecompressionStream !== "undefined";
}

async function decompressGzip(buffer: ArrayBuffer): Promise<string> {
  if (!supportsDecompressionStream()) {
    throw new Error(
      "This browser does not support native gzip decompression (DecompressionStream). " +
        "Please use a recent version of Chrome, Firefox, Safari or Edge."
    );
  }
  const stream = new Blob([buffer]).stream().pipeThrough(new DecompressionStream("gzip"));
  const decompressed = await new Response(stream).arrayBuffer();
  return new TextDecoder().decode(decompressed);
}

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 400;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchOnce<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal });
  } catch (err) {
    throw new FetchError(`Network error fetching ${url}: ${(err as Error).message}`, url);
  }
  if (!response.ok) {
    throw new FetchError(`Request to ${url} failed with status ${response.status}`, url, response.status);
  }
  const buffer = await response.arrayBuffer();
  const text = url.endsWith(".gz") ? await decompressGzip(buffer) : new TextDecoder().decode(buffer);
  return JSON.parse(text) as T;
}

export async function fetchJsonGz<T>(url: string, options?: { signal?: AbortSignal }): Promise<T> {
  if (memoryCache.has(url)) {
    return memoryCache.get(url) as T;
  }
  const existing = inFlight.get(url);
  if (existing) {
    return existing as Promise<T>;
  }

  // Retries with a short backoff make the app resilient to transient
  // network hiccups on first load (flaky Wi-Fi, cold CDN edge, etc.)
  // without masking persistent failures (still surfaced after retries).
  const promise = (async () => {
    let lastError: unknown;
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        const data = await fetchOnce<T>(url, options?.signal);
        memoryCache.set(url, data);
        return data;
      } catch (err) {
        lastError = err;
        if (attempt < MAX_RETRIES) await delay(RETRY_DELAY_MS * (attempt + 1));
      }
    }
    throw lastError;
  })();

  inFlight.set(url, promise);
  try {
    return await promise;
  } finally {
    inFlight.delete(url);
  }
}

export function clearFetchCache(): void {
  memoryCache.clear();
}
