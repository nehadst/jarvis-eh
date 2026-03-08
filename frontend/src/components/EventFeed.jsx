const TYPE_CONFIG = {
  face_recognized: { label: "Face Recognized", color: "#818cf8", icon: "👤" },
  situation_grounding: { label: "Grounding", color: "#34d399", icon: "🏠" },
  activity_continuity: { label: "Activity Reminder", color: "#fbbf24", icon: "🔄" },
  wandering_detected: { label: "Wandering Alert", color: "#f87171", icon: "⚠️" },
  wandering_escalated: { label: "Wandering — Urgent", color: "#ef4444", icon: "🚨" },
  conversation_assist: { label: "Conversation Assist", color: "#a78bfa", icon: "💬" },
  encounter_recording_started: { label: "Recording", color: "#ef4444", icon: "🔴" },
  encounter_clip_ready: { label: "Clip Ready", color: "#10b981", icon: "🎥" },
};

const styles = {
  container: {
    overflowY: "auto",
    padding: 20,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  empty: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: "100%",
    color: "#4b5563",
    fontSize: 15,
  },
  card: (color, urgent) => ({
    background: urgent ? "#1a0a0a" : "#1a1a24",
    border: `1px solid ${color}${urgent ? "99" : "33"}`,
    borderLeft: `3px solid ${color}`,
    borderRadius: 10,
    padding: "12px 16px",
  }),
  row: { display: "flex", alignItems: "center", gap: 8, marginBottom: 6 },
  badge: (color) => ({
    fontSize: 12,
    fontWeight: 700,
    color,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
  }),
  time: { fontSize: 11, color: "#6b7280", marginLeft: "auto" },
  message: { fontSize: 14, lineHeight: 1.5, color: "#d1d5db" },
  detail: { fontSize: 12, color: "#6b7280", marginTop: 4 },
  playBtn: {
    display: "inline-block",
    marginTop: 8,
    padding: "4px 12px",
    background: "#1d4ed8",
    color: "#bfdbfe",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 600,
  },
};

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function EventCard({ event, onPlayClip }) {
  const cfg = TYPE_CONFIG[event.type] || { label: event.type, color: "#9ca3af", icon: "•" };
  const message = event.whisper || event.message || "";
  const isUrgent = event.type === "wandering_escalated";

  return (
    <div style={styles.card(cfg.color, isUrgent)}>
      <div style={styles.row}>
        <span>{cfg.icon}</span>
        <span style={styles.badge(cfg.color)}>{cfg.label}</span>
        {event.person && <span style={{ fontSize: 13, color: "#e2e8f0", fontWeight: 600 }}>— {event.person}</span>}
        <span style={styles.time}>{formatTime(event.timestamp)}</span>
      </div>
      {message && <p style={styles.message}>"{message}"</p>}
      {event.scene && <p style={styles.detail}>Scene: {event.scene}</p>}
      {event.last_safe_scene && (
        <p style={styles.detail}>Last safe location: {event.last_safe_scene}</p>
      )}
      {event.alert_count > 1 && (
        <p style={{ ...styles.detail, color: "#f87171" }}>
          Alert #{event.alert_count} in this episode
        </p>
      )}
      {event.activity && <p style={styles.detail}>Activity: {event.activity}</p>}
      {event.confidence && <p style={styles.detail}>Confidence: {(event.confidence * 100).toFixed(1)}%</p>}
      {event.type === "encounter_clip_ready" && event.clip_url && (
        <>
          <button style={styles.playBtn} onClick={() => onPlayClip?.(event)}>
            Play Clip
          </button>
          {event.snapshots?.length > 0 && (
            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
              {event.snapshots.map((url, i) => (
                <img
                  key={i}
                  src={url}
                  alt={`Snapshot ${i + 1}`}
                  style={{ width: 80, height: 60, objectFit: "cover", borderRadius: 6, border: "1px solid #2d2d3d" }}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function EventFeed({ events, onPlayClip }) {
  if (!events.length) {
    return <div style={styles.empty}>No events yet. Start capture to begin.</div>;
  }
  return (
    <div style={styles.container}>
      {events.map((e, i) => (
        <EventCard key={i} event={e} onPlayClip={onPlayClip} />
      ))}
    </div>
  );
}
