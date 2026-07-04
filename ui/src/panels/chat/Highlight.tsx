// Split `text` on every case-insensitive occurrence of `term` and wrap the
// matches in <mark>, so a search result shows WHY it matched. An empty term (or
// no match) returns the text untouched. Regex specials in the term are escaped
// so a user typing "a.b" matches the literal string, never a wildcard.

interface HighlightProps {
  text: string;
  term: string;
}

export function Highlight({ text, term }: HighlightProps): JSX.Element {
  const needle = term.trim();
  if (!needle) return <>{text}</>;
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "ig"));
  const lower = needle.toLowerCase();

  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === lower ? (
          <mark key={i} className="conv-item__hl">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export { type HighlightProps };
