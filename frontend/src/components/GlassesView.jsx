import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";

const WS_STREAM_URL = "ws://localhost:8000/ws/stream";

export default function GlassesView({ events, connected, captureRunning, captureMode, onCaptureMode, onStartCapture, onStopCapture }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [showControls, setShowControls] = useState(true);
  const hideTimer = useRef(null);

  // ── Overlay state ──────────────────────────────────────────────────────
  const [faceCard, setFaceCard] = useState(null);
  const [groundingBanner, setGroundingBanner] = useState(null);
  const [activityReminder, setActivityReminder] = useState(null);
  const [wanderingAlert, setWanderingAlert] = useState(null);
  const [conversationWhisper, setConversationWhisper] = useState(null);
  const [activeTask, setActiveTask] = useState(null);
  const [hudContext, setHudContext] = useState(null);

  // ── Timers ─────────────────────────────────────────────────────────────
  const faceCardTimer = useRef(null);
  const groundingTimer = useRef(null);
  const activityTimer = useRef(null);
  const wanderingTimer = useRef(null);
  const whisperTimer = useRef(null);
  const lastEventRef = useRef(null);

  // ── Auto-hide controls after inactivity ────────────────────────────────
  useEffect(() => {
    const reset = () => {
      setShowControls(true);
      clearTimeout(hideTimer.current);
      hideTimer.current = setTimeout(() => setShowControls(false), 3000);
    };
    reset();
    window.addEventListener("mousemove", reset);
    return () => {
      window.removeEventListener("mousemove", reset);
      clearTimeout(hideTimer.current);
    };
  }, []);

  // ── Stream frames to canvas ────────────────────────────────────────────
  useEffect(() => {
    if (!captureRunning) return;
    let ws, rafId, latestBlob = null, stopped = false;

    function connect() {
      if (stopped) return;
      ws = new WebSocket(WS_STREAM_URL);
      ws.binaryType = "arraybuffer";
      ws.onmessage = (e) => { latestBlob = new Blob([e.data], { type: "image/jpeg" }); };
      ws.onclose = () => { if (!stopped) setTimeout(connect, 1000); };
    }

    const renderLoop = async () => {
      if (stopped) return;
      if (latestBlob) {
        const blob = latestBlob;
        latestBlob = null;
        try {
          const bitmap = await createImageBitmap(blob);
          const canvas = canvasRef.current;
          if (canvas) {
            canvas.width = bitmap.width;
            canvas.height = bitmap.height;
            canvas.getContext("2d").drawImage(bitmap, 0, 0);
          }
          bitmap.close();
        } catch {}
      }
      rafId = requestAnimationFrame(renderLoop);
    };

    connect();
    rafId = requestAnimationFrame(renderLoop);
    return () => { stopped = true; cancelAnimationFrame(rafId); ws?.close(); };
  }, [captureRunning]);

  // ── Fetch active task ──────────────────────────────────────────────────
  useEffect(() => {
    const fetchTask = async () => {
      try {
        const res = await fetch("/api/tasks");
        const data = await res.json();
        setActiveTask(data.task || null);
      } catch {}
    };
    fetchTask();
    const interval = setInterval(fetchTask, 15000);
    return () => clearInterval(interval);
  }, []);

  // ── Process incoming events ────────────────────────────────────────────
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[0];
    if (latest === lastEventRef.current) return;
    lastEventRef.current = latest;

    switch (latest.type) {
      case "face_recognized": {
        const name = latest.person || "Unknown";
        const initials = name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2);
        const bbox = latest.bbox || { x: 0, y: 0, w: 100, h: 100 };
        const frameW = latest.frame_size?.w || canvasRef.current?.width || 1280;
        const frameH = latest.frame_size?.h || canvasRef.current?.height || 720;
        const viewW = window.innerWidth;
        const viewH = window.innerHeight;
        let screenX = ((bbox.x + bbox.w / 2) / frameW) * viewW;
        let screenY = (bbox.y / frameH) * viewH;
        screenX = Math.max(170, Math.min(screenX, viewW - 170));
        screenY = Math.max(160, screenY);

        clearTimeout(faceCardTimer.current);
        setFaceCard({ name, relationship: latest.relationship || "", whisper: latest.whisper || "", initials, screenX, screenY, key: Date.now() });
        faceCardTimer.current = setTimeout(() => setFaceCard(null), 6500);
        break;
      }

      case "situation_grounding": {
        setHudContext({ scene: latest.scene, time: latest.time });
        clearTimeout(groundingTimer.current);
        setGroundingBanner({ message: latest.message, key: Date.now() });
        groundingTimer.current = setTimeout(() => setGroundingBanner(null), 10000);
        if (latest.task) setActiveTask(latest.task);
        break;
      }

      case "activity_continuity": {
        clearTimeout(activityTimer.current);
        setActivityReminder({ activity: latest.activity, locationHint: latest.location_hint, message: latest.message, key: Date.now() });
        activityTimer.current = setTimeout(() => setActivityReminder(null), 8000);
        break;
      }

      case "wandering_detected": {
        clearTimeout(wanderingTimer.current);
        setWanderingAlert({ scene: latest.scene, message: latest.message, severity: latest.severity, key: Date.now() });
        wanderingTimer.current = setTimeout(() => setWanderingAlert(null), 12000);
        break;
      }

      case "conversation_assist": {
        clearTimeout(whisperTimer.current);
        setConversationWhisper({ whisper: latest.whisper, subject: latest.subject, key: Date.now() });
        whisperTimer.current = setTimeout(() => setConversationWhisper(null), 7000);
        break;
      }

      case "task_completed": {
        setActiveTask(null);
        break;
      }
    }
  }, [events]);

  // ── Cleanup all timers on unmount ──────────────────────────────────────
  useEffect(() => {
    return () => {
      clearTimeout(faceCardTimer.current);
      clearTimeout(groundingTimer.current);
      clearTimeout(activityTimer.current);
      clearTimeout(wanderingTimer.current);
      clearTimeout(whisperTimer.current);
    };
  }, []);

  return (
    <div ref={containerRef} style={styles.root}>
      {/* Full-screen stream */}
      {captureRunning ? (
        <canvas ref={canvasRef} style={styles.canvas} />
      ) : (
        <div style={styles.idle}>
          <div style={styles.idleOrb} />
          <p style={styles.idleText}>REWIND</p>
          <p style={styles.idleSub}>Start capture to begin</p>
        </div>
      )}

      {/* ── Top bar ─────────────────────────────────────────────────────── */}
      <div style={{ ...styles.topBar, opacity: showControls ? 1 : 0 }}>
        <Link to="/" style={styles.backLink}>Dashboard</Link>
        <div style={styles.topCenter}>
          <span style={styles.logo}>REWIND</span>
          <span style={styles.statusDot(connected)} />
        </div>
        <div style={styles.topRight}>
          {!captureRunning && (
            <select
              style={styles.modeSelect}
              value={captureMode}
              onChange={(e) => onCaptureMode(e.target.value)}
            >
              <option value="glasses">Meta Glasses</option>
              <option value="webcam">Webcam</option>
            </select>
          )}
          <button
            style={styles.captureBtn(captureRunning)}
            onClick={captureRunning ? onStopCapture : () => onStartCapture(captureMode)}
          >
            {captureRunning ? "Stop" : "Start"}
          </button>
        </div>
      </div>

      {/* ── Passive HUD — scene + time (top-left) ─────────────────────── */}
      {captureRunning && hudContext && (
        <div style={styles.hud}>
          <div style={styles.hudDot} />
          <span style={styles.hudText}>{hudContext.scene}</span>
          <span style={styles.hudSep}>{"\u00B7"}</span>
          <span style={styles.hudText}>{hudContext.time}</span>
        </div>
      )}

      {/* ── Active Task Pill (top center, below bar) ──────────────────── */}
      {activeTask && (
        <div key={activeTask} style={styles.taskPill}>
          <span style={styles.taskLabel}>TASK</span>
          <span style={styles.taskText}>{activeTask}</span>
        </div>
      )}

      {/* ── Face Recognition Card — floats above the person ───────────── */}
      {faceCard && (
        <div
          key={faceCard.key}
          style={{
            position: "absolute",
            left: faceCard.screenX,
            top: faceCard.screenY,
            transform: "translate(-50%, -100%)",
            marginTop: -16,
            zIndex: 20,
            pointerEvents: "none",
          }}
        >
          <div style={styles.faceCard}>
            <div style={styles.faceCardHeader}>
              <div style={styles.faceCardAvatar}>
                <span style={styles.faceCardInitials}>{faceCard.initials}</span>
              </div>
              <div>
                <div style={styles.faceCardName}>{faceCard.name}</div>
                {faceCard.relationship && (
                  <div style={styles.faceCardRelationship}>{faceCard.relationship}</div>
                )}
              </div>
            </div>
            {faceCard.whisper && (
              <p style={styles.faceCardWhisper}>"{faceCard.whisper}"</p>
            )}
          </div>
        </div>
      )}

      {/* ── Wandering Alert (center screen, amber) ────────────────────── */}
      {wanderingAlert && (
        <div key={wanderingAlert.key} style={styles.wanderingOverlay}>
          <div style={styles.wanderingCard}>
            <div style={styles.wanderingIconRow}>
              <div style={styles.wanderingDot} />
              <span style={styles.wanderingLabel}>Gentle Redirect</span>
            </div>
            <p style={styles.wanderingMessage}>{wanderingAlert.message}</p>
            <p style={styles.wanderingScene}>{wanderingAlert.scene}</p>
          </div>
        </div>
      )}

      {/* ── Grounding Banner — full width at very bottom ──────────────── */}
      {groundingBanner && (
        <div key={groundingBanner.key} style={styles.groundingBanner}>
          <p style={styles.groundingMessage}>{groundingBanner.message}</p>
        </div>
      )}

      {/* ── Bottom card stack — activity + whisper above grounding ─────── */}
      <div style={{ ...styles.bottomStack, bottom: groundingBanner ? 110 : 24 }}>
        {activityReminder && (
          <div key={activityReminder.key} style={styles.activityCard}>
            <div style={styles.activityHeader}>
              <div style={styles.activityDot} />
              <span style={styles.activityLabel}>Activity Reminder</span>
            </div>
            <p style={styles.activityMessage}>{activityReminder.message}</p>
          </div>
        )}
        {conversationWhisper && (
          <div key={conversationWhisper.key} style={styles.whisperCard}>
            <p style={styles.whisperText}>"{conversationWhisper.whisper}"</p>
            {conversationWhisper.subject && (
              <p style={styles.whisperSubject}>Re: {conversationWhisper.subject}</p>
            )}
          </div>
        )}
      </div>

      {/* ── AI processing indicator ───────────────────────────────────── */}
      {captureRunning && (
        <div style={{ ...styles.aiIndicator, opacity: showControls ? 1 : 0.4 }}>
          <div style={styles.aiPulse} />
          <span style={styles.aiText}>AI Active</span>
        </div>
      )}
    </div>
  );
}

// ── CSS keyframes ────────────────────────────────────────────────────────────
const cssText = `
@keyframes rewind-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}
@keyframes rewind-orb {
  0%, 100% { transform: scale(1); opacity: 0.15; }
  50% { transform: scale(1.1); opacity: 0.25; }
}
@keyframes visionCardIn {
  from { opacity: 0; transform: scale(0.85) translateY(8px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}
@keyframes visionCardOut {
  from { opacity: 1; transform: scale(1) translateY(0); }
  to { opacity: 0; transform: scale(0.92) translateY(-4px); }
}
@keyframes groundingIn {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes groundingOut {
  from { opacity: 1; transform: translateY(0); }
  to { opacity: 0; transform: translateY(20px); }
}
@keyframes overlayIn {
  from { opacity: 0; transform: translateY(12px) scale(0.96); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@keyframes overlayOut {
  from { opacity: 1; }
  to { opacity: 0; transform: translateY(-6px) scale(0.98); }
}
@keyframes wanderingIn {
  from { opacity: 0; transform: scale(0.85); }
  to { opacity: 1; transform: scale(1); }
}
@keyframes wanderingOut {
  from { opacity: 1; }
  to { opacity: 0; transform: scale(0.93); }
}
@keyframes amberPulse {
  0%, 100% { box-shadow: 0 0 30px color-mix(in oklch, oklch(0.704 0.191 22.216) 10%, transparent), 0 0 0 0.5px color-mix(in oklch, oklch(0.704 0.191 22.216) 15%, transparent) inset; }
  50% { box-shadow: 0 0 50px color-mix(in oklch, oklch(0.704 0.191 22.216) 25%, transparent), 0 0 0 0.5px color-mix(in oklch, oklch(0.704 0.191 22.216) 30%, transparent) inset; }
}
@keyframes hudFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
@keyframes taskSlideIn {
  from { opacity: 0; transform: translateX(-50%) translateY(-8px); }
  to { opacity: 1; transform: translateX(-50%) translateY(0); }
}
`;

if (typeof document !== "undefined" && !document.getElementById("rewind-glasses-css")) {
  const style = document.createElement("style");
  style.id = "rewind-glasses-css";
  style.textContent = cssText;
  document.head.appendChild(style);
}

// ── Styles ───────────────────────────────────────────────────────────────────
const styles = {
  root: {
    position: "fixed",
    inset: 0,
    background: "#000",
    overflow: "hidden",
  },
  canvas: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    objectFit: "contain",
  },
  idle: {
    position: "absolute",
    inset: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
  },
  idleOrb: {
    width: 120,
    height: 120,
    borderRadius: "50%",
    background: "radial-gradient(circle, oklch(0.455 0.188 13.697) 0%, transparent 70%)",
    animation: "rewind-orb 3s ease-in-out infinite",
  },
  idleText: {
    fontSize: 28,
    fontWeight: 800,
    letterSpacing: "0.15em",
    color: "#e8e8f0",
  },
  idleSub: {
    fontSize: 14,
    color: "#555",
  },

  // ── Top bar — glassmorphic ────────────────────────────────────────────────
  topBar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "14px 24px",
    background: "rgba(0, 0, 0, 0.2)",
    backdropFilter: "blur(24px) saturate(150%)",
    WebkitBackdropFilter: "blur(24px) saturate(150%)",
    borderBottom: "1px solid rgba(255, 255, 255, 0.06)",
    transition: "opacity 0.4s ease",
    zIndex: 10,
  },
  backLink: {
    color: "#9ca3af",
    textDecoration: "none",
    fontSize: 14,
    fontWeight: 600,
  },
  topCenter: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  logo: {
    fontSize: 16,
    fontWeight: 800,
    letterSpacing: "0.1em",
    color: "#e8e8f0",
  },
  statusDot: (connected) => ({
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: connected ? "oklch(0.645 0.246 16.439)" : "oklch(0.704 0.191 22.216)",
    boxShadow: connected ? "0 0 6px oklch(0.645 0.246 16.439)" : "0 0 6px oklch(0.704 0.191 22.216)",
  }),
  topRight: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  modeSelect: {
    padding: "5px 10px",
    borderRadius: 0,
    border: "1px solid rgba(255,255,255,0.15)",
    background: "rgba(255,255,255,0.08)",
    color: "#e8e8f0",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    outline: "none",
  },
  captureBtn: (active) => ({
    padding: "6px 16px",
    borderRadius: 0,
    border: "none",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
    background: active ? "oklch(0.704 0.191 22.216)" : "oklch(0.455 0.188 13.697)",
    color: "#fff",
  }),

  // ── Passive HUD (top-left) ────────────────────────────────────────────────
  hud: {
    position: "absolute",
    top: 70,
    left: 24,
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "8px 16px",
    borderRadius: 0,
    background: "rgba(0, 0, 0, 0.35)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    border: "1px solid rgba(255, 255, 255, 0.06)",
    zIndex: 10,
    pointerEvents: "none",
    animation: "hudFadeIn 0.5s ease forwards",
  },
  hudDot: {
    width: 6,
    height: 6,
    borderRadius: "50%",
    background: "oklch(0.645 0.246 16.439)",
    opacity: 0.7,
    flexShrink: 0,
  },
  hudText: {
    fontSize: 13,
    fontWeight: 500,
    color: "rgba(255, 255, 255, 0.5)",
    textTransform: "capitalize",
  },
  hudSep: {
    fontSize: 13,
    color: "rgba(255, 255, 255, 0.2)",
  },

  // ── Active Task Pill (top center) ─────────────────────────────────────────
  taskPill: {
    position: "absolute",
    top: 70,
    left: "50%",
    transform: "translateX(-50%)",
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "8px 20px",
    borderRadius: 0,
    background: "color-mix(in oklch, oklch(0.455 0.188 13.697) 12%, transparent)",
    backdropFilter: "blur(20px)",
    WebkitBackdropFilter: "blur(20px)",
    border: "1px solid color-mix(in oklch, oklch(0.455 0.188 13.697) 20%, transparent)",
    zIndex: 10,
    pointerEvents: "none",
    animation: "taskSlideIn 0.3s ease forwards",
  },
  taskLabel: {
    fontSize: 11,
    fontWeight: 700,
    letterSpacing: "0.08em",
    color: "oklch(0.645 0.246 16.439)",
    textTransform: "uppercase",
    flexShrink: 0,
  },
  taskText: {
    fontSize: 14,
    fontWeight: 500,
    color: "rgba(255, 255, 255, 0.7)",
    maxWidth: 400,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },

  // ── Face Recognition Card ─────────────────────────────────────────────────
  faceCard: {
    width: 300,
    padding: "18px 20px",
    borderRadius: 0,
    background: "rgba(255, 255, 255, 0.05)",
    backdropFilter: "blur(50px) saturate(200%)",
    WebkitBackdropFilter: "blur(50px) saturate(200%)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    boxShadow:
      "0 16px 48px rgba(0, 0, 0, 0.5), " +
      "0 0 0 0.5px rgba(255, 255, 255, 0.04) inset, " +
      "0 1px 0 rgba(255, 255, 255, 0.06) inset",
    animation:
      "visionCardIn 0.45s cubic-bezier(0.34, 1.56, 0.64, 1) forwards, " +
      "visionCardOut 0.4s ease 5.8s forwards",
  },
  faceCardHeader: {
    display: "flex",
    alignItems: "center",
    gap: 14,
  },
  faceCardAvatar: {
    width: 48,
    height: 48,
    borderRadius: "50%",
    background: "linear-gradient(135deg, oklch(0.586 0.253 17.585) 0%, oklch(0.455 0.188 13.697) 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    boxShadow: "0 2px 12px color-mix(in oklch, oklch(0.586 0.253 17.585) 25%, transparent)",
  },
  faceCardInitials: {
    fontSize: 18,
    fontWeight: 700,
    color: "#fff",
  },
  faceCardName: {
    fontSize: 17,
    fontWeight: 600,
    color: "#fff",
    letterSpacing: "-0.01em",
  },
  faceCardRelationship: {
    fontSize: 13,
    fontWeight: 500,
    color: "rgba(255, 255, 255, 0.4)",
    textTransform: "capitalize",
    marginTop: 2,
  },
  faceCardWhisper: {
    fontSize: 14,
    lineHeight: 1.55,
    color: "rgba(255, 255, 255, 0.5)",
    fontStyle: "italic",
    margin: "14px 0 0",
    paddingTop: 14,
    borderTop: "1px solid rgba(255, 255, 255, 0.06)",
  },

  // ── Wandering Alert (center, amber) ───────────────────────────────────────
  wanderingOverlay: {
    position: "absolute",
    inset: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 30,
    pointerEvents: "none",
  },
  wanderingCard: {
    maxWidth: 440,
    padding: "28px 36px",
    borderRadius: 0,
    background: "color-mix(in oklch, oklch(0.704 0.191 22.216) 15%, transparent)",
    backdropFilter: "blur(50px) saturate(180%)",
    WebkitBackdropFilter: "blur(50px) saturate(180%)",
    border: "1px solid color-mix(in oklch, oklch(0.704 0.191 22.216) 20%, transparent)",
    textAlign: "center",
    animation:
      "wanderingIn 0.5s cubic-bezier(0.34, 1.56, 0.64, 1) forwards, " +
      "wanderingOut 0.5s ease 11s forwards, " +
      "amberPulse 3s ease-in-out infinite",
  },
  wanderingIconRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    marginBottom: 18,
  },
  wanderingDot: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    background: "oklch(0.704 0.191 22.216)",
    boxShadow: "0 0 12px color-mix(in oklch, oklch(0.704 0.191 22.216) 50%, transparent)",
  },
  wanderingLabel: {
    fontSize: 13,
    fontWeight: 700,
    letterSpacing: "0.06em",
    color: "oklch(0.704 0.191 22.216)",
    textTransform: "uppercase",
  },
  wanderingMessage: {
    fontSize: 22,
    fontWeight: 500,
    lineHeight: 1.4,
    color: "rgba(255, 255, 255, 0.85)",
    margin: 0,
  },
  wanderingScene: {
    fontSize: 13,
    color: "color-mix(in oklch, oklch(0.704 0.191 22.216) 50%, transparent)",
    marginTop: 14,
    textTransform: "capitalize",
  },

  // ── Grounding Banner (full-width, very bottom) ────────────────────────────
  groundingBanner: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    padding: "22px 32px",
    background: "rgba(0, 0, 0, 0.45)",
    backdropFilter: "blur(40px) saturate(150%)",
    WebkitBackdropFilter: "blur(40px) saturate(150%)",
    borderTop: "1px solid rgba(255, 255, 255, 0.06)",
    zIndex: 15,
    pointerEvents: "none",
    animation:
      "groundingIn 0.5s ease forwards, " +
      "groundingOut 0.5s ease 9s forwards",
  },
  groundingMessage: {
    fontSize: 18,
    fontWeight: 400,
    lineHeight: 1.5,
    color: "rgba(255, 255, 255, 0.8)",
    textAlign: "center",
    margin: 0,
    maxWidth: 700,
    marginLeft: "auto",
    marginRight: "auto",
  },

  // ── Bottom card stack (above grounding) ───────────────────────────────────
  bottomStack: {
    position: "absolute",
    left: 0,
    right: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 12,
    zIndex: 15,
    pointerEvents: "none",
    transition: "bottom 0.4s ease",
  },

  // ── Activity Reminder Card ────────────────────────────────────────────────
  activityCard: {
    maxWidth: 480,
    width: "90%",
    padding: "16px 22px",
    borderRadius: 0,
    background: "rgba(255, 255, 255, 0.05)",
    backdropFilter: "blur(40px) saturate(180%)",
    WebkitBackdropFilter: "blur(40px) saturate(180%)",
    border: "1px solid rgba(255, 255, 255, 0.08)",
    boxShadow: "0 12px 40px rgba(0, 0, 0, 0.4)",
    animation:
      "overlayIn 0.4s ease forwards, " +
      "overlayOut 0.4s ease 7s forwards",
  },
  activityHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 10,
  },
  activityDot: {
    width: 8,
    height: 8,
    borderRadius: "50%",
    background: "oklch(0.586 0.253 17.585)",
    boxShadow: "0 0 8px color-mix(in oklch, oklch(0.586 0.253 17.585) 40%, transparent)",
    flexShrink: 0,
  },
  activityLabel: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: "0.06em",
    color: "oklch(0.586 0.253 17.585)",
    textTransform: "uppercase",
  },
  activityMessage: {
    fontSize: 16,
    fontWeight: 400,
    lineHeight: 1.5,
    color: "rgba(255, 255, 255, 0.75)",
    margin: 0,
  },

  // ── Conversation Whisper (subtitle-style) ─────────────────────────────────
  whisperCard: {
    maxWidth: 520,
    width: "90%",
    padding: "12px 22px",
    borderRadius: 0,
    background: "rgba(255, 255, 255, 0.03)",
    backdropFilter: "blur(30px)",
    WebkitBackdropFilter: "blur(30px)",
    border: "1px solid rgba(255, 255, 255, 0.05)",
    animation:
      "overlayIn 0.3s ease forwards, " +
      "overlayOut 0.4s ease 6s forwards",
  },
  whisperText: {
    fontSize: 15,
    fontWeight: 400,
    fontStyle: "italic",
    lineHeight: 1.5,
    color: "rgba(255, 255, 255, 0.6)",
    textAlign: "center",
    margin: 0,
  },
  whisperSubject: {
    fontSize: 12,
    fontWeight: 500,
    color: "rgba(255, 255, 255, 0.25)",
    textAlign: "center",
    marginTop: 6,
  },

  // ── AI indicator ──────────────────────────────────────────────────────────
  aiIndicator: {
    position: "absolute",
    bottom: 24,
    right: 24,
    display: "flex",
    alignItems: "center",
    gap: 8,
    transition: "opacity 0.4s ease",
    zIndex: 10,
  },
  aiPulse: {
    width: 10,
    height: 10,
    borderRadius: "50%",
    background: "oklch(0.455 0.188 13.697)",
    boxShadow: "0 0 8px oklch(0.455 0.188 13.697)",
    animation: "rewind-pulse 2s ease-in-out infinite",
  },
  aiText: {
    fontSize: 12,
    fontWeight: 700,
    color: "oklch(0.645 0.246 16.439)",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
};
