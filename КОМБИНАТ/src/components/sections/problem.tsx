import { FadeIn } from "@/components/motion/fade-in";

export function ProblemSection() {
  return (
    <section className="section" id="problem" aria-labelledby="problem-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="problem-title">Incidents still live in scattered threads</h2>
          <p>
            When response lives across chat, tickets, and ad-hoc calls, ownership blurs, handoffs
            stall, and security review becomes an afterthought. AegisOps frames the work as an
            explicit orchestration path—not another noisy channel.
          </p>
        </FadeIn>
      </div>
    </section>
  );
}
