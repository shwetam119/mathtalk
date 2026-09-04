/** Context memo card — real learner-memory summary derived in present.ts. */
export function ContextMemo(props: { title: string; body: string; note?: string }) {
  const { title, body, note } = props;
  return (
    <div className="memo">
      <p className="memo-title">{title}</p>
      <p className="memo-body">{body}</p>
      {note && <p className="memo-note">{note}</p>}
    </div>
  );
}
