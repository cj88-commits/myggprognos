// Runs async tasks with bounded concurrency instead of firing them all at
// once. Loading a location's full 7-day + 48-hour series means up to ~56
// small file requests; without a cap, that can exceed browser/proxy
// concurrent-connection limits and produce spurious "failed to fetch"
// errors, especially in constrained network environments.
export async function mapWithConcurrency<T, R>(
  items: T[],
  limit: number,
  fn: (item: T, index: number) => Promise<R>
): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let cursor = 0;

  async function worker() {
    while (cursor < items.length) {
      const index = cursor++;
      results[index] = await fn(items[index], index);
    }
  }

  const workers = Array.from({ length: Math.min(limit, items.length) }, worker);
  await Promise.all(workers);
  return results;
}
