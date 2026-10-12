export function Pagination({ offset, total, onChange, label }: { offset: number; total: number; onChange: (offset: number) => void; label: string }) {
  const pages = Math.max(1, Math.floor(offset / 20) + 1, Math.ceil(total / 20));
  return <nav className="pagination" aria-label={`${label} pagination`}>
    <button className="filter-button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - 20))}>Previous</button>
    <span role="status">Page {Math.floor(offset / 20) + 1} of {pages} · {total} {label}</span>
    <button className="filter-button" disabled={offset + 20 >= total} onClick={() => onChange(offset + 20)}>Next</button>
  </nav>;
}
