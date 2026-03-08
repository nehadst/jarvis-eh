import { useState, useEffect } from "react";
import { addTask, fetchFamily, triggerEncounterRecording, setHousehold, getHousehold, triggerGrounding, getSafezones, setSafezones } from "../api/client.js";

const C1 = "oklch(0.81 0.117 11.638)";
const C2 = "oklch(0.645 0.246 16.439)";
const C3 = "oklch(0.586 0.253 17.585)";
const C4 = "oklch(0.514 0.222 16.935)";
const C5 = "oklch(0.455 0.188 13.697)";
const CD = "oklch(0.704 0.191 22.216)";

const inputCls = "w-full px-3 py-2.5 text-[13px] font-sans text-foreground placeholder:text-muted-foreground outline-none focus:ring-1 focus:ring-ring transition-colors";
const inputStyle = { background: "var(--muted)", border: "1px solid var(--border)" };

const btnCls = "w-full py-2.5 text-[13px] font-medium cursor-pointer border-none transition-opacity hover:opacity-90";

export default function TaskPanel() {
  const [task, setTask] = useState("");
  const [sent, setSent] = useState(false);

  const [whoIsHome, setWhoIsHome] = useState("");
  const [householdSaved, setHouseholdSaved] = useState(false);

  const [grounding, setGrounding] = useState(false);
  const [groundingTriggered, setGroundingTriggered] = useState(false);

  const [family, setFamily] = useState([]);
  const [selectedPerson, setSelectedPerson] = useState("");
  const [recording, setRecording] = useState(false);
  const [recordingSent, setRecordingSent] = useState(false);

  const [customZones, setCustomZones] = useState([]);
  const [defaultZones, setDefaultZones] = useState([]);
  const [newZone, setNewZone] = useState("");

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
    getSafezones()
      .then((data) => {
        setCustomZones(data?.custom_zones || []);
        const all = data?.safe_zones || [];
        const custom = data?.custom_zones || [];
        setDefaultZones(all.filter((z) => !custom.includes(z)));
      })
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

  const handleRecordEncounter = async () => {
    if (!selectedPerson) return;
    setRecording(true);
    try {
      await triggerEncounterRecording(selectedPerson);
      setRecordingSent(true);
      setTimeout(() => setRecordingSent(false), 4000);
    } finally {
      setRecording(false);
    }
  };

  const handleAddZone = async () => {
    const zone = newZone.trim().toLowerCase();
    if (!zone || customZones.includes(zone)) return;
    const updated = [...customZones, zone];
    setCustomZones(updated);
    setNewZone("");
    try {
      await setSafezones(updated);
    } catch {
      setCustomZones(customZones);
    }
  };

  const handleRemoveZone = async (zone) => {
    const updated = customZones.filter((z) => z !== zone);
    setCustomZones(updated);
    try {
      await setSafezones(updated);
    } catch {
      setCustomZones(customZones);
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

      <div className="border-t border-border" />

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

      <div className="border-t border-border" />

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

      <div className="border-t border-border" />

      {/* Safe Zones */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Safe Zones</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Rooms where the patient is allowed. An alert fires when they leave all safe zones for 3 consecutive checks.
        </p>
        <div className="flex flex-wrap gap-1.5">
          {defaultZones.map((z) => (
            <span key={z} className="inline-flex items-center px-2.5 py-1 text-[11px] text-muted-foreground opacity-45" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}>
              {z}
            </span>
          ))}
          {customZones.map((z) => (
            <span key={z} className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] text-foreground" style={{ background: "var(--muted)", border: "1px solid var(--border)" }}>
              {z}
              <button
                className="bg-transparent border-none text-muted-foreground cursor-pointer text-[13px] leading-none p-0 hover:text-foreground"
                onClick={() => handleRemoveZone(z)}
                title={`Remove ${z}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-1.5">
          <input
            className={inputCls + " flex-1"}
            style={inputStyle}
            type="text"
            placeholder="Add a room (e.g. garden)"
            value={newZone}
            onChange={(e) => setNewZone(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleAddZone()}
          />
          <button
            className="px-3 py-2 text-[13px] font-medium cursor-pointer border-none transition-opacity hover:opacity-90"
            style={{ background: "var(--accent)", color: "var(--foreground)" }}
            onClick={handleAddZone}
          >
            Add
          </button>
        </div>
      </section>

      <div className="border-t border-border" />

      {/* Record Encounter */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Record Encounter</SectionLabel>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Capture a 10-second clip + 3 snapshot photos of a real encounter with a family member.
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
            <button
              className={btnCls}
              style={{
                background: `color-mix(in oklch, ${C4} 15%, transparent)`,
                color: C4,
                border: `1px solid color-mix(in oklch, ${C4} 30%, transparent)`,
              }}
              onClick={handleRecordEncounter}
              disabled={recording}
            >
              {recording ? "Starting…" : "Record Encounter"}
            </button>
            {recordingSent && <p className="text-[12px]" style={{ color: C4 }}>Recording — watch the event feed.</p>}
          </>
        )}
      </section>

      <div className="border-t border-border" />

      {/* Quick Reference */}
      <section className="flex flex-col gap-2">
        <SectionLabel>Quick Reference</SectionLabel>
        <div className="flex flex-col gap-1">
          {[
            [C2, "Face recognized"],
            [C1, "Situation grounding"],
            [C3, "Activity reminder"],
            [CD, "Wandering alert"],
            [C4, "Conversation / Voice command"],
            [C5, "Clip / Montage ready"],
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
    <p className="text-[12px] font-medium uppercase tracking-widest text-foreground">
      {children}
    </p>
  );
}
