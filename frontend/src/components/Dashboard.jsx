import { useState } from "react";
import { Link } from "react-router-dom";
import EventFeed from "./EventFeed.jsx";
import TaskPanel from "./TaskPanel.jsx";
import LiveStream from "./LiveStream.jsx";
import MontagePlayer from "./MontagePlayer.jsx";
import FamilySetup from "./FamilySetup.jsx";

export default function Dashboard({ events, connected, captureRunning, captureMode, onCaptureMode, onStartCapture, onStopCapture }) {
  const [montageEvent, setMontageEvent] = useState(null);
  const [montageDismissed, setMontageDismissed] = useState(false);
  const [tab, setTab] = useState("live"); // "live" | "family"

  // Show the player when a montage_ready event arrives
  const latestMontage = events.findLast?.((e) => e.type === "montage_ready") ?? null;
  const activeMontage = montageDismissed ? null : (montageEvent ?? latestMontage);

  return (
    <div className="min-h-screen grid bg-background text-foreground" style={{ gridTemplateRows: "auto 1fr" }}>
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-3.5 border-b border-border bg-card">
        <div className="flex items-center gap-3">
          <span className="text-[13px] font-semibold tracking-widest text-muted-foreground uppercase">Rewind</span>
          <span className="text-border">·</span>
          <span className="text-[15px] font-semibold tracking-tight text-foreground">Caregiver Dashboard</span>
        </div>

        <div className="flex gap-2 items-center">
          {/* Connection status */}
          <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ${
            connected
              ? "bg-green-950/60 text-green-400 ring-1 ring-green-900"
              : "bg-red-950/60 text-red-400 ring-1 ring-red-900"
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-green-400" : "bg-red-400"}`} />
            {connected ? "Live" : "Disconnected"}
          </span>

          {/* Tabs */}
          <div className="flex gap-1 bg-muted rounded-lg p-0.5">
            <button
              className={`px-3 py-1.5 rounded-md text-[12px] font-semibold transition-all cursor-pointer border-none ${
                tab === "live"
                  ? "bg-card text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground bg-transparent"
              }`}
              onClick={() => setTab("live")}
            >
              Live
            </button>
            <button
              className={`px-3 py-1.5 rounded-md text-[12px] font-semibold transition-all cursor-pointer border-none ${
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
            className="px-3 py-1.5 rounded-lg text-[12px] font-semibold transition-colors"
            style={{
              color: "#a5b4fc",
              background: "rgba(99,102,241,0.1)",
              border: "1px solid rgba(99,102,241,0.2)",
            }}
          >
            Glasses View →
          </Link>

          {/* Mode selector */}
          {!captureRunning && (
            <select
              className="px-2.5 py-1.5 rounded-lg text-[12px] font-semibold cursor-pointer outline-none bg-accent border border-border text-foreground"
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
              className="px-3.5 py-1.5 rounded-lg text-[12px] font-semibold text-white cursor-pointer border-none transition-opacity hover:opacity-90 bg-destructive"
              onClick={onStopCapture}
            >
              Stop Capture
            </button>
          ) : (
            <button
              className="px-3.5 py-1.5 rounded-lg text-[12px] font-semibold text-white cursor-pointer border-none transition-opacity hover:opacity-90"
              style={{ background: "oklch(0.45 0.15 145)" }}
              onClick={() => onStartCapture(captureMode)}
            >
              Start Capture
            </button>
          )}
        </div>
      </header>

      {/* Body */}
      <div
        className="grid overflow-hidden"
        style={{ gridTemplateColumns: "1fr 340px", height: "calc(100vh - 57px)" }}
      >
        {tab === "live" ? (
          <LiveStream captureRunning={captureRunning} />
        ) : (
          <div className="overflow-y-auto">
            <FamilySetup />
          </div>
        )}

        <div className="flex flex-col overflow-hidden border-l border-border">
          <EventFeed events={events} />
          <TaskPanel />
        </div>
      </div>

      <MontagePlayer
        event={activeMontage}
        onClose={() => { setMontageEvent(null); setMontageDismissed(true); }}
      />
    </div>
  );
}
