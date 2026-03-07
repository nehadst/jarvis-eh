import { useState, useEffect } from "react";
import Dashboard from "./components/Dashboard.jsx";
import { connectWebSocket } from "./api/client.js";

export default function App() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [captureRunning, setCaptureRunning] = useState(false);

  useEffect(() => {
    const ws = connectWebSocket({
      onOpen: () => setConnected(true),
      onClose: () => setConnected(false),
      onEvent: (event) => setEvents((prev) => [event, ...prev].slice(0, 100)),
    });
    return () => ws.close();
  }, []);

  const startCapture = async () => {
    await fetch("/api/capture/start", { method: "POST" });
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
      onStartCapture={startCapture}
      onStopCapture={stopCapture}
    />
  );
}
