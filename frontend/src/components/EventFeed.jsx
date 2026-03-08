// All colors are from the Lyra Rose palette (chart-1 through chart-5, primary, destructive)
const C1 = "oklch(0.81 0.117 11.638)";   // chart-1 — light rose
const C2 = "oklch(0.645 0.246 16.439)";  // chart-2 — medium rose
const C3 = "oklch(0.586 0.253 17.585)";  // chart-3 — deeper rose
const C4 = "oklch(0.514 0.222 16.935)";  // chart-4 — dark rose
const C5 = "oklch(0.455 0.188 13.697)";  // chart-5 — darkest rose
const CD = "oklch(0.704 0.191 22.216)";  // destructive — bright red-rose

const TYPE_CONFIG = {
  face_recognized:    { label: "Face Recognized",    color: C2, icon: "👤" },
  situation_grounding:{ label: "Grounding",           color: C1, icon: "🏠" },
  activity_continuity:{ label: "Activity Reminder",   color: C3, icon: "🔄" },
  wandering_detected: { label: "Wandering Alert",     color: CD, icon: "⚠️" },
  conversation_assist:{ label: "Conversation Assist", color: C4, icon: "💬" },
  montage_ready:      { label: "Montage Ready",       color: C5, icon: "🎬" },
  confusion_checkin:  { label: "Check-In",            color: C1, icon: "💭" },
  task_reminder:      { label: "Task Reminder",       color: C3, icon: "📋" },
  task_completed:     { label: "Task Complete",       color: C2, icon: "✅" },
};

function formatTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function EventCard({ event, onPlayMontage }) {
  const cfg = TYPE_CONFIG[event.type] || { label: event.type, color: "var(--muted-foreground)", icon: "•" };
  const message = event.whisper || event.message || "";

  return (
    <div
      className="p-3.5"
      style={{
        background: "var(--card)",
        border: "1px solid var(--border)",
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
          className="mt-2 px-3 py-1 text-[11px] font-semibold cursor-pointer transition-opacity hover:opacity-80"
          style={{
            background: `color-mix(in oklch, ${C5} 15%, transparent)`,
            color: C5,
            border: `1px solid color-mix(in oklch, ${C5} 30%, transparent)`,
          }}
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
      <div className="flex items-center justify-center h-full text-foreground text-[14px]">
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
