import { useState, useEffect } from "react";
import { addTask, fetchFamily, triggerMontage, setHousehold, getHousehold, triggerGrounding } from "../api/client.js";

const C1 = "oklch(0.81 0.117 11.638)";
const C2 = "oklch(0.645 0.246 16.439)";
const C3 = "oklch(0.586 0.253 17.585)";
const C4 = "oklch(0.514 0.222 16.935)";
const C5 = "oklch(0.455 0.188 13.697)";
const CD = "oklch(0.704 0.191 22.216)";

const inputCls = "w-full px-3 py-2.5 text-[13px] font-sans text-foreground placeholder:text-muted-foreground outline-none focus:ring-1 focus:ring-ring transition-colors";
const inputStyle = { background: "var(--muted)", border: "1px solid var(--border)" };

const btnCls = "w-full py-2.5 text-[13px] font-semibold cursor-pointer border-none transition-opacity hover:opacity-90";

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
        {householdSaved && <p className="text-[12px]" style={{ color: C2 }}>Saved!</p>}
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
        {sent && <p className="text-[12px]" style={{ color: C2 }}>Task sent!</p>}
      </section>

      {/* Manual Grounding */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Manual Grounding</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Immediately play a grounding message for the patient.
        </p>
        <button
          className={btnCls}
          style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
          onClick={handleGrounding}
          disabled={grounding}
        >
          {grounding ? "Triggering…" : "Ground Now"}
        </button>
        {groundingTriggered && <p className="text-[12px]" style={{ color: C2 }}>Triggered!</p>}
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
              style={{
                background: `color-mix(in oklch, ${C5} 15%, transparent)`,
                color: C5,
                border: `1px solid color-mix(in oklch, ${C5} 30%, transparent)`,
              }}
              onClick={handleMontage}
              disabled={montaging}
            >
              {montaging ? "Building…" : "Generate Montage"}
            </button>
            {montageSent && <p className="text-[12px]" style={{ color: C5 }}>Building — watch the event feed.</p>}
          </>
        )}
      </section>

      {/* Quick Reference */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Quick Reference</SectionLabel>
        <div className="flex flex-col gap-1">
          {[
            [C2, "Face recognized"],
            [C1, "Situation grounding"],
            [C3, "Activity reminder"],
            [CD, "Wandering alert"],
            [C4, "Conversation assist"],
            [C5, "Montage ready"],
            [C1, "Check-in"],
            [C3, "Task reminder"],
            [C2, "Task complete"],
          ].map(([color, label]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="w-2 h-2 flex-shrink-0" style={{ background: color }} />
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
    <p className="text-[12px] font-bold uppercase tracking-widest text-foreground">
      {children}
    </p>
  );
}
