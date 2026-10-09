// Live runs spend Token Factory credit, so the hosted demo caps them per UTC day and in total.
// The FaultForge server keeps its own daily count in memory, but the container restarts after it
// sleeps, which would reset that count. These caps live in Durable Object storage instead.

export interface Store {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
}

export interface Caps {
  perDay: number;
  total: number;
}

const TOTAL = "live-runs-total";
const dayKey = (now: Date) => `live-runs-${now.toISOString().slice(0, 10)}`;

export async function remaining(store: Store, caps: Caps, now: Date): Promise<number> {
  const day = (await store.get<number>(dayKey(now))) ?? 0;
  const total = (await store.get<number>(TOTAL)) ?? 0;
  return Math.max(0, Math.min(caps.perDay - day, caps.total - total));
}

// Reserves one live run, or returns false when a cap is reached. Reserve before forwarding the
// request and release on failure: a Durable Object handles other requests while it awaits the
// container, so counting only after success could over-admit.
export async function reserve(store: Store, caps: Caps, now: Date): Promise<boolean> {
  if ((await remaining(store, caps, now)) === 0) return false;
  await bump(store, now, 1);
  return true;
}

export async function release(store: Store, now: Date): Promise<void> {
  await bump(store, now, -1);
}

async function bump(store: Store, now: Date, by: number): Promise<void> {
  const key = dayKey(now);
  await store.put(key, Math.max(0, ((await store.get<number>(key)) ?? 0) + by));
  await store.put(TOTAL, Math.max(0, ((await store.get<number>(TOTAL)) ?? 0) + by));
}
