/**
 * MontagePlayer — full-screen overlay that autoplays a Cloudinary memory montage
 * video when a `montage_ready` WebSocket event is received.
 *
 * Props:
 *   event   — the montage_ready event object (null = hidden)
 *   onClose — called when the user dismisses the player
 */

const styles = {
  overlay: {
    position: "fixed",
    inset: 0,
    zIndex: 1000,
    background: "rgba(0,0,0,0.88)",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 20,
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    width: "min(860px, 90vw)",
  },
  title: {
    flex: 1,
    fontSize: 18,
    fontWeight: 700,
    color: "#e8e8f0",
    letterSpacing: "-0.3px",
  },
  person: {
    color: "#60a5fa",
  },
  closeBtn: {
    background: "#1a1a24",
    border: "1px solid #2d2d3d",
    borderRadius: 8,
    color: "#9ca3af",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 600,
    padding: "6px 14px",
  },
  video: {
    width: "min(860px, 90vw)",
    borderRadius: 12,
    background: "#000",
    boxShadow: "0 0 60px rgba(0,0,0,0.8)",
    outline: "none",
  },
  caption: {
    width: "min(860px, 90vw)",
    fontSize: 13,
    color: "#6b7280",
    lineHeight: 1.5,
  },
  narration: {
    color: "#9ca3af",
    fontStyle: "italic",
    marginTop: 4,
  },
};

export default function MontagePlayer({ event, onClose }) {
  if (!event) return null;

  const { montage_url, person, narration } = event;

  return (
    <div style={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={styles.header}>
        <span style={styles.title}>
          Memory Montage
          {person && <span style={styles.person}> — {person}</span>}
        </span>
        <button style={styles.closeBtn} onClick={onClose}>
          Close
        </button>
      </div>

      {montage_url ? (
        <video
          key={montage_url}
          style={styles.video}
          src={montage_url}
          autoPlay
          controls
          playsInline
        />
      ) : (
        <div style={{ ...styles.video, padding: 40, textAlign: "center", color: "#6b7280" }}>
          Video unavailable
        </div>
      )}

      {narration && (
        <div style={styles.caption}>
          <p style={styles.narration}>"{narration}"</p>
        </div>
      )}
    </div>
  );
}
