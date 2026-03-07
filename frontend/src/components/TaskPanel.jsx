import { useState, useEffect } from "react";
import { addTask, fetchFamily, triggerMontage, setHousehold, getHousehold, triggerGrounding } from "../api/client.js";

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
  select: {
    width: "100%",
    background: "#1a1a24",
    border: "1px solid #2d2d3d",
    borderRadius: 8,
    color: "#e8e8f0",
    padding: "10px 12px",
    fontSize: 14,
    fontFamily: "inherit",
    marginBottom: 8,
  },
  tagInput: {
    width: "100%",
    background: "#1a1a24",
    border: "1px solid #2d2d3d",
    borderRadius: 8,
    color: "#e8e8f0",
    padding: "10px 12px",
    fontSize: 14,
    fontFamily: "inherit",
    marginBottom: 8,
    boxSizing: "border-box",
  },
  btnSecondary: {
    width: "100%",
    padding: "10px",
    background: "#1d4ed8",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 14,
  },
  input: {
    width: "100%",
    background: "#1a1a24",
    border: "1px solid #2d2d3d",
    borderRadius: 8,
    color: "#e8e8f0",
    padding: "10px 12px",
    fontSize: 14,
    fontFamily: "inherit",
    boxSizing: "border-box",
    marginBottom: 8,
  },
  btnGreen: {
    width: "100%",
    padding: "10px",
    background: "#15803d",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
    fontWeight: 600,
    fontSize: 14,
  },
  success: { fontSize: 13, color: "#34d399", marginTop: 4 },
  sending: { fontSize: 13, color: "#60a5fa", marginTop: 4 },
  tip: { fontSize: 12, color: "#4b5563", lineHeight: 1.5 },
};

export default function TaskPanel() {
  const [task, setTask] = useState("");
  const [sent, setSent] = useState(false);

  // Household context state
  const [whoIsHome, setWhoIsHome] = useState("");
  const [householdSaved, setHouseholdSaved] = useState(false);

  // Manual grounding state
  const [grounding, setGrounding] = useState(false);
  const [groundingTriggered, setGroundingTriggered] = useState(false);

  // Montage trigger state
  const [family, setFamily] = useState([]);
  const [selectedPerson, setSelectedPerson] = useState("");
  const [tag, setTag] = useState("");
  const [montaging, setMontaging] = useState(false);
  const [montageSent, setMontageSent] = useState(false);

  useEffect(() => {
    fetchFamily()
      .then((data) => {
        setFamily(Array.isArray(data) ? data : []);
        if (data?.length) setSelectedPerson(data[0].id || data[0].person_id || "");
      })
      .catch(() => {});
    getHousehold()
      .then((data) => setWhoIsHome(data?.who_is_home || ""))
      .catch(() => {});
  }, []);

  const handleHousehold = async () => {
    await setHousehold(whoIsHome.trim());
    setHouseholdSaved(true);
    setTimeout(() => setHouseholdSaved(false), 2000);
  };

  const handleGrounding = async () => {
    setGrounding(true);
    try {
      await triggerGrounding();
      setGroundingTriggered(true);
      setTimeout(() => setGroundingTriggered(false), 2000);
    } finally {
      setGrounding(false);
    }
  };

  const handleSubmit = async () => {
    if (!task.trim()) return;
    await addTask(task.trim());
    setSent(true);
    setTimeout(() => setSent(false), 3000);
  };

  const handleMontage = async () => {
    if (!selectedPerson) return;
    setMontaging(true);
    try {
      await triggerMontage(selectedPerson, tag.trim() || undefined);
      setMontageSent(true);
      setTimeout(() => setMontageSent(false), 4000);
    } finally {
      setMontaging(false);
    }
  };

  return (
    <div style={styles.panel}>
      {/* Who is Home */}
      <section>
        <p style={styles.heading}>Who is Home</p>
        <p style={{ ...styles.tip, marginBottom: 10 }}>
          Names of people currently home. Used in grounding messages.
        </p>
        <input
          style={styles.input}
          type="text"
          placeholder="e.g. David, Sarah"
          value={whoIsHome}
          onChange={(e) => setWhoIsHome(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleHousehold()}
        />
        <button style={styles.btn} onClick={handleHousehold}>Update</button>
        {householdSaved && <p style={styles.success}>Saved!</p>}
      </section>

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
        {sent && <p style={styles.success}>Task sent!</p>}
      </section>

      {/* Ground Now */}
      <section>
        <p style={styles.heading}>Manual Grounding</p>
        <p style={{ ...styles.tip, marginBottom: 10 }}>
          Immediately play a grounding message for the patient.
        </p>
        <button style={styles.btnGreen} onClick={handleGrounding} disabled={grounding}>
          {grounding ? "Triggering…" : "Ground Now"}
        </button>
        {groundingTriggered && <p style={styles.success}>Triggered!</p>}
      </section>

      {/* Memory Montage */}
      <section>
        <p style={styles.heading}>Memory Montage</p>
        <p style={{ ...styles.tip, marginBottom: 10 }}>
          Generate a Ken Burns-style slideshow with AI narration for a family member.
        </p>
        {family.length === 0 ? (
          <p style={styles.tip}>No family profiles found.</p>
        ) : (
          <>
            <select
              style={styles.select}
              value={selectedPerson}
              onChange={(e) => setSelectedPerson(e.target.value)}
            >
              {family.map((p) => (
                <option key={p.id || p.person_id} value={p.id || p.person_id}>
                  {p.name}
                </option>
              ))}
            </select>
            <input
              style={styles.tagInput}
              type="text"
              placeholder="Optional tag (e.g. christmas)"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
            <button style={styles.btnSecondary} onClick={handleMontage} disabled={montaging}>
              {montaging ? "Building…" : "Generate Montage"}
            </button>
            {montageSent && <p style={styles.sending}>Building — watch the event feed.</p>}
          </>
        )}
      </section>

      {/* Hints */}
      <section>
        <p style={styles.heading}>Quick Reference</p>
        <p style={styles.tip}>
          <strong style={{ color: "#818cf8" }}>Purple</strong> — Face recognized<br />
          <strong style={{ color: "#34d399" }}>Green</strong> — Situation grounding<br />
          <strong style={{ color: "#fbbf24" }}>Yellow</strong> — Activity reminder<br />
          <strong style={{ color: "#f87171" }}>Red</strong> — Wandering alert<br />
          <strong style={{ color: "#a78bfa" }}>Violet</strong> — Conversation assist<br />
          <strong style={{ color: "#60a5fa" }}>Blue</strong> — Montage ready
        </p>
      </section>
    </div>
  );
}
