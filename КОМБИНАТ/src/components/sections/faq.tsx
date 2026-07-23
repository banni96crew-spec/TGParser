import { FadeIn } from "@/components/motion/fade-in";

const faqs = [
  {
    q: "How long does implementation take?",
    a: "The demo walks a focused orchestration path first. Rollout scope is agreed in the technical session—not promised as a one-click install.",
  },
  {
    q: "Where does data live?",
    a: "Control boundaries and exportability are part of the security discussion in the demo. This page does not invent hosting claims.",
  },
  {
    q: "Do we need to replace our stack?",
    a: "No. The integration model is category-based so existing chat, paging, and ticketing can remain sources of truth.",
  },
  {
    q: "Is this an AI autopilot?",
    a: "No. AegisOps emphasizes human-owned workflows and explicit checkpoints—especially where distrust of AI is a barrier.",
  },
];

export function FaqSection() {
  return (
    <section className="section" id="faq" aria-labelledby="faq-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="faq-title">FAQ</h2>
          <div className="stack" style={{ marginTop: "var(--space-5)", maxWidth: "42rem" }}>
            {faqs.map((item) => (
              <details
                key={item.q}
                style={{ borderTop: "1px solid var(--color-border)", paddingBlock: "var(--space-3)" }}
              >
                <summary style={{ cursor: "pointer", fontWeight: 600 }}>{item.q}</summary>
                <p style={{ marginTop: "var(--space-2)" }}>{item.a}</p>
              </details>
            ))}
          </div>
        </FadeIn>
      </div>
    </section>
  );
}
