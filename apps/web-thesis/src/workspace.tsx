import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { Stepper, go, Loading, ErrState } from "./ui";
import { Genesis } from "./genesis";
import { Plan, Run } from "./plan";
import { Brief, ReadPanel, ReasoningPanel, CompetitivePanel, DeckPanel, LinesPanel } from "./brief";
import { Brainstorm } from "./brainstorm";
import { Experts } from "./experts";
import { Share } from "./share";

const STAGES: [string, string, string][] = [
  ["plan", "1", "Plan"], ["run", "2", "Run & Lines"], ["brief", "3", "Brief"],
  ["reason", "4", "Reasoning Map"], ["competitive", "5", "Competitive"], ["deck", "6", "Pitch Deck"],
  ["brainstorm", "7", "Brainstorm"], ["experts", "8", "Experts"], ["share", "9", "Share"],
];

function TopBar({ crumb }: { crumb?: ReactNode }) {
  return (
    <div className="top"><div className="top-in">
      <span className="mark" onClick={() => go("")}>EIG<b>E</b>N</span>
      {crumb ? <span className="crumb">{crumb}</span> : null}
      <span className="grow" />
    </div></div>
  );
}

export function Workspace({ id, token }: { id: string; token?: string }) {
  const qc = useQueryClient();
  const tq = useQuery({ queryKey: ["thesis", id, token || ""], queryFn: () => api.thesis(id, token || undefined) });
  const doc = tq.data;
  const isDraft = !!doc && !(doc.claims || []).length;
  const iq = useQuery({ queryKey: ["inq", id, token || ""], queryFn: () => api.inquiries(id, token || undefined), enabled: !!doc && !isDraft });
  const tested = doc?.research_status === "completed" || (iq.data?.inquiries || []).some((i) => (i.questions || []).some((q) => q.target_status));
  const [stage, setStage] = useState<string>("");
  const active = stage || (tested ? "brief" : "plan");

  const reloadInq = () => qc.invalidateQueries({ queryKey: ["inq", id] });
  const reloadDoc = () => { qc.invalidateQueries({ queryKey: ["thesis", id] }); reloadInq(); };

  if (tq.isLoading) return (<><TopBar /><div className="wrap"><Loading /></div></>);
  if (tq.error || !doc) return (<><TopBar /><div className="wrap"><ErrState e={tq.error} /></div></>);

  if (isDraft) return (<><TopBar crumb="New thesis · genesis" /><div className="wrap"><Genesis id={id} doc={doc} onCommitted={reloadDoc} /></div></>);

  if (!doc.is_owner) {
    return (<><TopBar crumb="Shared · read-only" /><div className="wrap"><Brief doc={doc} inq={iq.data || {}} anonymous /></div></>);
  }

  const inqs = iq.data?.inquiries;
  const take = iq.data?.take || doc.collective_take;
  const panel = { doc, inq: iq.data || {}, id, owner: doc.is_owner, onRefetchInq: reloadDoc };
  return (
    <>
      <TopBar crumb={<><span style={{ cursor: "pointer" }} onClick={() => go("")}>My theses</span> · <b>{(doc.thesis || "").slice(0, 40)}…</b></>} />
      <Stepper stages={STAGES} active={active} onNav={setStage} />
      <div className="wrap">
        {active === "plan" ? <Plan id={id} inquiries={inqs} onReload={reloadInq} onRun={() => setStage("run")} />
          : active === "run" ? (<><Run id={id} onDone={reloadDoc} />{tested ? <LinesPanel {...panel} /> : null}</>)
            : active === "brief" ? <ReadPanel {...panel} />
              : active === "reason" ? <ReasoningPanel {...panel} />
                : active === "competitive" ? <CompetitivePanel {...panel} />
                  : active === "deck" ? <DeckPanel {...panel} />
                    : active === "brainstorm" ? <Brainstorm id={id} take={take} onExperts={() => setStage("experts")} />
                      : active === "experts" ? <Experts id={id} inquiries={inqs} />
                        : <Share id={id} doc={doc} onChanged={reloadDoc} />}
      </div>
    </>
  );
}
