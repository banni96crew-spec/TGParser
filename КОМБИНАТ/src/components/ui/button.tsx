import type { ButtonHTMLAttributes, ReactNode } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary";
  children: ReactNode;
};

export function Button({
  variant = "primary",
  className = "",
  children,
  ...rest
}: Props) {
  const base = variant === "secondary" ? "btn btn-secondary" : "btn";
  return (
    <button className={`${base} ${className}`.trim()} {...rest}>
      {children}
    </button>
  );
}
