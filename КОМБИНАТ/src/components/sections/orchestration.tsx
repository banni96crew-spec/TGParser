import { FadeIn } from "@/components/motion/fade-in";

export function OrchestrationSection() {
  return (
    <section className="section" id="orchestration" aria-labelledby="orchestration-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="orchestration-title">How orchestration works</h2>
          <p>
            Declare roles, escalation paths, and evidence checkpoints once. During an incident,
            AegisOps keeps the active plan visible, records decisions, and surfaces the next
            accountable step—so coordination is structured instead of improvised.
          </p>
          <ol className="stack" style={{ marginTop: "var(--space-5)", maxWidth: "40rem" }}>
            <li>Detect and open a coordinated response room with named owners.</li>
            <li>Execute the workflow with timed checkpoints and clear status.</li>
            <li>Close with a controlled review trail—without fabricated outcome metrics.</li>
          </ol>
        </FadeIn>
      </div>
    </section>
  );
}
