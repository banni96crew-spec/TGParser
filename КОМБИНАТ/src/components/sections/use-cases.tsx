import { FadeIn } from "@/components/motion/fade-in";

const cases = [
  {
    title: "VP Engineering",
    body: "Keep cross-team incidents on one accountable plan without adding another status meeting.",
  },
  {
    title: "Head of Security",
    body: "Require explicit access boundaries and review checkpoints before sensitive actions proceed.",
  },
  {
    title: "SRE Lead",
    body: "Plug orchestration into the tools you already page from and write postmortems in.",
  },
];

export function UseCasesSection() {
  return (
    <section className="section" id="use-cases" aria-labelledby="use-cases-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="use-cases-title">Use cases</h2>
          <div
            style={{
              marginTop: "var(--space-5)",
              display: "grid",
              gap: "var(--space-5)",
              gridTemplateColumns: "repeat(auto-fit, minmax(16rem, 1fr))",
            }}
          >
            {cases.map((item) => (
              <article
                key={item.title}
                style={{ borderTop: "1px solid var(--color-border)", paddingTop: "var(--space-4)" }}
              >
                <h3 style={{ margin: "0 0 var(--space-2)", fontSize: "1.125rem" }}>{item.title}</h3>
                <p style={{ margin: 0 }}>{item.body}</p>
              </article>
            ))}
          </div>
        </FadeIn>
      </div>
    </section>
  );
}
