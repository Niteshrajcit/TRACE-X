import { FormEvent, useRef, useState } from "react";
import { ApiError, createComplaint } from "../api/client";
import type { ComplaintCreateRequest, FraudType, InstitutionType } from "../types/domain";

const FRAUD_TYPES: { value: FraudType; label: string }[] = [
  { value: "upi_fraud", label: "UPI Fraud" },
  { value: "phishing", label: "Phishing" },
  { value: "investment_scam", label: "Investment Scam" },
  { value: "loan_app_fraud", label: "Loan App Fraud" },
  { value: "other", label: "Other" },
];

const INSTITUTION_TYPES: { value: InstitutionType; label: string }[] = [
  { value: "bank", label: "Bank" },
  { value: "wallet", label: "Wallet" },
  { value: "merchant", label: "Merchant" },
  { value: "exchange", label: "Exchange" },
  { value: "other", label: "Other" },
];

const emptyForm = {
  incidentDate: "",
  incidentTime: "",
  fraudType: "upi_fraud" as FraudType,
  amount: "",
  locationText: "",
  institutionName: "",
  institutionType: "bank" as InstitutionType,
  transactionReference: "",
  victimAccountNumber: "",
  victimPhone: "",
  victimEmail: "",
  description: "",
  evidenceNotes: "",
  jurisdictionHint: "",
};

type FormState = typeof emptyForm;

/**
 * docs/PRODUCT_EXPERIENCE.md §2 screen 01. Deliberately plain - this phase
 * is about functional correctness of the intake -> incident pipeline, not
 * the visual design pass (docs/DESIGN_SYSTEM.md is a later-phase spec).
 */
export function ComplaintPortal() {
  const [form, setForm] = useState<FormState>(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{
    incidentReference: string;
    complaintId: string;
    phone: string | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // A fresh key per browser form load; if a double-click or a retried
  // request re-sends the same submission, the backend returns the same
  // incident instead of filing a duplicate complaint (docs/API_CONTRACT.md
  // §1, idempotency_key).
  const idempotencyKeyRef = useRef<string>(crypto.randomUUID());

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const incidentDatetime = new Date(
        `${form.incidentDate}T${form.incidentTime || "00:00"}:00`
      ).toISOString();

      const payload: ComplaintCreateRequest = {
        incident_datetime: incidentDatetime,
        fraud_type: form.fraudType,
        amount: form.amount,
        location_text: form.locationText,
        institution_name: form.institutionName,
        institution_type: form.institutionType,
        transaction_reference: form.transactionReference || null,
        victim_account_number: form.victimAccountNumber || null,
        victim_phone: form.victimPhone || null,
        victim_email: form.victimEmail || null,
        description: form.description,
        evidence_notes: form.evidenceNotes
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean),
        jurisdiction_hint: form.jurisdictionHint || null,
        idempotency_key: idempotencyKeyRef.current,
      };

      const submittedPhone = form.victimPhone ? form.victimPhone.trim() : null;
      const response = await createComplaint(payload);
      setResult({
        incidentReference: response.incident_reference,
        complaintId: response.complaint_id,
        phone: submittedPhone,
      });
      setForm(emptyForm);
      idempotencyKeyRef.current = crypto.randomUUID();
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Could not reach TRACE-X. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    const cleanDigits = result.phone ? result.phone.replace(/\D/g, "").slice(-10) : null;
    return (
      <div className="centered-shell">
        <div className="card-portal" style={{ maxWidth: 520, textAlign: "center" }}>
          <h1>Complaint Registered!</h1>
          <p style={{ marginTop: 12 }}>
            Your TRACE-X incident reference is{" "}
            <strong className="mono" style={{ fontSize: "1.1rem", color: "var(--accent)" }}>
              {result.incidentReference}
            </strong>
            .
          </p>
          {cleanDigits && (
            <p style={{ marginTop: 12, padding: "8px 12px", background: "rgba(0, 200, 100, 0.1)", borderRadius: 6, color: "var(--text-main)" }}>
              📱 Confirmation SMS dispatched to +91 {cleanDigits}
            </p>
          )}
          <p className="hint" style={{ marginTop: 8 }}>Keep this reference to check the status of your complaint.</p>
          <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={() => setResult(null)}>
            File another complaint
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="centered-shell" style={{ alignItems: "flex-start", paddingTop: 48 }}>
      <div className="card-portal">
      <h1>TRACE-X Cyber Fraud Complaint Portal</h1>
      <p className="subtitle">
        Report a financial cyber fraud. This is a Smart India Hackathon prototype - complaints
        submitted here are stored on TRACE-X's own systems, not the national NCRP portal.
      </p>

      <form onSubmit={handleSubmit} className="form-grid">
        <fieldset>
          <legend>When did it happen?</legend>
          <label>
            Incident date
            <input
              type="date"
              required
              value={form.incidentDate}
              onChange={(e) => update("incidentDate", e.target.value)}
            />
          </label>
          <label>
            Incident time
            <input
              type="time"
              required
              value={form.incidentTime}
              onChange={(e) => update("incidentTime", e.target.value)}
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>What happened?</legend>
          <label>
            Fraud category
            <select value={form.fraudType} onChange={(e) => update("fraudType", e.target.value as FraudType)}>
              {FRAUD_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Amount lost (INR)
            <input
              type="number"
              min="1"
              step="0.01"
              required
              value={form.amount}
              onChange={(e) => update("amount", e.target.value)}
            />
          </label>
          <label>
            Description
            <textarea
              required
              minLength={10}
              rows={4}
              value={form.description}
              onChange={(e) => update("description", e.target.value)}
              placeholder="What happened, step by step?"
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Where did it happen?</legend>
          <label>
            Location (area, city)
            <input
              type="text"
              required
              value={form.locationText}
              onChange={(e) => update("locationText", e.target.value)}
              placeholder="e.g. T. Nagar, Chennai"
            />
          </label>
          <label>
            District / jurisdiction (if known)
            <input
              type="text"
              value={form.jurisdictionHint}
              onChange={(e) => update("jurisdictionHint", e.target.value)}
              placeholder="e.g. Chennai"
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Bank / wallet / merchant involved</legend>
          <label>
            Institution name
            <input
              type="text"
              required
              value={form.institutionName}
              onChange={(e) => update("institutionName", e.target.value)}
            />
          </label>
          <label>
            Institution type
            <select
              value={form.institutionType}
              onChange={(e) => update("institutionType", e.target.value as InstitutionType)}
            >
              {INSTITUTION_TYPES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Transaction reference (if any)
            <input
              type="text"
              value={form.transactionReference}
              onChange={(e) => update("transactionReference", e.target.value)}
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Your contact / account details</legend>
          <p className="hint">
            Stored only as a one-way cryptographic hash - never in the clear (docs/SECURITY_AND_GOVERNANCE.md §2).
          </p>
          <label>
            Your account number
            <input
              type="text"
              value={form.victimAccountNumber}
              onChange={(e) => update("victimAccountNumber", e.target.value)}
            />
          </label>
          <label>
            Phone number
            <input
              type="tel"
              value={form.victimPhone}
              onChange={(e) => update("victimPhone", e.target.value)}
            />
          </label>
          <label>
            Email
            <input
              type="email"
              value={form.victimEmail}
              onChange={(e) => update("victimEmail", e.target.value)}
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>Evidence you have (optional)</legend>
          <label>
            One item per line (e.g. "Screenshot of debit SMS", "Call recording")
            <textarea
              rows={3}
              value={form.evidenceNotes}
              onChange={(e) => update("evidenceNotes", e.target.value)}
            />
          </label>
        </fieldset>

        {error && <p className="error-text">{error}</p>}

        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting ? "Submitting..." : "Submit complaint"}
        </button>
      </form>
      </div>
    </div>
  );
}
