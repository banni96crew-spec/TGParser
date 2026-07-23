import type { InputHTMLAttributes } from "react";

type Props = InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  error?: string;
};

export function TextField({ label, error, id, ...rest }: Props) {
  const fieldId = id ?? rest.name ?? "field";
  const errorId = `${fieldId}-error`;
  return (
    <div className="stack" style={{ gap: "0.35rem" }}>
      <label htmlFor={fieldId}>{label}</label>
      <input
        id={fieldId}
        className="input"
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={error ? errorId : undefined}
        {...rest}
      />
      {error ? (
        <p id={errorId} role="alert" style={{ color: "var(--color-danger)", margin: 0 }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
