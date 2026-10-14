import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunEvent } from "../api/client";
import { useRunEvents } from "./useRunEvents";

class MockEventSource {
  static instances: MockEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  listeners = new Map<string, EventListener>();

  constructor(readonly url: string) {
    MockEventSource.instances.push(this);
  }

  close() { this.closed = true; }
  addEventListener(type: string, listener: EventListener) { this.listeners.set(type, listener); }
  removeEventListener(type: string) { this.listeners.delete(type); }
}

function event(sequence: number, type = "stage_started"): RunEvent {
  return { sequence, type, stage: "research", attempt: 1, level: "info", message: `Event ${sequence}`, payload: {}, created_at: "2026-10-01T10:00:00Z" };
}

describe("useRunEvents", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("CF-REQ-602 consumes SSE events once and leaves native Last-Event-ID reconnection active", async () => {
    const { result } = renderHook(() => useRunEvents("run-1", [event(1)]));
    const source = MockEventSource.instances[0]!;
    expect(source.url).toBe("/api/runs/run-1/events/stream");

    act(() => source.onopen?.());
    act(() => source.listeners.get("stage_started")?.(new MessageEvent("stage_started", { data: JSON.stringify(event(2)) })));
    act(() => source.onmessage?.(new MessageEvent("message", { data: JSON.stringify(event(2)) })));

    expect(result.current.connectionState).toBe("live");
    expect(result.current.events.map((item) => item.sequence)).toEqual([1, 2]);
    expect(source.closed).toBe(false);
  });

  it("CF-REQ-602 falls back to sequence polling after repeated SSE errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [event(3, "run_completed")] }), { status: 200 })));
    const { result } = renderHook(() => useRunEvents("run-1", [event(2)]));
    const source = MockEventSource.instances[0]!;

    act(() => { source.onerror?.(); source.onerror?.(); source.onerror?.(); });

    await waitFor(() => expect(result.current.connectionState).toBe("complete"));
    expect(fetch).toHaveBeenCalledWith("/api/runs/run-1/events?after_sequence=2", expect.any(Object));
    expect(result.current.events.map((item) => item.sequence)).toEqual([2, 3]);
  });
});