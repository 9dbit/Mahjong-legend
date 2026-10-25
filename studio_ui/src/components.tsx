import {
  Children,
  cloneElement,
  isValidElement,
  useId,
  type HTMLAttributes,
  type ReactNode,
} from "react";

const icons: Record<string, string> = {
  overview: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
  betting: "M4 7h16v13H4z M4 11h16 M16 15h1 M7 7V4h10v3",
  rules: "M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h3 M14 15h2",
  tiles: "M4 3h10v15H4z M10 6h10v15H10 M7 7h4 M7 11h4",
  scene: "M3 4h18v16H3z M3 15l5-5 4 4 4-6 5 8 M7 8h.01",
  audio: "M3 10v4 M7 6v12 M11 3v18 M15 7v10 M19 5v14 M23 10v4",
  math: "M5 3v18h16 M8 16l4-7 4 4 5-9",
  preview: "M3 4h18v13H3z M8 21h8 M12 17v4 M10 8l5 3-5 3z",
  releases: "M12 3v12 M8 11l4 4 4-4 M4 15v6h16v-6",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2",
  plus: "M12 5v14 M5 12h14",
  play: "M8 4l12 8-12 8z",
  pause: "M8 4v16 M16 4v16",
  stop: "M5 5h14v14H5z",
  check: "M4 12l5 5L20 5",
  chevron: "M9 5l7 7-7 7",
  logout: "M10 4H4v16h6 M8 12h13 M16 7l5 5-5 5",
  refresh: "M20 7a8 8 0 1 0 1 9 M20 2v5h-5",
  upload: "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6",
  link: "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2 M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
  menu: "M4 6h16 M4 12h16 M4 18h16",
  close: "M6 6l12 12 M18 6L6 18",
  shield: "M12 2l9 4v6c0 5-9 10-9 10S3 17 3 12V6z",
  undo: "M9 4L3 10l6 6 M3 10h11a6 6 0 0 1 6 6",
  redo: "M15 4l6 6-6 6 M21 10H10a6 6 0 0 0-6 6",
};
export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.65"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={icons[name] || icons.settings} />
    </svg>
  );
}
export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={"badge " + tone}>{children}</span>;
}
export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <label className={"field " + className}>
      <span>{label}</span>
      {Children.map(children, (child) =>
        isValidElement<HTMLAttributes<HTMLElement>>(child)
          ? cloneElement(child, {
              "aria-label": child.props["aria-label"] || label,
              "aria-describedby": hint ? id : undefined,
            })
          : child,
      )}
      {hint && <small id={id}>{hint}</small>}
    </label>
  );
}
export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = "any",
  hint,
  disabled,
}: {
  label: string;
  value: number | string;
  onChange: (n: number) => void;
  min?: number;
  max?: number;
  step?: number | "any";
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        type="number"
        inputMode="decimal"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) =>
          onChange(e.target.value === "" ? NaN : Number(e.target.value))
        }
      />
    </Field>
  );
}
export function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className="toggle-row">
      <span>
        <strong>{label}</strong>
        {hint && <small>{hint}</small>}
      </span>
      <input
        role="switch"
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
    </label>
  );
}
export function Section({
  title,
  eyebrow,
  description,
  actions,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={"panel " + className}>
      <div className="panel-head">
        <div>
          {eyebrow && <p className="eyebrow">{eyebrow}</p>}
          <h2>{title}</h2>
          {description && <p className="muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}
export function Empty({
  title,
  children,
  icon = "tiles",
}: {
  title: string;
  children?: ReactNode;
  icon?: string;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} size={28} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function Notice({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <div className={"notice " + tone}>{children}</div>;
}
export function Metric({
  label,
  value,
  detail,
  tone = "",
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: string;
}) {
  return (
    <div className={"metric " + tone}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}
