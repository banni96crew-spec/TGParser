import Link from "next/link";

export default function NotFound() {
  return (
    <main className="container-page section" id="main">
      <h1>Page not found</h1>
      <p>The requested route is not part of the AegisOps pilot landing page.</p>
      <p>
        <Link className="btn" href="/">
          Back to home
        </Link>
      </p>
    </main>
  );
}
