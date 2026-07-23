import { FadeIn } from "@/components/motion/fade-in";

const steps = [
  "Triage and severity alignment",
  "Role assignment and paging",
  "Mitigation actions with owners",
  "Stakeholder updates on a cadence",
  "Resolution and controlled closeout",
];

export function WorkflowSection() {
  return (
    <section className="section" id="workflow" aria-labelledby="workflow-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="workflow-title">Incident workflow</h2>
          <p>
            A linear path you can audit. Secondary CTA from the hero lands here so teams can inspect
            the mechanism before booking time.
          </p>
          <ol className="stack" style={{ marginTop: "var(--space-5)", maxWidth: "36rem" }}>
            {steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </FadeIn>
      </div>
    </section>
  );
}
