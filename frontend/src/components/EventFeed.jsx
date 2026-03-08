const TYPE_CONFIG = {
  face_recognized:    { label: "Face Recognized",   color: "#818cf8", icon: "👤" },
  situation_grounding:{ label: "Grounding",          color: "#34d399", icon: "🏠" },
  activity_continuity:{ label: "Activity Reminder",  color: "#fbbf24", icon: "🔄" },
  wandering_detected: { label: "Wandering Alert",    color: "#f87171", icon: "⚠️" },
  conversation_assist:{ label: "Conversation Assist",color: "#a78bfa", icon: "💬" },
  montage_ready:      { label: "Montage Ready",      color: "#60a5fa", icon: "🎬" },
  confusion_checkin:  { label: "Check-In",           color: "#34d399", icon: "💭" },
  task_reminder:      { label: "Task Reminder",      color: "#fbbf24", icon: "📋" },
  task_completed:     { label: "Task Complete",      color: "#4ade80", icon: "✅" },
};

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function EventCard({ event, onPlayMontage }) {
  const cfg = TYPE_CONFIG[event.type] || { label: event.type, color: "#9ca3af", icon: "•" };
  const message = event.whisper || event.message || "";

  return (
    <div
      className="rounded-xl p-3.5"
      style={{
        background: "var(--card)",
        border: `1px solid ${cfg.color}22`,
        borderLeft: `3px solid ${cfg.color}`,
      }}
    >
      {/* Row: icon + badge + person + time */}
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm leading-none">{cfg.icon}</span>
        <span
          className="text-[11px] font-bold uppercase tracking-wider"
          style={{ color: cfg.color }}
        >
          {cfg.label}
        </span>
        {event.person && (
          <span className="text-[12px] font-semibold text-foreground">— {event.person}</span>
        )}
        <span className="text-[10px] text-muted-foreground ml-auto tabular-nums">
          {formatTime(event.timestamp)}
        </span>
      </div>

      {/* Message */}
      {message && (
        <p className="text-[13px] leading-relaxed text-foreground/80">"{message}"</p>
      )}

      {/* Details */}
      {event.scene && (
        <p className="text-[11px] text-muted-foreground mt-1">Scene: {event.scene}</p>
      )}
      {event.activity && (
        <p className="text-[11px] text-muted-foreground mt-1">Activity: {event.activity}</p>
      )}
      {event.confidence && (
        <p className="text-[11px] text-muted-foreground mt-1">
          Confidence: {(event.confidence * 100).toFixed(1)}%
        </p>
      )}

      {/* Play montage button */}
      {event.type === "montage_ready" && event.montage_url && (
        <button
          className="mt-2 px-3 py-1 text-[11px] font-semibold rounded-md cursor-pointer border-none transition-opacity hover:opacity-80"
          style={{ background: "rgba(96,165,250,0.15)", color: "#60a5fa", border: "1px solid rgba(96,165,250,0.25)" }}
          onClick={() => onPlayMontage?.(event)}
        >
          ▶ Play Montage
        </button>
      )}
    </div>
  );
}

export default function EventFeed({ events, onPlayMontage }) {
  if (!events.length) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-[14px]">
        No events yet — start capture to begin.
      </div>
    );
  }

  return (
    <div className="overflow-y-auto flex-1 p-4 flex flex-col gap-2.5">
      {events.map((e, i) => (
        <EventCard key={i} event={e} onPlayMontage={onPlayMontage} />
      ))}
    </div>
  );
}
