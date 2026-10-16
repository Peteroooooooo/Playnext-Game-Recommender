// "同系列另有 N 款" as a disclosure: the button and the list it controls are placed by the caller,
// because on backup rows the list goes on its own line below the row.

export function SeriesButton({
  count,
  open,
  onToggle,
  controls,
  className,
  suffix = "",
}: {
  count: number;
  open: boolean;
  onToggle: () => void;
  controls: string;
  className: string;
  suffix?: string;
}) {
  return (
    <button type="button" className={className} aria-expanded={open} aria-controls={controls} onClick={onToggle}>
      同系列另有 {count} 款{suffix}
    </button>
  );
}

export function SeriesList({ id, names, count, open }: { id: string; names: string[]; count: number; open: boolean }) {
  const rest = count - names.length;
  return (
    <ul id={id} className="plain-list series-list" hidden={!open}>
      {names.map((n) => (
        <li key={n}>{n}</li>
      ))}
      {rest > 0 && <li className="muted">还有 {rest} 款没列出</li>}
    </ul>
  );
}
