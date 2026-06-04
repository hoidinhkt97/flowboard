import { useState } from "react";
import { useAuthStore } from "../../store/auth";

interface RegisterPageProps {
  onGoLogin: () => void;
}

function getPasswordStrength(pw: string): { level: number; label: string; color: string } {
  if (pw.length === 0) return { level: 0, label: "", color: "#4a4455" };
  if (pw.length < 6) return { level: 1, label: "Weak", color: "#ffb4ab" };
  if (pw.length < 10) return { level: 2, label: "Fair", color: "#ffd166" };
  if (/[A-Z]/.test(pw) && /[0-9]/.test(pw)) return { level: 4, label: "Strong", color: "#4cd7f6" };
  return { level: 3, label: "Good", color: "#a8e6cf" };
}

export function RegisterPage({ onGoLogin }: RegisterPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [showPw, setShowPw] = useState(false);
  const { register, loading, error, clearError } = useAuthStore();

  const strength = getPasswordStrength(password);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (mismatch || !agreed) return;
    await register(email, password);
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.logoRow}>
          <div style={styles.logoIcon}>F</div>
          <span style={styles.logoText}>Flowboard</span>
        </div>
        <h1 style={styles.heading}>Create your account</h1>
        <p style={styles.sub}>Start generating cinematic AI videos today.</p>

        {error && (
          <div style={styles.errorBanner} onClick={clearError}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.field}>
            <span style={styles.fieldIcon}>✉</span>
            <input
              type="email"
              placeholder="Email address"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              style={styles.input}
              autoComplete="email"
            />
          </div>

          <div>
            <div style={styles.field}>
              <span style={styles.fieldIcon}>🔒</span>
              <input
                type={showPw ? "text" : "password"}
                placeholder="Password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                required
                style={styles.input}
                autoComplete="new-password"
              />
              <button type="button" onClick={() => setShowPw(v => !v)} style={styles.eyeBtn}>
                {showPw ? "🙈" : "👁"}
              </button>
            </div>
            {password.length > 0 && (
              <div style={styles.strengthRow}>
                {[1, 2, 3, 4].map(i => (
                  <div
                    key={i}
                    style={{
                      ...styles.strengthBar,
                      background: i <= strength.level ? strength.color : "#4a4455",
                    }}
                  />
                ))}
                <span style={{ ...styles.strengthLabel, color: strength.color }}>
                  {strength.label}
                </span>
              </div>
            )}
          </div>

          <div style={styles.field}>
            <span style={styles.fieldIcon}>🔑</span>
            <input
              type={showPw ? "text" : "password"}
              placeholder="Confirm password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              required
              style={{
                ...styles.input,
                borderColor: mismatch ? "#ffb4ab" : "#4a4455",
              }}
              autoComplete="new-password"
            />
          </div>
          {mismatch && <p style={styles.fieldError}>Passwords do not match</p>}

          <label style={styles.checkRow}>
            <input
              type="checkbox"
              checked={agreed}
              onChange={e => setAgreed(e.target.checked)}
              style={styles.checkbox}
            />
            <span style={styles.checkLabel}>
              I agree to the{" "}
              <span style={styles.termsLink}>Terms of Service</span> and{" "}
              <span style={styles.termsLink}>Privacy Policy</span>
            </span>
          </label>

          <button
            type="submit"
            disabled={loading || mismatch || !agreed}
            style={{
              ...styles.primaryBtn,
              ...(loading || mismatch || !agreed ? styles.btnDisabled : {}),
            }}
          >
            {loading ? "Creating account…" : "Create account →"}
          </button>
        </form>

        <p style={styles.switchText}>
          Already have an account?{" "}
          <button onClick={onGoLogin} style={styles.linkBtn}>
            Sign in
          </button>
        </p>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    minHeight: "100vh",
    background: "linear-gradient(135deg, #060e20 0%, #0b1326 50%, #111827 100%)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    padding: "20px",
    fontFamily: "Geist, system-ui, sans-serif",
  },
  card: {
    background: "rgba(23,31,51,0.85)",
    backdropFilter: "blur(16px)",
    border: "1px solid #4a4455",
    borderRadius: "12px",
    padding: "40px 48px",
    width: "100%",
    maxWidth: "420px",
    boxShadow: "0 10px 40px rgba(0,0,0,0.5)",
  },
  logoRow: { display: "flex", alignItems: "center", gap: "10px", marginBottom: "24px" },
  logoIcon: {
    width: "36px", height: "36px", borderRadius: "8px",
    background: "linear-gradient(135deg, #7c3aed, #4cd7f6)",
    display: "flex", alignItems: "center", justifyContent: "center",
    color: "#fff", fontWeight: 700, fontSize: "18px",
  },
  logoText: { color: "#dae2fd", fontWeight: 600, fontSize: "18px" },
  heading: { color: "#dae2fd", fontSize: "28px", fontWeight: 700, margin: "0 0 8px" },
  sub: { color: "#ccc3d8", fontSize: "14px", margin: "0 0 28px" },
  errorBanner: {
    background: "rgba(147,0,10,0.3)", border: "1px solid #ffb4ab",
    color: "#ffb4ab", borderRadius: "6px", padding: "10px 14px",
    fontSize: "13px", marginBottom: "16px", cursor: "pointer",
  },
  form: { display: "flex", flexDirection: "column", gap: "14px" },
  field: { position: "relative", display: "flex", alignItems: "center" },
  fieldIcon: { position: "absolute", left: "12px", fontSize: "14px", pointerEvents: "none", zIndex: 1 },
  input: {
    width: "100%", background: "#131b2e", border: "1px solid #4a4455",
    borderRadius: "8px", color: "#dae2fd", fontSize: "14px",
    padding: "11px 40px 11px 36px", outline: "none", boxSizing: "border-box",
  },
  eyeBtn: { position: "absolute", right: "10px", background: "none", border: "none", cursor: "pointer", fontSize: "16px", padding: "4px", lineHeight: 1 },
  strengthRow: { display: "flex", alignItems: "center", gap: "4px", marginTop: "6px", paddingLeft: "2px" },
  strengthBar: { height: "3px", flex: 1, borderRadius: "2px", transition: "background 0.2s" },
  strengthLabel: { fontSize: "11px", marginLeft: "4px", minWidth: "36px" },
  fieldError: { color: "#ffb4ab", fontSize: "12px", margin: "-8px 0 0", paddingLeft: "4px" },
  checkRow: { display: "flex", alignItems: "flex-start", gap: "8px", cursor: "pointer" },
  checkbox: { marginTop: "2px", accentColor: "#7c3aed", width: "16px", height: "16px", flexShrink: 0 },
  checkLabel: { color: "#ccc3d8", fontSize: "13px", lineHeight: "18px" },
  termsLink: { color: "#d2bbff", textDecoration: "underline", cursor: "pointer" },
  primaryBtn: {
    marginTop: "6px", background: "linear-gradient(135deg, #7c3aed, #6f54bf)",
    color: "#fff", border: "none", borderRadius: "8px", padding: "12px",
    fontSize: "15px", fontWeight: 600, cursor: "pointer", letterSpacing: "0.01em",
  },
  btnDisabled: { opacity: 0.6, cursor: "not-allowed" },
  switchText: { textAlign: "center", color: "#ccc3d8", fontSize: "13px", marginTop: "20px", marginBottom: 0 },
  linkBtn: { background: "none", border: "none", color: "#d2bbff", cursor: "pointer", fontSize: "13px", padding: 0, textDecoration: "underline" },
};
