import { FaqSection } from "@/components/sections/faq";
import { FinalCtaSection } from "@/components/sections/final-cta";
import { HeroSection } from "@/components/sections/hero";
import { IntegrationsSection } from "@/components/sections/integrations";
import { OrchestrationSection } from "@/components/sections/orchestration";
import { ProblemSection } from "@/components/sections/problem";
import { SecuritySection } from "@/components/sections/security";
import { UseCasesSection } from "@/components/sections/use-cases";
import { WorkflowSection } from "@/components/sections/workflow";

export default function HomePage() {
  return (
    <>
      <HeroSection />
      <main id="main">
        <ProblemSection />
        <OrchestrationSection />
        <WorkflowSection />
        <UseCasesSection />
        <SecuritySection />
        <IntegrationsSection />
        <FaqSection />
        <FinalCtaSection />
      </main>
      <footer className="container-page" style={{ paddingBlock: "var(--space-8)", color: "var(--color-muted)" }}>
        <p style={{ margin: 0, fontSize: "var(--text-small)" }}>
          AegisOps pilot landing — demonstrative content. No customer logos or unverified metrics.
        </p>
      </footer>
    </>
  );
}
