import { useState } from "react";
import EventFeed from "./EventFeed.jsx";
import TaskPanel from "./TaskPanel.jsx";

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
};

export default function Dashboard({ events, connected, captureRunning, onStartCapture, onStopCapture }) {
  return (
    <div style={styles.root}>
      <header style={styles.header}>
        <span style={styles.title}>REWIND — Caregiver Dashboard</span>
        <div style={styles.controls}>
          <span style={styles.pill(connected)}>
            {connected ? "● Live" : "○ Disconnected"}
          </span>
          {captureRunning ? (
            <button style={styles.btn(true)} onClick={onStopCapture}>Stop Capture</button>
          ) : (
            <button style={styles.btn(false)} onClick={onStartCapture}>Start Capture</button>
          )}
        </div>
      </header>

      <div style={styles.body}>
        <EventFeed events={events} />
        <TaskPanel />
      </div>
    </div>
  );
}
