import { Crown, Landmark, ScrollText } from "lucide-react";
import { FullscreenModal } from "./hud";
import { MechanicalTailFailure } from "./mechanicalTailFailure";
import type { EndingPayload } from "../types";

export function EndingModal({ ending, failure, onClose, onRetry }: { ending: EndingPayload; failure?: { error?: string; error_pack_path?: string } | null; onClose: () => void; onRetry?: () => void }) {
  const lastTimeline = ending.timeline?.[ending.timeline.length - 1];
  const endingDate = lastTimeline ? `${lastTimeline.year}年${lastTimeline.period}月` : "终局";
  const timelineCount = ending.timeline?.length ?? 0;
  // #1845：机械尾失败时空总评不得用「（无总评）」冒充已完成；pending / 失败均留空，仅真无总评时才显示占位。
  const summaryText = ending.summary
    || (ending.summary_pending || failure ? "" : "（无总评）");

  return (
    <FullscreenModal
      title="终章定论"
      subtitle="崇祯一朝，盖棺论定"
      bgClass="modal-bg-state modal-bg-ending"
      onClose={onClose}
    >
      <article className="state-document ending-document modal-scroll">
        <div className="ending-hero">
          <div className="ending-seal" aria-hidden="true">
            <Crown size={34} />
          </div>
          <div className="ending-hero-copy">
            <p>大明国史馆录</p>
            <h2>{ending.label}</h2>
            <span>{endingDate} · 第 {timelineCount || 1} 卷</span>
          </div>
        </div>

        <section className="ending-verdict-card" aria-label="结局总评">
          <div className="ending-section-kicker">
            <ScrollText size={17} />
            <span>国史编纂官总评</span>
          </div>
          {onRetry && <MechanicalTailFailure failure={failure} onRetry={onRetry} />}
          <pre
            className="ending-summary-text"
            aria-busy={ending.summary_pending ? true : undefined}
          >{summaryText}</pre>
        </section>

        {ending.timeline && ending.timeline.length > 0 && (
          <section className="ending-chronicle" aria-label="逐月历程">
            <div className="ending-section-kicker">
              <Landmark size={17} />
              <span>崇祯一朝逐月历程</span>
            </div>
            <ol className="ending-timeline">
              {ending.timeline.map((it) => (
                <li key={it.turn} className="ending-timeline-item">
                  <div className="ending-timeline-date">
                    <b>{it.year}</b>
                    <span>{it.period}月</span>
                  </div>
                  <div className="ending-timeline-body">
                    {it.gazette ? (
                      <p className="ending-timeline-chapter">{it.gazette}</p>
                    ) : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
      </article>
    </FullscreenModal>
  );
}

