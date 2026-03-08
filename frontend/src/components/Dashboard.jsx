import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import EventFeed from "./EventFeed.jsx";
import TaskPanel from "./TaskPanel.jsx";
import LiveStream from "./LiveStream.jsx";
import MontagePlayer from "./MontagePlayer.jsx";
import FamilySetup from "./FamilySetup.jsx";
import { LightRays } from "./ui/light-rays.jsx";

const C2 = "oklch(0.645 0.246 16.439)";

export default function Dashboard({ events, connected, captureRunning, captureMode, webcamIndex, onCaptureMode, onWebcamIndex, onStartCapture, onStopCapture }) {
  const [clipEvent, setClipEvent] = useState(null);
  const [clipDismissed, setClipDismissed] = useState(false);
  const [tab, setTab] = useState("live"); // "live" | "family"
  const [webcams, setWebcams] = useState([]);

  // Fetch available webcams when mode is "webcam"
  useEffect(() => {
    if (captureMode !== "webcam") return;
    fetch("/api/webcams")
      .then((r) => r.json())
      .then((data) => setWebcams(data.webcams || []))
      .catch(() => setWebcams([]));
  }, [captureMode]);

  // Show the player when an encounter_clip_ready or montage_ready event arrives
  const latestClip = events.findLast?.((e) => e.type === "encounter_clip_ready" || e.type === "montage_ready") ?? null;
  const activeClip = clipDismissed ? null : (clipEvent ?? latestClip);

  const handlePlayMedia = (e) => {
    setClipEvent(e);
    setClipDismissed(false);
  };

  const handleClose = () => {
    setClipEvent(null);
    setClipDismissed(true);
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

          {/* Webcam device picker */}
          {!captureRunning && captureMode === "webcam" && webcams.length > 0 && (
            <select
              className="px-2.5 py-1.5 text-[13px] font-medium cursor-pointer outline-none bg-accent border border-border text-foreground"
              value={webcamIndex}
              onChange={(e) => onWebcamIndex(Number(e.target.value))}
            >
              {webcams.map((cam) => (
                <option key={cam.index} value={cam.index}>
                  {cam.label}
                </option>
              ))}
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
          <EventFeed events={events} onPlayClip={handlePlayMedia} />
          <div className="flex-shrink-0 overflow-y-auto border-t border-border" style={{ maxHeight: "45%" }}>
            <TaskPanel />
          </div>
        </div>
      </div>

      <MontagePlayer event={activeClip} onClose={handleClose} />
    </div>
  );
}
