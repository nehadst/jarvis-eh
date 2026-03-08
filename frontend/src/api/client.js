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
 * @param {string} personId
 * @param {string} [tag] - optional Cloudinary tag filter, e.g. "christmas"
 */
export async function triggerMontage(personId, tag) {
  const url = tag ? `/api/montage/${personId}?tag=${encodeURIComponent(tag)}` : `/api/montage/${personId}`;
  const res = await fetch(url, { method: "POST" });
  return res.json();
}

/**
 * Fetch all family profiles.
 */
export async function fetchFamily() {
  const res = await fetch("/api/family");
  return res.json();
}

/**
 * Set who is currently home (feeds into grounding messages).
 * @param {string} whoIsHome - e.g. "David, Sarah"
 */
export async function setHousehold(whoIsHome) {
  const res = await fetch("/api/household", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ who_is_home: whoIsHome }),
  });
  return res.json();
}

/**
 * Get current household context.
 */
export async function getHousehold() {
  const res = await fetch("/api/household");
  return res.json();
}

/**
 * Manually trigger an immediate grounding message.
 */
export async function triggerGrounding() {
  const res = await fetch("/api/grounding/trigger", { method: "POST" });
  return res.json();
}

/**
 * Get current safe zones (defaults merged with caregiver custom zones).
 * Returns { safe_zones: string[], custom_zones: string[] }
 */
export async function getSafezones() {
  const res = await fetch("/api/safezones");
  return res.json();
}

/**
 * Update the caregiver-defined safe zone list.
 * @param {string[]} zones - full list of custom zones to persist
 */
export async function setSafezones(zones) {
  const res = await fetch("/api/safezones", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ safe_zones: zones }),
  });
  return res.json();
}

/**
 * Remove a single safe zone by name (works for both defaults and custom zones).
 * @param {string} zone
 */
export async function removeSafezone(zone) {
  const res = await fetch(`/api/safezones/${encodeURIComponent(zone)}`, { method: "DELETE" });
  return res.json();
}

/** Get the current caregiver situational context. */
export async function getContext() {
  const res = await fetch("/api/context");
  return res.json();
}

/**
 * Set situational context describing where the patient is supposed to be.
 * Pass an empty string to clear.
 * @param {string} description
 */
export async function setContext(description) {
  const res = await fetch("/api/context", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description }),
  });
  return res.json();
}

/**
 * Create or update a family member profile.
 */
export async function saveFamily(personId, profile) {
  const res = await fetch(`/api/family/${personId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
  return res.json();
}

/**
 * Upload face photos for a family member.
 * @param {string} personId
 * @param {FileList|File[]} files
 */
export async function uploadFacePhotos(personId, files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await fetch(`/api/family/${personId}/photos`, {
    method: "POST",
    body: form,
  });
  return res.json();
}

/**
 * Delete a family member and their photos.
 */
export async function deleteFamily(personId) {
  const res = await fetch(`/api/family/${personId}`, { method: "DELETE" });
  return res.json();
}
