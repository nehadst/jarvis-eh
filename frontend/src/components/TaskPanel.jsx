import { useState, useEffect } from "react";
import { addTask, fetchFamily, triggerMontage, setHousehold, getHousehold, triggerGrounding } from "../api/client.js";

const inputCls = "w-full px-3 py-2.5 rounded-lg text-[13px] font-sans text-foreground placeholder:text-muted-foreground outline-none focus:ring-1 focus:ring-ring transition-colors";
const inputStyle = { background: "var(--muted)", border: "1px solid var(--border)" };

const btnCls = "w-full py-2.5 rounded-lg text-[13px] font-semibold cursor-pointer border-none transition-opacity hover:opacity-90";

export default function TaskPanel() {
  const [task, setTask] = useState("");
  const [sent, setSent] = useState(false);

  const [whoIsHome, setWhoIsHome] = useState("");
  const [householdSaved, setHouseholdSaved] = useState(false);

  const [grounding, setGrounding] = useState(false);
  const [groundingTriggered, setGroundingTriggered] = useState(false);

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
    <div
      className="flex flex-col gap-5 p-4 overflow-y-auto"
      style={{ borderTop: "1px solid var(--border)", background: "var(--background)" }}
    >
      {/* Who is Home */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Who is Home</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Names of people currently home. Used in grounding messages.
        </p>
        <input
          className={inputCls}
          style={inputStyle}
          type="text"
          placeholder="e.g. David, Sarah"
          value={whoIsHome}
          onChange={(e) => setWhoIsHome(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleHousehold()}
        />
        <button
          className={btnCls}
          style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
          onClick={handleHousehold}
        >
          Update
        </button>
        {householdSaved && <p className="text-[12px] text-green-400">Saved!</p>}
      </section>

      {/* Caregiver Task */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Set Patient Task</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Tell the patient what they should be doing right now.
        </p>
        <textarea
          className={inputCls}
          style={{ ...inputStyle, minHeight: 72, resize: "vertical" }}
          placeholder="e.g. Go to the fridge and grab an orange"
          value={task}
          onChange={(e) => setTask(e.target.value)}
        />
        <button
          className={btnCls}
          style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
          onClick={handleSubmit}
        >
          Send to Patient
        </button>
        {sent && <p className="text-[12px] text-green-400">Task sent!</p>}
      </section>

      {/* Manual Grounding */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Manual Grounding</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Immediately play a grounding message for the patient.
        </p>
        <button
          className={btnCls}
          style={{ background: "oklch(0.45 0.15 145)", color: "#fff" }}
          onClick={handleGrounding}
          disabled={grounding}
        >
          {grounding ? "Triggering…" : "Ground Now"}
        </button>
        {groundingTriggered && <p className="text-[12px] text-green-400">Triggered!</p>}
      </section>

      {/* Memory Montage */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Memory Montage</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Generate a Ken Burns-style slideshow with AI narration.
        </p>
        {family.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">No family profiles found.</p>
        ) : (
          <>
            <select
              className={inputCls}
              style={{ ...inputStyle, marginBottom: 0 }}
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
              className={inputCls}
              style={inputStyle}
              type="text"
              placeholder="Optional tag (e.g. christmas)"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
            />
            <button
              className={btnCls}
              style={{ background: "rgba(96,165,250,0.15)", color: "#60a5fa", border: "1px solid rgba(96,165,250,0.25)" }}
              onClick={handleMontage}
              disabled={montaging}
            >
              {montaging ? "Building…" : "Generate Montage"}
            </button>
            {montageSent && <p className="text-[12px]" style={{ color: "#60a5fa" }}>Building — watch the event feed.</p>}
          </>
        )}
      </section>

      {/* Quick Reference */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Quick Reference</SectionLabel>
        <div className="flex flex-col gap-1">
          {[
            ["#818cf8", "Face recognized"],
            ["#34d399", "Situation grounding"],
            ["#fbbf24", "Activity reminder"],
            ["#f87171", "Wandering alert"],
            ["#a78bfa", "Conversation assist"],
            ["#60a5fa", "Montage ready"],
          ].map(([color, label]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color }} />
              <span className="text-[11px] text-muted-foreground">{label}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <p className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
      {children}
    </p>
  );
}
