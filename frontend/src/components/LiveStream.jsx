import { useEffect, useRef } from "react";

const WS_STREAM_URL = "ws://localhost:8000/ws/stream";

export default function LiveStream({ captureRunning }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    if (!captureRunning) return;

    let ws;
    let rafId;
    let latestBlob = null;
    let stopped = false;

    function connect() {
      if (stopped) return;

      ws = new WebSocket(WS_STREAM_URL);
      ws.binaryType = "arraybuffer";

      ws.onmessage = (event) => {
        latestBlob = new Blob([event.data], { type: "image/jpeg" });
      };

      ws.onclose = () => {
        if (!stopped) setTimeout(connect, 1000); // reconnect after 1s
      };
    }

    // Render loop — synced to display refresh, only draws latest frame
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
        } catch (e) {}
      }

      rafId = requestAnimationFrame(renderLoop);
    };

    connect();
    rafId = requestAnimationFrame(renderLoop);

    return () => {
      stopped = true;
      if (rafId) cancelAnimationFrame(rafId);
      if (ws) ws.close();
    };
  }, [captureRunning]);

  if (!captureRunning) {
    return (
      <div className="flex items-center justify-center h-full" style={{ background: "oklch(0.08 0 0)" }}>
        <span className="text-[15px] text-muted-foreground">Start capture to see live feed</span>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center bg-black overflow-hidden h-full">
      <canvas ref={canvasRef} className="max-w-full max-h-full object-contain" />
    </div>
  );
}
