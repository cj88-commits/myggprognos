// Mirrors forecast/src/output.py::shard_for_cell_id -- a stable djb2 hash,
// NOT JavaScript's non-existent built-in hash (there isn't one) and NOT
// anything based on object identity, so the frontend independently
// computes the exact same shard index the pipeline used to write
// series/<shard>.json.gz, without needing a lookup table. Keep both in
// sync if either changes.
export function shardForCellId(cellId: string, shardCount: number): number {
  let h = 5381;
  for (let i = 0; i < cellId.length; i++) {
    h = (Math.imul(h, 33) + cellId.charCodeAt(i)) >>> 0;
  }
  return h % shardCount;
}
