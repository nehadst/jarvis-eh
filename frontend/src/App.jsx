import { useState, useEffect } from "react";
import Dashboard from "./components/Dashboard.jsx";
import { connectWebSocket } from "./api/client.js";

export default function App() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [captureRunning, setCaptureRunning] = useState(false);
  const [captureMode, setCaptureMode] = useState("glasses");

  useEffect(() => {
    const ws = connectWebSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onEvent: (event) => setEvents((prev) => [event, ...prev].slice(0, 100)),
    });
    return () => ws.close();
  }, []);

  const startCapture = async (mode) => {
    await fetch("/api/capture/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    setCaptureRunning(true);
  };

  const stopCapture = async () => {
    await fetch("/api/capture/stop", { method: "POST" });
    setCaptureRunning(false);
  };

  return (
    <Dashboard
      events={events}
      connected={connected}
      captureRunning={captureRunning}
      captureMode={captureMode}
      onCaptureMode={setCaptureMode}
      onStartCapture={startCapture}
      onStopCapture={stopCapture}
    />
  );
}
