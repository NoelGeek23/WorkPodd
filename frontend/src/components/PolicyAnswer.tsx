type Props = {
  citations: Array<Record<string, unknown>>;
};

export default function PolicyAnswer({ citations }: Props) {
  if (citations.length === 0) {
    return null;
  }

  return (
    <details className="policy-citations">
      <summary>Policy sections used</summary>
      {citations.map((citation) => (
        <article key={String(citation.chunk_id)} className="policy-citation">
          <strong>{String(citation.section_title ?? "Policy section")}</strong>
          <p>{String(citation.content ?? "").slice(0, 260)}...</p>
        </article>
      ))}
    </details>
  );
}
