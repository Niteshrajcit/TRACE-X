import type { ComplaintDetail, RingSummary } from "../types/domain";

/**
 * Shared between Case Overview and Network Investigation so the two pages
 * never quietly drift into showing different "why is this suspicious"
 * reasoning for the same case. Every line here traces to a real field on
 * RingSummary/ComplaintDetail - nothing here is a computed "AI risk score"
 * (see the F1/F2 readiness reports' honesty discipline around exactly that).
 */
export function computeSuspiciousIndicators(rings: RingSummary[], complaint: ComplaintDetail): string[] {
  const indicators: string[] = [];
  if (rings.length > 0) {
    indicators.push(`${rings.length} detected fraud ring${rings.length > 1 ? "s" : ""} sharing entities with this case`);
  }
  const highCohesion = rings.filter((r) => Number(r.cohesion_score) >= 0.7);
  if (highCohesion.length > 0) {
    indicators.push(`${highCohesion.length} ring(s) with high structural cohesion (≥0.70)`);
  }
  const fastBurst = rings.filter((r) => r.burst_ratio && Number(r.burst_ratio) > 0.5);
  if (fastBurst.length > 0) {
    indicators.push(`Burst transaction pattern detected in ${fastBurst.length} ring(s)`);
  }
  if (complaint.latest_prediction) {
    indicators.push("An automated exit-corridor prediction is available for this case");
  }
  if (indicators.length === 0) {
    indicators.push("No automated suspicious-pattern indicators yet — intelligence pipeline may still be building the graph.");
  }
  return indicators;
}
