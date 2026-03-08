/**
 * MontagePlayer — full-screen overlay that autoplays a Cloudinary memory montage
 * video when a `montage_ready` WebSocket event is received.
 *
 * Props:
 *   event   — the montage_ready event object (null = hidden)
 *   onClose — called when the user dismisses the player
 */

export default function MontagePlayer({ event, onClose }) {
  if (!event) return null;

  const { montage_url, person, narration } = event;

  return (
    <div
      className="fixed inset-0 z-[1000] flex flex-col items-center justify-center gap-5"
      style={{ background: "rgba(0,0,0,0.88)" }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      {/* Header */}
      <div className="flex items-center gap-3" style={{ width: "min(860px, 90vw)" }}>
        <span className="flex-1 text-[18px] font-bold tracking-tight text-foreground">
          Memory Montage
          {person && <span style={{ color: "#60a5fa" }}> — {person}</span>}
        </span>
        <button
          className="px-3.5 py-1.5 rounded-lg text-[13px] font-semibold cursor-pointer border transition-opacity hover:opacity-80"
          style={{ background: "var(--card)", border: "1px solid var(--border)", color: "var(--muted-foreground)" }}
          onClick={onClose}
        >
          Close
        </button>
      </div>

      {montage_url ? (
        <video
          key={montage_url}
          className="rounded-xl bg-black outline-none"
          style={{ width: "min(860px, 90vw)", boxShadow: "0 0 60px rgba(0,0,0,0.8)" }}
          src={montage_url}
          autoPlay
          controls
          playsInline
        />
      ) : (
        <div
          className="rounded-xl bg-black flex items-center justify-center text-[14px] text-muted-foreground"
          style={{ width: "min(860px, 90vw)", padding: 40 }}
        >
          Video unavailable
        </div>
      )}

      {narration && (
        <div className="text-[13px] leading-relaxed" style={{ width: "min(860px, 90vw)" }}>
          <p className="text-muted-foreground italic">"{narration}"</p>
        </div>
      )}
    </div>
  );
}
