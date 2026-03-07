const WS_URL = "ws://localhost:8000/ws";

/**
 * Opens a WebSocket to the backend and calls handlers for open/close/events.
 * Returns the WebSocket instance so the caller can close it on cleanup.
 */
export function connectWebSocket({ onOpen, onClose, onEvent }) {
  const ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    console.log("[WS] Connected to REWIND backend");
    onOpen?.();
  };

  ws.onclose = () => {
    console.log("[WS] Disconnected");
    onClose?.();
  };

  ws.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      onEvent?.(event);
    } catch {
      // ignore malformed messages
    }
  };

  return ws;
}

/**
 * Add a caregiver task for the patient.
 * @param {string} task - e.g. "Go to the fridge and grab an orange"
 */
export async function addTask(task, setBy = "caregiver") {
  const res = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task, set_by: setBy }),
  });
  return res.json();
}

/**
 * Trigger a memory montage for a family member.
 */
export async function triggerMontage(personId) {
  const res = await fetch(`/api/montage/${personId}`, { method: "POST" });
  return res.json();
}

/**
 * Fetch all family profiles.
 */
export async function fetchFamily() {
  const res = await fetch("/api/family");
  return res.json();
}
