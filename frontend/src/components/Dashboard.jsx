import { useState } from "react";
import { Link } from "react-router-dom";
import EventFeed from "./EventFeed.jsx";
import TaskPanel from "./TaskPanel.jsx";
import LiveStream from "./LiveStream.jsx";
import MontagePlayer from "./MontagePlayer.jsx";
import FamilySetup from "./FamilySetup.jsx";
import { LightRays } from "./ui/light-rays.jsx";

const C2 = "oklch(0.645 0.246 16.439)";

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
    <div className="relative h-screen grid bg-background text-foreground overflow-hidden" style={{ gridTemplateRows: "auto 1fr" }}>
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3.5 border-b border-border bg-background">
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-medium tracking-widest text-muted-foreground uppercase">Rewind</span>
          <span className="text-border">·</span>
          <span className="text-[17px] font-normal tracking-tight text-foreground">Caregiver Dashboard</span>
        </div>

        <div className="flex gap-2.5 items-center">
          {/* Connection status */}
          <span
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium"
            style={connected ? {
              background: `color-mix(in oklch, ${C2} 12%, transparent)`,
              color: C2,
              boxShadow: `0 0 0 1px color-mix(in oklch, ${C2} 25%, transparent)`,
            } : {
              background: "color-mix(in oklch, var(--destructive) 12%, transparent)",
              color: "var(--destructive)",
              boxShadow: "0 0 0 1px color-mix(in oklch, var(--destructive) 25%, transparent)",
            }}
          >
            <span
              className="w-1.5 h-1.5"
              style={{ background: connected ? C2 : "var(--destructive)" }}
            />
            {connected ? "Live" : "Disconnected"}
          </span>

          {/* Tabs */}
          <div className="flex gap-0.5 bg-muted p-0.5">
            <button
              className={`px-3.5 py-1.5 text-[13px] font-medium transition-all cursor-pointer border-none ${
                tab === "live"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground bg-transparent"
              }`}
              onClick={() => setTab("live")}
            >
              Live
            </button>
            <button
              className={`px-3.5 py-1.5 text-[13px] font-medium transition-all cursor-pointer border-none ${
                tab === "family"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground bg-transparent"
              }`}
              onClick={() => setTab("family")}
            >
              Family Setup
            </button>
          </div>

          {/* Glasses view link */}
          <Link
            to="/glasses"
            className="px-3.5 py-1.5 text-[13px] font-medium transition-colors"
            style={{
              color: "var(--primary-foreground)",
              background: "var(--primary)",
            }}
          >
            Glasses View →
          </Link>

          {/* Mode selector */}
          {!captureRunning && (
            <select
              className="px-2.5 py-1.5 text-[13px] font-medium cursor-pointer outline-none bg-accent border border-border text-foreground"
              value={captureMode}
              onChange={(e) => onCaptureMode(e.target.value)}
            >
              <option value="glasses">Meta Glasses</option>
              <option value="webcam">Webcam</option>
            </select>
          )}

          {/* Capture toggle */}
          {captureRunning ? (
            <button
              className="px-4 py-1.5 text-[13px] font-medium cursor-pointer border-none transition-opacity hover:opacity-90"
              style={{ background: "var(--destructive)", color: "var(--primary-foreground)" }}
              onClick={onStopCapture}
            >
              Stop Capture
            </button>
          ) : (
            <button
              className="px-4 py-1.5 text-[13px] font-medium cursor-pointer border-none transition-opacity hover:opacity-90"
              style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
              onClick={() => onStartCapture(captureMode)}
            >
              Start Capture
            </button>
          )}
        </div>
      </header>

      {/* Body */}
      <div
        className="relative grid overflow-hidden"
        style={{ gridTemplateColumns: "1fr 340px", height: "calc(100vh - 57px)" }}
      >
        <LightRays color="oklch(0.645 0.246 16.439 / 0.08)" count={5} blur={50} speed={18} className="z-50" />
        {tab === "live" ? (
          <LiveStream captureRunning={captureRunning} />
        ) : (
          <div className="overflow-y-auto">
            <FamilySetup />
          </div>
        )}

        <div className="flex flex-col overflow-hidden border-l border-border">
          <EventFeed events={events} onPlayMontage={handlePlayMontage} />
          <TaskPanel />
        </div>
      </div>

      <MontagePlayer event={activeMontage} onClose={handleClose} />

    </div>
  );
}
