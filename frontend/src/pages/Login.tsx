import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, login } from "../api/client";
import { useAuth } from "../context/AuthContext";

export function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { setAuth } = useAuth();
  const navigate = useNavigate();

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await login({ email, password });
      setAuth({
        token: response.access_token,
        role: response.role,
        jurisdictionId: response.jurisdiction_id,
      });
      navigate("/mission-control");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach TRACE-X.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="centered-shell">
      <div className="card-auth">
        <div className="row" style={{ gap: 10, marginBottom: 20 }}>
          <span className="mark" style={{
            width: 32, height: 32, borderRadius: 8,
            background: "linear-gradient(135deg, var(--accent) 0%, #0891b2 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "#04141a", fontWeight: 700, fontSize: "0.85rem",
          }}>TX</span>
          <div>
            <div style={{ fontWeight: 700, fontSize: "1.05rem" }}>TRACE-X</div>
            <div className="dim" style={{ fontSize: "0.68rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Intelligence Console
            </div>
          </div>
        </div>
        <h1 style={{ marginBottom: 4 }}>Investigator sign in</h1>
        <p className="hint" style={{ marginBottom: 20 }}>
          Demo credentials seeded by <code>scripts/seed_synthetic.py</code> (see backend README).
        </p>
        <form onSubmit={handleSubmit} className="form-grid">
          <label>
            Email
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="investigator@tracex-demo.com" />
          </label>
          <label>
            Password
            <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p className="error-text">{error}</p>}
          <button type="submit" className="btn btn-primary btn-block" disabled={submitting} style={{ marginTop: 8 }}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
