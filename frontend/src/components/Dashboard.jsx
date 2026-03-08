import { useState } from "react";
import { Link } from "react-router-dom";
import EventFeed from "./EventFeed.jsx";
import TaskPanel from "./TaskPanel.jsx";
import LiveStream from "./LiveStream.jsx";
import MontagePlayer from "./MontagePlayer.jsx";
import FamilySetup from "./FamilySetup.jsx";


const styles = {
  root: {
    minHeight: "100vh",
    display: "grid",
    gridTemplateRows: "auto 1fr",
    background: "#0f0f14",
    color: "#e8e8f0",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "16px 24px",
    borderBottom: "1px solid #1e1e2e",
    background: "#13131a",
  },
  title: { fontSize: 22, fontWeight: 700, letterSpacing: "-0.5px" },
  pill: (connected) => ({
    padding: "4px 12px",
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 600,
    background: connected ? "#14532d" : "#450a0a",
    color: connected ? "#86efac" : "#fca5a5",
  }),
  controls: { display: "flex", gap: 10, alignItems: "center" },
  modeSelect: {
    padding: "6px 10px",
    borderRadius: 8,
    border: "1px solid #2d2d3d",
    background: "#1a1a24",
    color: "#e8e8f0",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    outline: "none",
  },
  tabBtn: (active) => ({
    padding: "6px 14px",
    borderRadius: 8,
    border: "none",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 13,
    background: active ? "#4f46e5" : "#1a1a24",
    color: active ? "#fff" : "#9ca3af",
    transition: "background 0.15s",
  }),
  btn: (active) => ({
    padding: "8px 18px",
    borderRadius: 8,
    border: "none",
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 14,
    background: active ? "#dc2626" : "#16a34a",
    color: "#fff",
    transition: "opacity 0.15s",
  }),
  body: {
    display: "grid",
    gridTemplateColumns: "1fr 340px",
    gap: 0,
    height: "calc(100vh - 65px)",
    overflow: "hidden",
  },
  sidebar: {
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderLeft: "1px solid #1e1e2e",
  },
  glassesLink: {
    padding: "6px 14px",
    borderRadius: 8,
    fontSize: 13,
    fontWeight: 600,
    color: "#818cf8",
    textDecoration: "none",
    background: "rgba(79, 70, 229, 0.12)",
    border: "1px solid rgba(79, 70, 229, 0.25)",
    transition: "background 0.15s",
  },
};

export default function Dashboard({ events, connected, captureRunning, captureMode, onCaptureMode, onStartCapture, onStopCapture }) {
  // ID (timestamp) of the event the user explicitly clicked "Play" on
  const [pinnedId, setPinnedId] = useState(null);
  // Set of timestamps the user has dismissed — prevents auto-pop from reopening them
  const [dismissedIds, setDismissedIds] = useState(() => new Set());
  const [tab, setTab] = useState("live"); // "live" | "family"

  // Use a plain loop instead of Array.findLast (not available in older browsers)
  const latestMontage = (() => {
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === "montage_ready") return events[i];
    }
    return null;
  })();

  // Pinned event takes priority; otherwise auto-show latest unless dismissed
  const activeMontage = (() => {
    if (pinnedId) {
      return events.find((e) => e.type === "montage_ready" && e.timestamp === pinnedId) ?? null;
    }
    if (latestMontage && !dismissedIds.has(latestMontage.timestamp)) {
      return latestMontage;
    }
    return null;
  })();

  const handlePlayMontage = (event) => {
    // Un-dismiss this event in case the user previously closed it
    setDismissedIds((prev) => { const next = new Set(prev); next.delete(event.timestamp); return next; });
    setPinnedId(event.timestamp);
  };

  const handleClose = () => {
    if (activeMontage) {
      setDismissedIds((prev) => new Set([...prev, activeMontage.timestamp]));
    }
    setPinnedId(null);
  };

  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <span style={styles.title}>REWIND — Caregiver Dashboard</span>
        <div style={styles.controls}>
          <span style={styles.pill(connected)}>
            {connected ? "● Live" : "○ Disconnected"}
          </span>
          <button style={styles.tabBtn(tab === "live")} onClick={() => setTab("live")}>Live</button>
          <button style={styles.tabBtn(tab === "family")} onClick={() => setTab("family")}>Family Setup</button>
          <Link to="/glasses" style={styles.glassesLink}>Glasses View →</Link>
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
          {captureRunning ? (
            <button style={styles.btn(true)} onClick={onStopCapture}>Stop Capture</button>
          ) : (
            <button style={styles.btn(false)} onClick={() => onStartCapture(captureMode)}>Start Capture</button>
          )}
        </div>
      </header>

      <div style={styles.body}>
        {tab === "live" ? (
          <LiveStream captureRunning={captureRunning} />
        ) : (
          <div style={{ overflowY: "auto" }}><FamilySetup /></div>
        )}
        <div style={styles.sidebar}>
          <EventFeed events={events} onPlayMontage={handlePlayMontage} />
          <TaskPanel />
        </div>
      </div>

      <MontagePlayer event={activeMontage} onClose={handleClose} />
    </div>
  );
}
