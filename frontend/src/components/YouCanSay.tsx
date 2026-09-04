import type { SayAction } from "../present";

/** "You can say" bar — numbered pills that drive the real command/turn API. */
export function YouCanSay(props: {
  items: SayAction[];
  disabled: boolean;
  onAction: (item: SayAction) => void;
}) {
  const { items, disabled, onAction } = props;
  if (items.length === 0) return null;
  return (
    <section className="say" aria-label="You can say">
      <p className="say-label">YOU CAN SAY</p>
      <div className="say-items" role="group">
        {items.map((it, i) => (
          <button
            key={it.key}
            className={`say-btn${it.primary ? " say-primary" : ""}`}
            onClick={() => onAction(it)}
            disabled={disabled}
            aria-label={`${i + 1}: ${it.label}`}
          >
            <span className="say-num" aria-hidden="true">
              {i + 1}
            </span>
            {it.label}
          </button>
        ))}
      </div>
    </section>
  );
}
