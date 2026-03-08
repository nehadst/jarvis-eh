/**
 * MontagePlayer — full-screen overlay that autoplays an encounter recording
 * clip or memory montage when triggered.
 *
 * Props:
 *   event   — the encounter_clip_ready or montage_ready event object (null = hidden)
 *   onClose — called when the user dismisses the player
 */

export default function MontagePlayer({ event, onClose }) {
  if (!event) return null;

  const videoUrl = event.clip_url || event.montage_url;
  const { person, snapshots, duration_seconds, frame_count, narration } = event;
  const title = event.type === "montage_ready" ? "Memory Montage" : "Encounter Recording";

  return (
    <div
      className="fixed inset-0 z-[1000] flex flex-col items-center justify-center gap-5"
      style={{ background: "rgba(0,0,0,0.88)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      {/* Header */}
      <div className="flex items-center gap-3" style={{ width: "min(860px, 90vw)" }}>
        <span className="flex-1 text-[18px] font-bold tracking-tight text-foreground">
          {title}
          {person && <span style={{ color: "var(--primary)" }}> — {person}</span>}
        </span>
        <button
          className="px-3.5 py-1.5 text-[13px] font-semibold cursor-pointer border transition-opacity hover:opacity-80"
          style={{ background: "var(--card)", border: "1px solid var(--border)", color: "var(--muted-foreground)" }}
          onClick={onClose}
        >
          Close
        </button>
      </div>

      {videoUrl ? (
        <video
          key={videoUrl}
          className="bg-black outline-none"
          style={{ width: "min(860px, 90vw)", boxShadow: "0 0 60px rgba(0,0,0,0.8)" }}
          src={videoUrl}
          autoPlay
          controls
          playsInline
        />
      ) : (
        <div
          className="bg-black flex items-center justify-center text-[14px] text-muted-foreground"
          style={{ width: "min(860px, 90vw)", padding: 40 }}
        >
          Video unavailable
        </div>
      )}

      {/* Snapshots (encounter clips) */}
      {snapshots?.length > 0 && (
        <div className="flex gap-3 justify-center" style={{ width: "min(860px, 90vw)" }}>
          {snapshots.map((url, i) => (
            <img
              key={i}
              src={url}
              alt={`Snapshot ${i + 1}`}
              style={{ width: 200, height: 150, objectFit: "cover", border: "2px solid var(--border)" }}
            />
          ))}
        </div>
      )}

      {/* Narration (montages) */}
      {narration && (
        <div className="text-[13px] leading-relaxed" style={{ width: "min(860px, 90vw)" }}>
          <p className="text-muted-foreground italic">"{narration}"</p>
        </div>
      )}

      {/* Duration info */}
      {(duration_seconds || frame_count) && (
        <div className="text-[13px] text-muted-foreground text-center" style={{ width: "min(860px, 90vw)" }}>
          {duration_seconds && <span>{duration_seconds}s</span>}
          {duration_seconds && frame_count && <span> · </span>}
          {frame_count && <span>{frame_count} frames</span>}
        </div>
      )}
    </div>
  );
}
