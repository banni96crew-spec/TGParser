import { FadeIn } from "@/components/motion/fade-in";

export function IntegrationsSection() {
  return (
    <section className="section" id="integrations" aria-labelledby="integrations-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="integrations-title">Integration model</h2>
          <p>
            Connect chat, paging, ticketing, and observability categories you already run. This pilot
            lists categories only—no unverified partner logos.
          </p>
          <ul
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(10rem, 1fr))",
              gap: "var(--space-3)",
              marginTop: "var(--space-5)",
              padding: 0,
              listStyle: "none",
            }}
          >
            {["Chat", "Paging", "Ticketing", "Observability", "Identity", "Docs"].map((label) => (
              <li
                key={label}
                style={{
                  border: "1px solid var(--color-border)",
                  padding: "var(--space-3)",
                  borderRadius: "var(--radius-sm)",
                }}
              >
                {label}
              </li>
            ))}
          </ul>
        </FadeIn>
      </div>
    </section>
  );
}
