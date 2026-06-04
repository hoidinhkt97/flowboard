import { useState } from "react";
import { useAuthStore } from "../../store/auth";

interface LoginPageProps {
  onGoRegister: () => void;
}

export function LoginPage({ onGoRegister }: LoginPageProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const { login, loading, error, clearError } = useAuthStore();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await login(email, password);
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        {/* Logo */}
        <div style={styles.logoRow}>
          <div style={styles.logoIcon}>F</div>
          <span style={styles.logoText}>Flowboard</span>
        </div>
        <h1 style={styles.heading}>Welcome back</h1>
        <p style={styles.sub}>Access your creative AI workspace.</p>

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
          <div style={styles.field}>
            <span style={styles.fieldIcon}>🔒</span>
            <input
              type={showPw ? "text" : "password"}
              placeholder="Password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              style={styles.input}
              autoComplete="current-password"
            />
            <button type="button" onClick={() => setShowPw(v => !v)} style={styles.eyeBtn}>
              {showPw ? "🙈" : "👁"}
            </button>
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{ ...styles.primaryBtn, ...(loading ? styles.btnDisabled : {}) }}
          >
            {loading ? "Signing in…" : "Sign in →"}
          </button>
        </form>

        <p style={styles.switchText}>
          New here?{" "}
          <button onClick={onGoRegister} style={styles.linkBtn}>
            Create an account
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
  logoRow: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "24px",
  },
  logoIcon: {
    width: "36px",
    height: "36px",
    borderRadius: "8px",
    background: "linear-gradient(135deg, #7c3aed, #4cd7f6)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: "#fff",
    fontWeight: 700,
    fontSize: "18px",
  },
  logoText: {
    color: "#dae2fd",
    fontWeight: 600,
    fontSize: "18px",
  },
  heading: {
    color: "#dae2fd",
    fontSize: "28px",
    fontWeight: 700,
    margin: "0 0 8px",
  },
  sub: {
    color: "#ccc3d8",
    fontSize: "14px",
    margin: "0 0 28px",
  },
  errorBanner: {
    background: "rgba(147,0,10,0.3)",
    border: "1px solid #ffb4ab",
    color: "#ffb4ab",
    borderRadius: "6px",
    padding: "10px 14px",
    fontSize: "13px",
    marginBottom: "16px",
    cursor: "pointer",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
  },
  field: {
    position: "relative",
    display: "flex",
    alignItems: "center",
  },
  fieldIcon: {
    position: "absolute",
    left: "12px",
    fontSize: "14px",
    pointerEvents: "none",
    zIndex: 1,
  },
  input: {
    width: "100%",
    background: "#131b2e",
    border: "1px solid #4a4455",
    borderRadius: "8px",
    color: "#dae2fd",
    fontSize: "14px",
    padding: "11px 40px 11px 36px",
    outline: "none",
    boxSizing: "border-box",
    transition: "border-color 0.2s",
  },
  eyeBtn: {
    position: "absolute",
    right: "10px",
    background: "none",
    border: "none",
    cursor: "pointer",
    fontSize: "16px",
    padding: "4px",
    lineHeight: 1,
  },
  primaryBtn: {
    marginTop: "6px",
    background: "linear-gradient(135deg, #7c3aed, #6f54bf)",
    color: "#fff",
    border: "none",
    borderRadius: "8px",
    padding: "12px",
    fontSize: "15px",
    fontWeight: 600,
    cursor: "pointer",
    transition: "opacity 0.2s",
    letterSpacing: "0.01em",
  },
  btnDisabled: {
    opacity: 0.6,
    cursor: "not-allowed",
  },
  switchText: {
    textAlign: "center",
    color: "#ccc3d8",
    fontSize: "13px",
    marginTop: "20px",
    marginBottom: 0,
  },
  linkBtn: {
    background: "none",
    border: "none",
    color: "#d2bbff",
    cursor: "pointer",
    fontSize: "13px",
    padding: 0,
    textDecoration: "underline",
  },
};
