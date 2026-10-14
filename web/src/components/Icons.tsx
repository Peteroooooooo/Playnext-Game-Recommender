export function XIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function ArrowIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 8h9.5M8.5 4L12.5 8l-4 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ExtIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M4.5 2.5h5v5M9.5 2.5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg width="11" height="11" viewBox="0 0 10 10" aria-hidden="true">
      <path d="M2 5.2l2 2L8 3" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="var(--accent)" />
      <path d="M8 8.5v11l7-5.5z" fill="var(--accent-ink)" />
      <path d="M15 8.5v11l7-5.5z" fill="var(--accent-ink)" opacity=".5" />
    </svg>
  );
}

/** Member avatar: first character on the member colour. */
export function Avatar({ name, index, small }: { name: string; index: number; small?: boolean }) {
  return (
    <span className={`av${small ? " sm" : ""}`} style={{ ["--h" as string]: `var(--m${(index % 6) + 1})` }} aria-hidden="true">
      {Array.from(name.trim() || "?")[0]}
    </span>
  );
}
