import type { ReactNode } from "react";

export const go = (h: string) => { location.hash = h; };

// A consistent async indicator: a small spinner + a brief message, used at every background-run spot.
export const Spinner = () => <span className="spinner" aria-hidden="true" />;
export function Working({ text }: { text?: string }) {
  return <span className="working" role="status" aria-live="polite"><Spinner /><span>{text || "working…"}</span></span>;
}

// strip [[e:id]] markers for plain display (the new do-side screens don't resolve citations yet)
export function plain(s?: string): string {
  return String(s || "").replace(/\[\[e:[^\]]+\]\]/g, "").replace(/\s+([.,;:])/g, "$1").replace(/\s{2,}/g, " ").trim();
}

export const REG: Record<string, { c: string; l: string }> = {
  filed: { c: "var(--fact)", l: "Filed · fact" },
  stated: { c: "var(--intent)", l: "Stated · intent" },
  observed: { c: "var(--signal)", l: "Observed · signal" },
  coverage: { c: "var(--signal)", l: "Coverage · signal" },
};

export function Stepper({ stages, active, onNav }: { stages: [string, string, string][]; active: string; onNav: (id: string) => void }) {
  const idx = stages.findIndex((s) => s[0] === active);
  return (
    <div className="stepwrap"><div className="steps">
      {stages.map((s, i) => (
        <span key={s[0]} style={{ display: "contents" }}>
          <button className={`step${s[0] === active ? " on" : i < idx ? " done" : ""}`} onClick={() => onNav(s[0])}>
            <span className="num">{s[1]}</span>{s[2]}
          </button>
          {i < stages.length - 1 ? <span className="sep">›</span> : null}
        </span>
      ))}
    </div></div>
  );
}

export function PageHead({ title, sub }: { title: string; sub?: ReactNode }) {
  return <div className="pagehead"><h1>{title}</h1>{sub ? <p>{sub}</p> : null}</div>;
}

export const Loading = () => <div className="state">loading…</div>;
export const ErrState = ({ e }: { e: unknown }) => <div className="state">{(e as Error)?.message || "something went wrong"}</div>;
