import { useState, useEffect } from "react";
import { fetchFamily, saveFamily, uploadFacePhotos, deleteFamily } from "../api/client.js";

const C2 = "oklch(0.645 0.246 16.439)";

const inputCls = "w-full px-3 py-2 text-[13px] font-sans text-foreground placeholder:text-muted-foreground outline-none focus:ring-1 focus:ring-ring transition-colors";
const inputStyle = { background: "var(--muted)", border: "1px solid var(--border)", boxSizing: "border-box" };

export default function FamilySetup() {
  const [members, setMembers] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", relationship: "", personal_detail: "", notes: "" });
  const [files, setFiles] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const loadMembers = async () => {
    try {
      const data = await fetchFamily();
      setMembers(Array.isArray(data) ? data : []);
    } catch { setMembers([]); }
  };

  useEffect(() => { loadMembers(); }, []);

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.relationship.trim()) return;
    setSaving(true);
    setMessage("");

    const personId = form.name.trim().toLowerCase().replace(/\s+/g, "_");
    const profile = {
      id: personId,
      name: form.name.trim(),
      relationship: form.relationship.trim(),
      personal_detail: form.personal_detail.trim(),
      notes: form.notes.trim() ? form.notes.trim().split("\n").filter(Boolean) : [],
      last_interaction: { date: "", summary: "" },
      calming_anchors: [],
    };

    try {
      await saveFamily(personId, profile);
      if (files && files.length > 0) {
        await uploadFacePhotos(personId, files);
      }
      setMessage(`Added ${profile.name}`);
      setForm({ name: "", relationship: "", personal_detail: "", notes: "" });
      setFiles(null);
      setShowForm(false);
      loadMembers();
    } catch (e) {
      setMessage("Error saving — check console");
      console.error(e);
    }
    setSaving(false);
  };

  const handleDelete = async (personId, name) => {
    if (!confirm(`Remove ${name}?`)) return;
    await deleteFamily(personId);
    loadMembers();
  };

  return (
    <div className="p-6 flex flex-col gap-4 max-w-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-bold uppercase tracking-widest text-muted-foreground">
          Family Members
        </p>
        <button
          className="px-3.5 py-1.5 text-[12px] font-semibold cursor-pointer border-none transition-opacity hover:opacity-90"
          style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? "Cancel" : "+ Add Member"}
        </button>
      </div>

      {/* Add form */}
      {showForm && (
        <div
          className="flex flex-col gap-3 p-4"
          style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        >
          <input className={inputCls} style={inputStyle} placeholder="Name (e.g. Sarah Johnson)" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input className={inputCls} style={inputStyle} placeholder="Relationship (e.g. granddaughter)" value={form.relationship}
            onChange={(e) => setForm({ ...form, relationship: e.target.value })} />
          <input className={inputCls} style={inputStyle} placeholder="Personal detail (e.g. just started nursing)" value={form.personal_detail}
            onChange={(e) => setForm({ ...form, personal_detail: e.target.value })} />
          <textarea
            className={inputCls}
            style={{ ...inputStyle, minHeight: 64, resize: "vertical" }}
            placeholder="Notes (one per line)"
            value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })}
          />
          <label className="flex items-center gap-2 text-[12px] font-semibold text-muted-foreground cursor-pointer">
            Face Photos
            <input type="file" accept="image/*" multiple className="text-[12px]"
              onChange={(e) => setFiles(e.target.files)} />
          </label>
          {files && <p className="text-[11px] text-muted-foreground">{files.length} photo(s) selected</p>}
          <button
            className="w-full py-2.5 text-[13px] font-semibold cursor-pointer border-none transition-opacity hover:opacity-90"
            style={{ background: "var(--primary)", color: "var(--primary-foreground)" }}
            onClick={handleSubmit}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save & Upload Photos"}
          </button>
          {message && <p className="text-[12px]" style={{ color: C2 }}>{message}</p>}
        </div>
      )}

      {/* Empty state */}
      {members.length === 0 && !showForm && (
        <p className="text-[13px] text-muted-foreground">
          No family members yet. Add someone to get started.
        </p>
      )}

      {/* Member cards */}
      {members.map((m) => (
        <div
          key={m.id}
          className="px-4 py-3.5 flex flex-col gap-1"
          style={{ background: "var(--card)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-baseline gap-1.5">
              <span className="text-[14px] font-semibold text-foreground">{m.name}</span>
              <span className="text-[13px]" style={{ color: "var(--primary)" }}>— {m.relationship}</span>
            </div>
            <button
              className="px-2.5 py-1 text-[11px] font-semibold cursor-pointer border-none transition-opacity hover:opacity-80"
              style={{
                background: "color-mix(in oklch, var(--destructive) 12%, transparent)",
                color: "var(--destructive)",
                border: "1px solid color-mix(in oklch, var(--destructive) 25%, transparent)",
              }}
              onClick={() => handleDelete(m.id, m.name)}
            >
              Remove
            </button>
          </div>
          {m.personal_detail && (
            <p className="text-[12px] text-muted-foreground">{m.personal_detail}</p>
          )}
          {m.last_interaction?.summary && (
            <p className="text-[12px] text-muted-foreground">Last: {m.last_interaction.summary}</p>
          )}
        </div>
      ))}
    </div>
  );
}
