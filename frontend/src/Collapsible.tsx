import { useId, useState, type ReactNode } from "react";

export function Collapsible({ title, children }: { title: string; children: ReactNode }) {
  const [expanded, setExpanded] = useState(true);
  const id = useId();
  return <div className="settings-group">
    <h2><button type="button" className="collapse-button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(!expanded)}>{title}<span aria-hidden="true">{expanded ? "−" : "+"}</span></button></h2>
    <div id={id} hidden={!expanded}>{children}</div>
  </div>;
}
