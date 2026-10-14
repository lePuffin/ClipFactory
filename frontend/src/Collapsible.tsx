import { useId, useState, type ReactNode } from "react";

type CollapsibleProps = {
  title: string;
  children: ReactNode;
  /** Settings groups start collapsed (CF-REQ-606); callers may opt into an expanded start. */
  defaultExpanded?: boolean;
  /** Heading level for the toggle; nested groups use a lower level than page sections. */
  level?: 2 | 3;
  className?: string;
};

/**
 * Accessible disclosure: a native button with aria-expanded/aria-controls.
 * Collapsed content is hidden, never unmounted, so unsaved drafts survive toggling.
 */
export function Collapsible({ title, children, defaultExpanded = false, level = 2, className = "settings-group" }: CollapsibleProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const id = useId();
  const Heading = level === 2 ? "h2" : "h3";
  return <div className={className}>
    <Heading><button type="button" className="collapse-button" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(!expanded)}>{title}<span aria-hidden="true">{expanded ? "−" : "+"}</span></button></Heading>
    <div id={id} hidden={!expanded}>{children}</div>
  </div>;
}
