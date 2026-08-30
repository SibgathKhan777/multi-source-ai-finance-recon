import Link from "next/link";

export default function TopNav({ active }: { active: "problem" | "solution" }) {
  return (
    <div className="sticky top-0 z-30 border-b border-black/10 bg-white/85 backdrop-blur dark:border-white/10 dark:bg-black/60">
      <nav className="mx-auto flex h-12 max-w-5xl items-center justify-between px-5 text-sm">
        <Link href="/" className="font-semibold tracking-tight text-slate-900 dark:text-slate-100">
          Reconciliation
        </Link>
        <div className="flex items-center gap-5">
          <Link
            href="/"
            className={
              active === "problem"
                ? "font-medium text-slate-900 underline decoration-2 underline-offset-8 dark:text-slate-100"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            }
          >
            The problem
          </Link>
          <Link
            href="/solution"
            className={
              active === "solution"
                ? "font-medium text-slate-900 underline decoration-2 underline-offset-8 dark:text-slate-100"
                : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            }
          >
            The solution
          </Link>
        </div>
      </nav>
    </div>
  );
}
