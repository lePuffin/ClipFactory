import { useEffect, useRef, useState } from "react";

import type { RunEvent } from "../api/client";
import { apiGet } from "../api/client";

type ConnectionState = "connecting" | "live" | "polling" | "complete" | "error";
const EVENT_TYPES = [
  "run_created", "run_started", "stage_started", "stage_completed", "stage_failed", "stage_skipped",
  "research_completed", "stories_clustered", "story_selected", "sources_collected", "claims_extracted",
  "story_package_built", "script_generated", "visual_plan_generated", "assets_selected", "assets_generated",
  "audio_generated", "transcription_completed", "captions_generated", "composition_completed",
  "validation_completed", "evaluation_completed", "retry_started", "retry_planned",
  "publication_started", "publication_completed", "publication_failed", "publication_awaiting_approval",
  "publication_approval_resolved", "provider_call_failed", "llm_call_started", "llm_call_completed",
  "progress", "warning", "run_completed", "run_failed", "run_resumed", "run_stop_requested",
];

export function useRunEvents(runId: string, initialEvents: RunEvent[] = []) {
  const [events, setEvents] = useState<RunEvent[]>(initialEvents);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const lastSequence = useRef(Math.max(0, ...initialEvents.map((event) => event.sequence)));

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    let failures = 0;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events/stream`);

    function append(incoming: RunEvent[]) {
      const fresh = incoming.filter((event) => event.sequence > lastSequence.current).sort((left, right) => left.sequence - right.sequence);
      if (!fresh.length) return;
      lastSequence.current = fresh.at(-1)!.sequence;
      setEvents((current) => [...current, ...fresh]);
      if (fresh.some((event) => event.type === "run_completed" || event.type === "run_failed")) {
        setConnectionState("complete");
        source.close();
        if (pollTimer) clearTimeout(pollTimer);
      }
    }

    async function poll() {
      if (stopped) return;
      setConnectionState("polling");
      try {
        const result = await apiGet<{ items: RunEvent[] }>(`/api/runs/${encodeURIComponent(runId)}/events?after_sequence=${lastSequence.current}`);
        append(result.items);
        if (!stopped && !result.items.some((event) => event.type === "run_completed" || event.type === "run_failed")) {
          pollTimer = setTimeout(() => void poll(), 2000);
        }
      } catch {
        setConnectionState("error");
        if (!stopped) pollTimer = setTimeout(() => void poll(), 4000);
      }
    }

    source.onopen = () => {
      failures = 0;
      setConnectionState("live");
    };
    const receive = (message: MessageEvent<string>) => {
      try {
        append([JSON.parse(message.data) as RunEvent]);
      } catch {
        setConnectionState("error");
      }
    };
    source.onmessage = receive;
    EVENT_TYPES.forEach((type) => source.addEventListener(type, receive as EventListener));
    source.onerror = () => {
      failures += 1;
      setConnectionState("connecting");
      if (failures >= 3) {
        source.close();
        void poll();
      }
    };

    return () => {
      stopped = true;
      EVENT_TYPES.forEach((type) => source.removeEventListener(type, receive as EventListener));
      source.close();
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [runId]);

  return { events, connectionState };
}