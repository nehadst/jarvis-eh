import { useState, useEffect } from "react";
import { fetchFamily, saveFamily, uploadFacePhotos, deleteFamily } from "../api/client.js";

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
    <div style={styles.container}>
      <div style={styles.headerRow}>
        <p style={styles.heading}>Family Members</p>
        <button style={styles.addBtn} onClick={() => setShowForm(!showForm)}>
          {showForm ? "Cancel" : "+ Add"}
        </button>
      </div>

      {showForm && (
        <div style={styles.form}>
          <input style={styles.input} placeholder="Name (e.g. Sarah Johnson)" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input style={styles.input} placeholder="Relationship (e.g. granddaughter)" value={form.relationship}
            onChange={(e) => setForm({ ...form, relationship: e.target.value })} />
          <input style={styles.input} placeholder="Personal detail (e.g. just started nursing)" value={form.personal_detail}
            onChange={(e) => setForm({ ...form, personal_detail: e.target.value })} />
          <textarea style={styles.textarea} placeholder="Notes (one per line)" value={form.notes}
            onChange={(e) => setForm({ ...form, notes: e.target.value })} />

          <label style={styles.fileLabel}>
            Face Photos
            <input type="file" accept="image/*" multiple style={styles.fileInput}
              onChange={(e) => setFiles(e.target.files)} />
          </label>
          {files && <p style={styles.hint}>{files.length} photo(s) selected</p>}

          <button style={styles.saveBtn} onClick={handleSubmit} disabled={saving}>
            {saving ? "Saving..." : "Save & Upload Photos"}
          </button>
          {message && <p style={styles.msg}>{message}</p>}
        </div>
      )}

      {members.length === 0 && !showForm && (
        <p style={styles.hint}>No family members yet. Add someone to get started.</p>
      )}

      {members.map((m) => (
        <div key={m.id} style={styles.card}>
          <div style={styles.cardRow}>
            <div>
              <span style={styles.name}>{m.name}</span>
              <span style={styles.rel}> — {m.relationship}</span>
            </div>
            <button style={styles.delBtn} onClick={() => handleDelete(m.id, m.name)}>Remove</button>
          </div>
          {m.personal_detail && <p style={styles.detail}>{m.personal_detail}</p>}
          {m.last_interaction?.summary && (
            <p style={styles.detail}>Last: {m.last_interaction.summary}</p>
          )}
        </div>
      ))}
    </div>
  );
}

const styles = {
  container: { padding: 20, display: "flex", flexDirection: "column", gap: 12 },
  headerRow: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  heading: { fontSize: 14, fontWeight: 700, color: "#9ca3af", textTransform: "uppercase", letterSpacing: "0.08em", margin: 0 },
  addBtn: { padding: "6px 14px", background: "#4f46e5", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer", fontWeight: 600, fontSize: 13 },
  form: { display: "flex", flexDirection: "column", gap: 10, background: "#1a1a24", borderRadius: 10, padding: 16, border: "1px solid #2d2d3d" },
  input: { width: "100%", padding: "8px 12px", background: "#13131a", border: "1px solid #2d2d3d", borderRadius: 6, color: "#e8e8f0", fontSize: 14, fontFamily: "inherit", boxSizing: "border-box" },
  textarea: { width: "100%", padding: "8px 12px", background: "#13131a", border: "1px solid #2d2d3d", borderRadius: 6, color: "#e8e8f0", fontSize: 14, fontFamily: "inherit", minHeight: 60, resize: "vertical", boxSizing: "border-box" },
  fileLabel: { fontSize: 13, color: "#9ca3af", fontWeight: 600, cursor: "pointer" },
  fileInput: { marginLeft: 10, fontSize: 13 },
  saveBtn: { padding: "10px", background: "#16a34a", color: "#fff", border: "none", borderRadius: 8, cursor: "pointer", fontWeight: 600, fontSize: 14 },
  msg: { fontSize: 13, color: "#34d399", margin: 0 },
  hint: { fontSize: 13, color: "#4b5563", margin: 0 },
  card: { background: "#1a1a24", border: "1px solid #2d2d3d", borderRadius: 10, padding: "12px 16px" },
  cardRow: { display: "flex", justifyContent: "space-between", alignItems: "center" },
  name: { fontWeight: 700, fontSize: 15, color: "#e8e8f0" },
  rel: { fontSize: 14, color: "#818cf8" },
  detail: { fontSize: 13, color: "#6b7280", margin: "4px 0 0" },
  delBtn: { padding: "4px 10px", background: "#450a0a", color: "#fca5a5", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 12, fontWeight: 600 },
};
