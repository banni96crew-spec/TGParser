"use client";

import { FormEvent, useState } from "react";
import { FadeIn } from "@/components/motion/fade-in";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { submitDemoRequest, type DemoRequest } from "@/lib/forms/mock";

export function FinalCtaSection() {
  const [values, setValues] = useState<DemoRequest>({ name: "", email: "", company: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof DemoRequest, string>>>({});
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("loading");
    setMessage("");
    setErrors({});
    const result = await submitDemoRequest(values);
    if (result.ok) {
      setStatus("success");
      setMessage(result.message);
      setValues({ name: "", email: "", company: "" });
      return;
    }
    setStatus("error");
    setMessage(result.message);
    setErrors(result.fieldErrors ?? {});
  }

  return (
    <section className="section" id="final-cta" aria-labelledby="final-cta-title">
      <div className="container-page">
        <FadeIn>
          <h2 id="final-cta-title">Book a technical demo</h2>
          <p>
            Thirty minutes with your incident workflow in mind. This pilot form uses a mock adapter—no
            messages are sent.
          </p>
          <form
            className="stack"
            style={{ marginTop: "var(--space-5)", maxWidth: "28rem" }}
            onSubmit={onSubmit}
            noValidate
          >
            <TextField
              label="Name"
              name="name"
              autoComplete="name"
              value={values.name}
              error={errors.name}
              disabled={status === "loading"}
              onChange={(e) => setValues((v) => ({ ...v, name: e.target.value }))}
            />
            <TextField
              label="Work email"
              name="email"
              type="email"
              autoComplete="email"
              value={values.email}
              error={errors.email}
              disabled={status === "loading"}
              onChange={(e) => setValues((v) => ({ ...v, email: e.target.value }))}
            />
            <TextField
              label="Company"
              name="company"
              autoComplete="organization"
              value={values.company}
              error={errors.company}
              disabled={status === "loading"}
              onChange={(e) => setValues((v) => ({ ...v, company: e.target.value }))}
            />
            <Button type="submit" disabled={status === "loading"}>
              {status === "loading" ? "Submitting…" : "Book a technical demo"}
            </Button>
            {message ? (
              <p
                role="status"
                style={{
                  margin: 0,
                  color: status === "success" ? "var(--color-success)" : "var(--color-danger)",
                }}
              >
                {message}
              </p>
            ) : null}
          </form>
        </FadeIn>
      </div>
    </section>
  );
}
