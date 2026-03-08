import { useState, useEffect, useRef } from "react";
import { Link } from "react-router-dom";

const WS_STREAM_URL = "ws://localhost:8000/ws/stream";

const TYPE_CONFIG = {
  face_recognized: { label: "Face Recognized", color: "#818cf8", icon: "👤" },
  situation_grounding: { label: "Grounding", color: "#34d399", icon: "🏠" },
  activity_continuity: { label: "Activity Reminder", color: "#fbbf24", icon: "🔄" },
  wandering_detected: { label: "Wandering Alert", color: "#f87171", icon: "⚠️" },
  conversation_assist: { label: "Conversation Assist", color: "#a78bfa", icon: "💬" },
  montage_ready: { label: "Montage Ready", color: "#60a5fa", icon: "🎬" },
};

export default function GlassesView({ events, connected, captureRunning, captureMode, onCaptureMode, onStartCapture, onStopCapture }) {
  const canvasRef = useRef(null);
  const containerRef = useRef(null);
  const [showControls, setShowControls] = useState(true);
  const hideTimer = useRef(null);
  const [visibleEvents, setVisibleEvents] = useState([]);

  // Auto-hide controls after inactivity
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

  // Stream frames to canvas
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

  // Show latest events as HUD toasts, auto-dismiss after 6s
  useEffect(() => {
    if (events.length === 0) return;
    const latest = events[0];
    const id = Date.now() + Math.random();
    setVisibleEvents((prev) => [{ ...latest, _id: id }, ...prev].slice(0, 5));
    const timer = setTimeout(() => {
      setVisibleEvents((prev) => prev.filter((e) => e._id !== id));
    }, 6000);
    return () => clearTimeout(timer);
  }, [events.length]);

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

      {/* Top bar — fades on inactivity */}
      <div style={{ ...styles.topBar, opacity: showControls ? 1 : 0 }}>
        <Link to="/" style={styles.backLink}>← Dashboard</Link>
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

      {/* HUD event toasts — bottom-left */}
      <div style={styles.toastContainer}>
        {visibleEvents.map((evt) => {
          const cfg = TYPE_CONFIG[evt.type] || { label: evt.type, color: "#9ca3af", icon: "•" };
          const message = evt.whisper || evt.message || "";
          return (
            <div key={evt._id} style={styles.toast(cfg.color)}>
              <div style={styles.toastHeader}>
                <span>{cfg.icon}</span>
                <span style={{ color: cfg.color, fontWeight: 700, fontSize: 12, textTransform: "uppercase" }}>{cfg.label}</span>
                {evt.person && <span style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 13 }}>— {evt.person}</span>}
              </div>
              {message && <p style={styles.toastMessage}>"{message}"</p>}
            </div>
          );
        })}
      </div>

      {/* AI processing indicator */}
      {captureRunning && (
        <div style={{ ...styles.aiIndicator, opacity: showControls ? 1 : 0.4 }}>
          <div style={styles.aiPulse} />
          <span style={styles.aiText}>AI Active</span>
        </div>
      )}
    </div>
  );
}

const pulse = `
@keyframes rewind-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.3); }
}
@keyframes rewind-orb {
  0%, 100% { transform: scale(1); opacity: 0.15; }
  50% { transform: scale(1.1); opacity: 0.25; }
}
`;

// Inject keyframes once
if (typeof document !== "undefined" && !document.getElementById("rewind-glasses-css")) {
  const style = document.createElement("style");
  style.id = "rewind-glasses-css";
  style.textContent = pulse;
  document.head.appendChild(style);
}

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
    background: "radial-gradient(circle, #4f46e5 0%, transparent 70%)",
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
  // Top bar
  topBar: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "14px 24px",
    background: "linear-gradient(to bottom, rgba(0,0,0,0.7) 0%, transparent 100%)",
    transition: "opacity 0.4s ease",
    zIndex: 10,
  },
  backLink: {
    color: "#9ca3af",
    textDecoration: "none",
    fontSize: 14,
    fontWeight: 600,
    transition: "color 0.15s",
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
    background: connected ? "#22c55e" : "#ef4444",
    boxShadow: connected ? "0 0 6px #22c55e" : "0 0 6px #ef4444",
  }),
  topRight: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  modeSelect: {
    padding: "5px 10px",
    borderRadius: 6,
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
    borderRadius: 6,
    border: "none",
    cursor: "pointer",
    fontWeight: 700,
    fontSize: 13,
    background: active ? "#dc2626" : "#16a34a",
    color: "#fff",
  }),
  // HUD toasts
  toastContainer: {
    position: "absolute",
    bottom: 24,
    left: 24,
    display: "flex",
    flexDirection: "column-reverse",
    gap: 10,
    zIndex: 10,
    maxWidth: 420,
  },
  toast: (color) => ({
    background: "rgba(15, 15, 20, 0.85)",
    backdropFilter: "blur(12px)",
    border: `1px solid ${color}44`,
    borderLeft: `3px solid ${color}`,
    borderRadius: 10,
    padding: "10px 16px",
    animation: "rewind-pulse 0.3s ease-out",
  }),
  toastHeader: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    marginBottom: 4,
  },
  toastMessage: {
    fontSize: 14,
    lineHeight: 1.5,
    color: "#d1d5db",
    margin: 0,
  },
  // AI indicator
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
    background: "#4f46e5",
    boxShadow: "0 0 8px #4f46e5",
    animation: "rewind-pulse 2s ease-in-out infinite",
  },
  aiText: {
    fontSize: 12,
    fontWeight: 700,
    color: "#818cf8",
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
};
