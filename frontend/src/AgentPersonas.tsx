import type { RunEvent, RunSummary } from "./api/client";

const roles = [
  { name: "Scout", role: "Research & discovery", stages: ["research", "ingest_url", "cluster_stories", "select_story"], color: "#e5bb83" },
  { name: "Sage", role: "Sources & claims", stages: ["gather_sources", "extract_claims", "build_story_package"], color: "#a9b6ed" },
  { name: "Scribe", role: "Script & visual plan", stages: ["write_script", "plan_visuals"], color: "#d9a4ca" },
  { name: "Pixel", role: "Asset selection", stages: ["select_assets"], color: "#80c8c5" },
  { name: "Echo", role: "Narration & captions", stages: ["generate_narration", "transcribe_narration", "build_captions"], color: "#f0ac8e" },
  { name: "Frame", role: "Composition", stages: ["compose_clip"], color: "#9fbded" },
  { name: "Guard", role: "Validation & evaluation", stages: ["validate_clip", "evaluate_clip", "plan_retry"], color: "#bfd389" },
  { name: "Relay", role: "Publishing", stages: ["publish"], color: "#adcfb2" },
];
type Mood = "waiting" | "working" | "success" | "failure";
const captions: Record<Mood, string> = { waiting: "Waiting", working: "Working", success: "Success", failure: "Failure" };

function roleMood(stages: string[], run: RunSummary | null, events: RunEvent[]): Mood {
  if (!run) return "waiting";
  const terminal = events.filter((event) => ["run_completed", "run_failed"].includes(event.type)).at(-1);
  const status = terminal?.type === "run_completed" ? "completed" : terminal?.type === "run_failed" ? "failed" : run.status;
  const lastStage = events.filter((event) => event.stage).at(-1)?.stage ?? run.current_stage ?? run.failure_stage;
  const lifecycle = events.filter((event) => stages.includes(event.stage ?? "") && ["stage_started", "stage_completed", "stage_failed", "stage_skipped"].includes(event.type)).at(-1);
  if (status === "failed" && stages.includes(lastStage ?? "")) return "failure";
  if (lifecycle?.type === "stage_failed") return "failure";
  if (status === "completed") return "success";
  if (status === "queued") return "waiting";
  if (stages.includes(lastStage ?? "")) return lifecycle?.type === "stage_completed" || lifecycle?.type === "stage_skipped" ? "success" : "working";
  if (lifecycle?.type === "stage_completed" || lifecycle?.type === "stage_skipped") return "success";
  // Stages emit only stage_started; once a later Stage owned by another role starts, this role's work is done.
  return lifecycle?.type === "stage_started" ? "success" : "waiting";
}

export function AgentPersonas({ run, events }: { run: RunSummary | null; events: RunEvent[] }) {
  const resumed = events.filter((event) => event.type === "run_resumed").at(-1)?.sequence ?? 0;
  const current = events.filter((event) => event.sequence >= resumed);
  return <section className="agent-team" aria-label="Agent Roles">
    <h3>Agents</h3>
    <div className="persona-grid">{roles.map((agent, index) => {
      const mood = roleMood(agent.stages, run, current);
      return <article className={`persona ${mood}`} key={agent.name} aria-label={`${agent.name}: ${captions[mood]}`}>
        <Character mood={mood} color={agent.color} variant={index} />
        <strong>{agent.name}</strong><span className="persona-role">{agent.role}</span><small>{captions[mood]}</small>
      </article>;
    })}</div>
  </section>;
}

// Flat, human portraits with a shared silhouette and role-specific styling.
const portraits = [
  { skin: "#c98d6c", hair: "#302d32", style: "M28 42 C23 17 42 10 57 16 C69 8 83 19 78 41 L71 32 C58 39 48 24 35 35 Z" },
  { skin: "#efc4a2", hair: "#c7cdd0", style: "M27 43 C22 22 37 12 51 14 C71 8 86 23 78 45 L72 32 C60 29 47 35 35 29 Z" },
  { skin: "#d6a180", hair: "#49364b", style: "M25 68 L25 35 C25 7 80 7 80 35 L82 69 L70 65 L70 34 C58 40 44 33 35 30 L35 65 Z" },
  { skin: "#f0c6aa", hair: "#5a4540", style: "M27 42 C19 31 28 16 39 17 C42 6 55 8 60 15 C74 7 86 23 77 42 L71 29 C62 40 48 23 35 34 Z" },
  { skin: "#9d6a50", hair: "#29292e", style: "M24 47 C16 39 22 29 25 27 C18 16 31 9 39 13 C44 4 59 6 62 12 C74 8 86 18 81 27 C90 34 82 45 79 48 L71 34 L35 34 Z" },
  { skin: "#e5b28c", hair: "#a36e48", style: "M27 43 L27 29 C27 12 44 9 59 14 C77 13 84 28 77 44 L71 30 L62 29 L54 35 L36 30 Z" },
  { skin: "#b77e60", hair: "#343b40", style: "M27 42 L27 28 C29 9 76 9 78 28 L78 42 L71 32 C59 27 45 28 35 33 Z" },
  { skin: "#f0c1a0", hair: "#71544d", style: "M26 58 L25 34 C25 17 40 12 53 13 C72 10 82 25 80 43 L78 59 L70 50 L70 29 C62 38 46 30 35 37 L35 51 Z" },
] as const;

function Character({ mood, color, variant }: { mood: Mood; color: string; variant: number }) {
  const happy = mood === "success";
  const sad = mood === "failure";
  const focused = mood === "working";
  const portrait = portraits[variant] ?? portraits[0];
  return <svg className="persona-art" viewBox="0 0 104 112" aria-hidden="true" focusable="false">
    <circle cx="52" cy="53" r="43" fill={color} opacity=".08" />
    <g className="persona-body" transform={sad ? "translate(0 3)" : happy ? "rotate(-3 52 80)" : undefined}>
      {variant === 7 && <circle cx="77" cy="24" r="12" fill={portrait.hair} />}
      {variant === 2 && <path d="M25 62 L24 37 C24 5 81 5 81 37 L82 69 Z" fill={portrait.hair} />}
      <path d="M18 106 L21 87 C23 76 36 72 52 72 C68 72 81 76 83 87 L86 106 Z" fill={color} />
      <path d="M43 69 L43 78 Q52 87 61 78 L61 69" fill={portrait.skin} />
      <path d="M39 77 L44 87 L52 82 L60 87 L65 77" fill="none" stroke="#101313" strokeOpacity=".25" strokeWidth="3" strokeLinejoin="round" />
      <path d={happy ? "M25 89 L15 77 L13 68 M79 89 L85 80 L91 76" : sad ? "M25 89 L23 103 M79 89 L81 103" : focused ? "M25 88 L36 98 L47 95 M79 88 L68 98 L58 95" : "M25 89 L30 99 L41 96 M79 89 L74 99 L63 96"} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round" strokeLinejoin="round" />
      <path d={happy ? "M13 69 L12 64 M91 76 L95 73" : focused ? "M45 95 L49 94 M59 95 L55 94" : sad ? "M23 103 L23 106 M81 103 L81 106" : "M40 96 L44 95 M64 96 L60 95"} stroke={portrait.skin} strokeWidth="7" strokeLinecap="round" />
      <ellipse cx="29" cy="50" rx="5" ry="7" fill={portrait.skin} />
      <ellipse cx="75" cy="50" rx="5" ry="7" fill={portrait.skin} />
      <path d="M29 35 C29 18 75 18 75 35 L74 55 C73 70 61 77 52 77 C43 77 31 70 30 55 Z" fill={portrait.skin} />
      <path d={portrait.style} fill={portrait.hair} />
      <g fill="none" stroke="#302d32" strokeWidth="2" strokeLinecap="round">
        <path d={sad ? "M37 44 L44 41 M60 41 L67 44" : focused ? "M37 41 L44 43 M60 43 L67 41" : "M37 41 Q40 39 44 41 M60 41 Q64 39 67 41"} />
        {happy ? <path d="M38 49 Q41 44 44 49 M60 49 Q63 44 66 49" /> : <><path d="M41 48 L41 50 M63 48 L63 50" strokeWidth={focused ? 2.5 : 3} /><path d="M51 52 L50 57 L53 57" strokeOpacity=".3" /></>}
        <path d={sad ? "M45 67 Q52 61 59 67" : focused ? "M47 65 Q52 66 57 65" : happy ? "M43 62 Q52 74 61 62 Z" : "M46 64 Q52 70 58 64"} fill={happy ? "#fff1e2" : "none"} />
      </g>
      <g fill="#d9817b" opacity=".3"><ellipse cx="36" cy="58" rx="4" ry="2" /><ellipse cx="68" cy="58" rx="4" ry="2" /></g>
      {variant === 0 && <><path d="M27 28 Q30 12 53 13 Q75 14 77 28 Z" fill={color} /><path d="M26 28 L64 28" stroke={color} strokeWidth="6" strokeLinecap="round" /><path d="M35 80 L42 105 M69 80 L62 105" stroke="#665740" strokeWidth="4" /></>}
      {variant === 1 && <g stroke="#485465" fill="none" strokeWidth="2"><rect x="33" y="44" width="16" height="13" rx="5" /><rect x="55" y="44" width="16" height="13" rx="5" /><path d="M49 48 L55 48" /></g>}
      {variant === 2 && <><path d="M72 37 L77 31" stroke={color} strokeWidth="4" strokeLinecap="round" /><path d="M69 88 L69 100" stroke="#fff1e2" strokeWidth="3" strokeLinecap="round" /></>}
      {variant === 3 && <><path d="M32 82 L72 82 L76 106 L28 106 Z" fill="#293b3c" /><path d="M41 90 L63 90 L63 106 L41 106 Z" fill={color} /><circle cx="37" cy="87" r="2" fill={color} /><circle cx="67" cy="87" r="2" fill={color} /></>}
      {variant === 4 && <g fill="none" stroke={color} strokeWidth="4"><path d="M24 49 L24 36 C24 11 80 11 80 36 L80 49" /><rect x="21" y="43" width="7" height="16" rx="3" fill="#394447" /><rect x="76" y="43" width="7" height="16" rx="3" fill="#394447" /><path d="M79 57 Q79 65 63 65" /><path d="M63 65 L59 65" stroke="#e7ece8" /></g>}
      {variant === 5 && <g><path d="M37 78 L44 91 M67 78 L60 91" fill="none" stroke="#354758" strokeWidth="3" /><rect x="40" y="90" width="24" height="15" rx="4" fill="#354758" /><circle cx="52" cy="97" r="5" fill={color} /><circle cx="52" cy="97" r="2" fill="#354758" /></g>}
      {variant === 6 && <><path d="M69 86 L76 89 L75 97 L69 101 L63 97 L62 89 Z" fill="#3b4932" /><path d="M66 93 L69 96 L73 91" stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" /></>}
      {variant === 7 && <><circle cx="29" cy="58" r="3" fill={color} /><circle cx="75" cy="58" r="3" fill={color} /><path d="M31 80 L37 106 L48 92 L64 105 L73 80" fill="#40564b" /><path d="M46 91 L55 86 L63 91 L55 96 Z" fill={color} /></>}
      {focused && <g className="persona-tools"><rect x="32" y="96" width="40" height="13" rx="3" fill="#283336" /><path d="M39 101 L65 101 M44 105 L60 105" stroke={color} strokeWidth="1.5" strokeLinecap="round" /></g>}
    </g>
  </svg>;
}
