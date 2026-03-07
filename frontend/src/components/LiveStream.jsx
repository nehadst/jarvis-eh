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
      <div style={styles.placeholder}>
        <span style={styles.placeholderText}>Start capture to see live feed</span>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <canvas ref={canvasRef} style={styles.canvas} />
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#000",
    overflow: "hidden",
    height: "100%",
  },
  canvas: {
    maxWidth: "100%",
    maxHeight: "100%",
    objectFit: "contain",
  },
  placeholder: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    background: "#0a0a0f",
    height: "100%",
  },
  placeholderText: {
    color: "#555",
    fontSize: 16,
  },
};
