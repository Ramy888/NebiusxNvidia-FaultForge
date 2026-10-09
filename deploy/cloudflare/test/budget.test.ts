import { describe, expect, it } from "vitest";
import { type Store, release, remaining, reserve } from "../src/budget";

class MemoryStore implements Store {
  data = new Map<string, unknown>();
  async get<T>(key: string) { return this.data.get(key) as T | undefined; }
  async put<T>(key: string, value: T) { this.data.set(key, value); }
}

const day1 = new Date("2026-10-09T10:00:00Z");
const day2 = new Date("2026-10-10T00:00:01Z");

describe("live-run budget", () => {
  it("allows the daily cap, then refuses", async () => {
    const store = new MemoryStore();
    const caps = { perDay: 2, total: 100 };
    expect(await reserve(store, caps, day1)).toBe(true);
    expect(await reserve(store, caps, day1)).toBe(true);
    expect(await reserve(store, caps, day1)).toBe(false);
    expect(await remaining(store, caps, day1)).toBe(0);
  });

  it("starts a new day at UTC midnight", async () => {
    const store = new MemoryStore();
    const caps = { perDay: 1, total: 100 };
    expect(await reserve(store, caps, day1)).toBe(true);
    expect(await reserve(store, caps, day1)).toBe(false);
    expect(await reserve(store, caps, day2)).toBe(true);
  });

  it("enforces the lifetime cap across days", async () => {
    const store = new MemoryStore();
    const caps = { perDay: 5, total: 2 };
    expect(await reserve(store, caps, day1)).toBe(true);
    expect(await reserve(store, caps, day2)).toBe(true);
    expect(await reserve(store, caps, day2)).toBe(false);
    expect(await remaining(store, caps, day2)).toBe(0);
  });

  it("gives a reservation back when the run did not start", async () => {
    const store = new MemoryStore();
    const caps = { perDay: 1, total: 1 };
    expect(await reserve(store, caps, day1)).toBe(true);
    await release(store, day1);
    expect(await remaining(store, caps, day1)).toBe(1);
    expect(await reserve(store, caps, day1)).toBe(true);
  });

  it("never counts below zero", async () => {
    const store = new MemoryStore();
    await release(store, day1);
    expect(await remaining(store, { perDay: 3, total: 3 }, day1)).toBe(3);
  });
});
