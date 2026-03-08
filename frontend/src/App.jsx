import { useState, useEffect } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Dashboard from "./components/Dashboard.jsx";
import GlassesView from "./components/GlassesView.jsx";
import { connectWebSocket } from "./api/client.js";

export default function App() {
  const [events, setEvents] = useState([]);
  const [connected, setConnected] = useState(false);
  const [captureRunning, setCaptureRunning] = useState(false);
  const [captureMode, setCaptureMode] = useState("glasses");
  const [webcamIndex, setWebcamIndex] = useState(0);

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
      body: JSON.stringify({ mode, webcam_index: webcamIndex }),
    });
    setCaptureRunning(true);
  };

  const stopCapture = async () => {
    await fetch("/api/capture/stop", { method: "POST" });
    setCaptureRunning(false);
  };

  const sharedProps = {
    events,
    connected,
    captureRunning,
    captureMode,
    webcamIndex,
    onCaptureMode: setCaptureMode,
    onWebcamIndex: setWebcamIndex,
    onStartCapture: startCapture,
    onStopCapture: stopCapture,
  };

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard {...sharedProps} />} />
        <Route path="/glasses" element={<GlassesView {...sharedProps} />} />
      </Routes>
    </BrowserRouter>
  );
}
