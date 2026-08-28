/**
 * A simplified geographic reference outline of India's boundary, hand-
 * traced from well-known coastline/border landmarks - NOT survey-grade
 * GeoJSON, and not sourced from any backend endpoint (none exists: no
 * jurisdictions-list endpoint, no state/district exposed anywhere - see
 * FRONTEND_F3_READINESS.md §2/§5). This is a static reference shape, the
 * same category of asset as an icon, used only to give a real case
 * coordinate geographic context - never presented as backend data, never
 * carrying any jurisdiction information itself.
 *
 * [lat, lon] pairs, clockwise from Kutch.
 */
export const INDIA_OUTLINE_LATLON: [number, number][] = [
  [23.7, 68.9], // Kutch
  [21.6, 69.6], // Saurashtra coast
  [20.7, 72.0], // South Gujarat
  [18.9, 72.8], // Maharashtra coast (Mumbai)
  [15.4, 73.8], // Goa
  [12.9, 74.8], // Karnataka coast
  [9.9, 76.2], // Kerala coast
  [8.1, 77.5], // Kanyakumari (southern tip)
  [9.3, 79.3], // Tamil Nadu east coast
  [13.1, 80.3], // Tamil Nadu (Chennai)
  [16.9, 82.3], // Andhra Pradesh coast
  [19.8, 85.9], // Odisha coast
  [21.6, 88.2], // West Bengal coast
  [24.5, 88.1], // Bangladesh west border
  [26.0, 89.9], // Assam entry
  [28.0, 96.0], // Arunachal Pradesh (simplified NE)
  [24.9, 94.0], // Nagaland / Manipur east
  [22.8, 92.8], // Mizoram south
  [23.5, 91.0], // Bangladesh east border
  [26.8, 88.9], // North Bengal / Bhutan border
  [27.9, 88.2], // Sikkim / Nepal border east
  [28.6, 82.0], // Nepal border (mid)
  [30.3, 80.2], // Nepal border west / Uttarakhand
  [32.0, 78.5], // Himachal Pradesh
  [34.8, 77.5], // Ladakh
  [35.5, 76.0], // Kashmir (northernmost)
  [34.0, 74.0], // Kashmir west
  [31.5, 74.4], // Punjab border
  [28.0, 70.5], // Rajasthan border
  [24.5, 69.5], // Rann of Kutch
];

/** Real bounding box for the outline above - used to project both the
 * outline and any real case coordinate consistently. */
export const INDIA_BOUNDS = { minLat: 6.5, maxLat: 37.0, minLon: 68.0, maxLon: 97.5 };
