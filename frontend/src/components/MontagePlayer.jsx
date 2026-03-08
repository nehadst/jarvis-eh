/**
 * MontagePlayer — full-screen overlay that autoplays an encounter recording
 * clip when an `encounter_clip_ready` WebSocket event is received.
 *
 * Props:
 *   event   — the encounter_clip_ready event object (null = hidden)
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
  snapshots: {
    display: "flex",
    gap: 12,
    width: "min(860px, 90vw)",
    justifyContent: "center",
  },
  snapshot: {
    width: 200,
    height: 150,
    objectFit: "cover",
    borderRadius: 8,
    border: "2px solid #2d2d3d",
  },
  caption: {
    width: "min(860px, 90vw)",
    fontSize: 13,
    color: "#6b7280",
    lineHeight: 1.5,
    textAlign: "center",
  },
};

export default function MontagePlayer({ event, onClose }) {
  if (!event) return null;

  const { clip_url, person, snapshots, duration_seconds, frame_count } = event;

  return (
    <div style={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={styles.header}>
        <span style={styles.title}>
          Encounter Recording
          {person && <span style={styles.person}> — {person}</span>}
        </span>
        <button style={styles.closeBtn} onClick={onClose}>
          Close
        </button>
      </div>

      {clip_url ? (
        <video
          key={clip_url}
          style={styles.video}
          src={clip_url}
          autoPlay
          controls
          playsInline
        />
      ) : (
        <div style={{ ...styles.video, padding: 40, textAlign: "center", color: "#6b7280" }}>
          Video unavailable
        </div>
      )}

      {snapshots?.length > 0 && (
        <div style={styles.snapshots}>
          {snapshots.map((url, i) => (
            <img
              key={i}
              src={url}
              alt={`Snapshot ${i + 1}`}
              style={styles.snapshot}
            />
          ))}
        </div>
      )}

      {(duration_seconds || frame_count) && (
        <div style={styles.caption}>
          {duration_seconds && <span>{duration_seconds}s</span>}
          {duration_seconds && frame_count && <span> · </span>}
          {frame_count && <span>{frame_count} frames</span>}
        </div>
      )}
    </div>
  );
}
