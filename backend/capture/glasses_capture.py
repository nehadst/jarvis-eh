"""
Meta Glasses frame capture — receives H.264 frames over WebSocket from the iOS app.

The iOS CameraAccess app connects to ws://<laptop-ip>:8765 and sends
each encoded H.264 access unit (Annex B format) as a binary WebSocket message.
Frames are hardware-encoded on the iPhone via VideoToolbox.

Usage:
    from capture.glasses_capture import GlassesCapture

    cap = GlassesCapture(host="0.0.0.0", port=8765)
    for frame in cap.frames():   # generator, blocks until cap.stop()
        process(frame)
"""

import asyncio
import threading
from queue import Queue, Empty

import av
import cv2
import numpy as np
import websockets
import websockets.server


class GlassesCapture:
    """
    WebSocket server that receives H.264-encoded frames from the Meta glasses iOS app.
    Decodes using PyAV (hardware-accelerated ffmpeg) and exposes the same interface
    as FrameCapture so the Orchestrator can use either one interchangeably.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8765, max_queue: int = 5) -> None:
        self.host = host
        self.port = port
        self._frame_queue: Queue[np.ndarray] = Queue(maxsize=max_queue)
        self._running = False
        self._server_thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Latest decoded frame for the video stream
        self._latest_frame: np.ndarray | None = None
        self._frame_lock = threading.Lock()
        self._new_frame_event = threading.Event()
        self.frame_id: int = 0

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
        # Fresh H.264 decoder per connection (clean state for first keyframe)
        codec = av.CodecContext.create("h264", "r")
        try:
            async for message in websocket:
                if not self._running:
                    break
                if isinstance(message, bytes):
                    # Decode H.264 Annex B data -> BGR numpy frames
                    try:
                        packet = av.Packet(message)
                        frames = codec.decode(packet)
                    except av.error.InvalidDataError:
                        continue

                    for frame in frames:
                        bgr = frame.to_ndarray(format="bgr24")

                        # Store latest frame for the video stream
                        with self._frame_lock:
                            self._latest_frame = bgr
                            self.frame_id += 1
                        self._new_frame_event.set()

                        # Queue for AI processing (drop oldest if full)
                        if self._frame_queue.full():
                            try:
                                self._frame_queue.get_nowait()
                            except Empty:
                                pass
                        self._frame_queue.put(bgr)
        except websockets.exceptions.ConnectionClosed:
            print("[GlassesCapture] iOS app disconnected.")

    def get_latest_frame(self) -> np.ndarray | None:
        """Return the latest decoded frame as a BGR numpy array (thread-safe)."""
        with self._frame_lock:
            return self._latest_frame

    def wait_for_frame(self, timeout: float = 0.1) -> bool:
        """Block until a new frame arrives. Returns True if a frame is ready."""
        result = self._new_frame_event.wait(timeout=timeout)
        self._new_frame_event.clear()
        return result

    def grab_once(self) -> np.ndarray | None:
        """Grab a single frame from the queue (non-blocking)."""
        try:
            return self._frame_queue.get_nowait()
        except Empty:
            return None

    def frames(self):
        """
        Generator that yields BGR frames as they arrive from the glasses.
        Same interface as FrameCapture.frames().
        """
        self._running = True
        self._server_thread = threading.Thread(target=self._start_server, daemon=True)
        self._server_thread.start()

        while self._running:
            try:
                frame = self._frame_queue.get(timeout=0.5)
                yield frame
            except Empty:
                continue

    def stop(self) -> None:
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
