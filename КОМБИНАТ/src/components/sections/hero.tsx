"use client";

import { FadeIn } from "@/components/motion/fade-in";

export function HeroSection() {
  return (
    <header className="container-page" style={{ paddingBlock: "var(--space-12) var(--space-10)" }}>
      <FadeIn>
        <p
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "var(--text-small)",
            color: "var(--color-muted)",
            letterSpacing: "0.04em",
            textTransform: "uppercase",
            marginBottom: "var(--space-4)",
          }}
        >
          AegisOps
        </p>
        <h1
          style={{
            fontSize: "var(--text-display)",
            lineHeight: "var(--leading-tight)",
            maxWidth: "14ch",
            margin: "0 0 var(--space-5)",
          }}
        >
          Coordinate incident response without the chat scramble.
        </h1>
        <p style={{ color: "var(--color-muted)", maxWidth: "36rem", marginBottom: "var(--space-6)" }}>
          A technical orchestration layer for VP Engineering, security leads, and SRE teams who need
          clear ownership, controlled access, and workflows that fit the existing stack.
        </p>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-3)" }}>
          <a className="btn" href="#final-cta">
            Book a technical demo
          </a>
          <a className="btn btn-secondary" href="#workflow">
            See how response workflows work
          </a>
        </div>
      </FadeIn>
    </header>
  );
}
