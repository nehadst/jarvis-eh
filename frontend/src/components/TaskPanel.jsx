import { useState } from "react";
import { addTask } from "../api/client.js";

const styles = {
  panel: {
    borderLeft: "1px solid #1e1e2e",
    background: "#13131a",
    padding: 20,
    display: "flex",
    flexDirection: "column",
    gap: 20,
    overflowY: "auto",
  },
  heading: { fontSize: 14, fontWeight: 700, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.08em" },
  textarea: {
    width: "100%",
    background: "#1a1a24",
    border: "1px solid #2d2d3d",
    borderRadius: 8,
    color: "#e8e8f0",
    padding: "10px 12px",
    fontSize: 14,
    resize: "vertical",
    minHeight: 80,
    fontFamily: "inherit",
  },
  btn: {
    width: "100%",
    padding: "10px",
    background: "#4f46e5",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 14,
  },
  success: { fontSize: 13, color: "#34d399", marginTop: 4 },
  tip: { fontSize: 12, color: "#4b5563", lineHeight: 1.5 },
};

export default function TaskPanel() {
  const [task, setTask] = useState("");
  const [sent, setSent] = useState(false);

  const handleSubmit = async () => {
    if (!task.trim()) return;
    await addTask(task.trim());
    setSent(true);
    setTimeout(() => setSent(false), 3000);
  };

  return (
    <div style={styles.panel}>
      {/* Caregiver Task */}
      <section>
        <p style={styles.heading}>Set Patient Task</p>
        <p style={{ ...styles.tip, marginBottom: 10 }}>
          Tell the patient what they should be doing right now. The AI will
          include this in grounding messages.
        </p>
        <textarea
          style={styles.textarea}
          placeholder="e.g. Go to the fridge and grab an orange"
          value={task}
          onChange={(e) => setTask(e.target.value)}
        />
        <button style={styles.btn} onClick={handleSubmit}>
          Send to Patient
        </button>
        {sent && <p style={styles.success}>✓ Task sent!</p>}
      </section>

      {/* Hints */}
      <section>
        <p style={styles.heading}>Quick Reference</p>
        <p style={styles.tip}>
          <strong style={{ color: "#818cf8" }}>Purple</strong> — Face recognized<br />
          <strong style={{ color: "#34d399" }}>Green</strong> — Situation grounding<br />
          <strong style={{ color: "#fbbf24" }}>Yellow</strong> — Activity reminder<br />
          <strong style={{ color: "#f87171" }}>Red</strong> — Wandering alert<br />
          <strong style={{ color: "#a78bfa" }}>Violet</strong> — Conversation assist
        </p>
      </section>
    </div>
  );
}
