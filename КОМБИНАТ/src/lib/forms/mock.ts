export type DemoRequest = {
  name: string;
  email: string;
  company: string;
};

export type DemoResult =
  | { ok: true; message: string }
  | {
      ok: false;
      message: string;
      fieldErrors?: Partial<Record<keyof DemoRequest, string>>;
    };

/** Pilot mock adapter — no real backend. */
export async function submitDemoRequest(input: DemoRequest): Promise<DemoResult> {
  await new Promise((r) => setTimeout(r, 400));
  const fieldErrors: Partial<Record<keyof DemoRequest, string>> = {};
  if (!input.name.trim()) fieldErrors.name = "Name is required.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.email)) {
    fieldErrors.email = "Enter a valid work email.";
  }
  if (!input.company.trim()) fieldErrors.company = "Company is required.";
  if (Object.keys(fieldErrors).length > 0) {
    return { ok: false, message: "Please fix the highlighted fields.", fieldErrors };
  }
  if (input.email.toLowerCase().includes("fail@")) {
    return { ok: false, message: "Mock backend error. Try again." };
  }
  return {
    ok: true,
    message: "Demo request received (mock). We will not send email in this pilot.",
  };
}
