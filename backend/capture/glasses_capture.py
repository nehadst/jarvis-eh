"""
Meta Glasses frame capture — receives JPEG frames over WebSocket from the iOS app.

Usage:
    from capture.glasses_capture import GlassesCapture

    cap = GlassesCapture(host="0.0.0.0", port=8765)
    for frame in cap.frames():   # generator, blocks until cap.stop()
        process(frame)

The iOS CameraAccess app connects to ws://<laptop-ip>:8765 and sends
each VideoFrame as raw JPEG bytes in a binary WebSocket message.
"""

import asyncio
import threading
from queue import Queue, Empty

import cv2
import numpy as np
import websockets
import websockets.server


class GlassesCapture:
    """
    WebSocket server that receives JPEG frames from the Meta glasses iOS app.
    Exposes the same interface as FrameCapture so the Orchestrator can use
    either one interchangeably.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, max_queue: int = 5) -> None:
        self.host = host
        self.port = port
        self._jpeg_queue: Queue[bytes] = Queue(maxsize=max_queue)
        self._running = False
        self._server_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Raw JPEG bytes from iOS — served directly to MJPEG stream (no re-encoding)
        self._latest_jpeg: bytes | None = None
        self._jpeg_lock = threading.Lock()
        self._new_frame_event = threading.Event()
        self.jpeg_id: int = 0

    def _start_server(self) -> None:
        """Run the WebSocket server in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self) -> None:
        async with websockets.serve(self._handler, self.host, self.port):
            print(f"[GlassesCapture] WebSocket server listening on ws://{self.host}:{self.port}")
            while self._running:
                await asyncio.sleep(0.1)

    async def _handler(self, websocket: websockets.server.ServerConnection) -> None:
        print(f"[GlassesCapture] iOS app connected from {websocket.remote_address}")
        try:
            async for message in websocket:
                if not self._running:
                    break
                if isinstance(message, bytes):
                    # Store raw JPEG for the MJPEG stream (zero CPU work)
                    with self._jpeg_lock:
                        self._latest_jpeg = message
                        self.jpeg_id += 1
                    self._new_frame_event.set()
                    # Queue raw JPEG bytes — decoding happens on the consumer thread
                    if self._jpeg_queue.full():
                        try:
                            self._jpeg_queue.get_nowait()
                        except Empty:
                            pass
                    self._jpeg_queue.put(message)
        except websockets.exceptions.ConnectionClosed:
            print("[GlassesCapture] iOS app disconnected.")

    def get_latest_jpeg(self) -> bytes | None:
        """Return raw JPEG bytes from the iOS app (no re-encoding needed)."""
        with self._jpeg_lock:
            return self._latest_jpeg

    def wait_for_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new frame arrives. Returns True if a frame is ready."""
        result = self._new_frame_event.wait(timeout=timeout)
        self._new_frame_event.clear()
        return result

    def grab_once(self) -> np.ndarray | None:
        """Grab a single frame from the queue (non-blocking)."""
        try:
            jpeg_bytes = self._jpeg_queue.get_nowait()
            arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Empty:
            return None

    def frames(self):
        """
        Generator that yields BGR frames as they arrive from the glasses.
        Same interface as FrameCapture.frames().
        Decodes JPEG → numpy here (on the consumer thread, not the async handler).
        """
        self._running = True
        self._server_thread = threading.Thread(target=self._start_server, daemon=True)
        self._server_thread.start()

        while self._running:
            try:
                jpeg_bytes = self._jpeg_queue.get(timeout=0.5)
                arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    yield frame
            except Empty:
                continue

    def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
