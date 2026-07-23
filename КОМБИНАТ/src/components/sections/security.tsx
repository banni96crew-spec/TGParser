import { FadeIn } from "@/components/motion/fade-in";

const controls = [
  "Role-scoped actions during response",
  "Explicit approval checkpoints for sensitive steps",
  "Exportable decision trail for internal review",
  "No AI black-box claims in this pilot narrative",
];

export function SecuritySection() {
  return (
    <section className="section" id="security" aria-labelledby="security-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="security-title">Security and control</h2>
          <p>
            Trust is a conversion barrier. Before the final ask, AegisOps states the control model in
            plain language—without invented certifications, logos, or percentages.
          </p>
          <ul className="stack" style={{ marginTop: "var(--space-5)", maxWidth: "40rem" }}>
            {controls.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </FadeIn>
      </div>
    </section>
  );
}
