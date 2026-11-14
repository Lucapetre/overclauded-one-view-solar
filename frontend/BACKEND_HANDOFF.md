# Backend handoff

Use the included SQLite schema as a starting point for a FastAPI application. The frontend currently calls the synchronous local persistence adapter in `src/store.js`; migrate mutations to asynchronous service methods with loading/error states. Never expose SQLite files, seed passwords or media keys in a real production deployment. Remove the source-download feature, role picker and synthetic fixtures from a real customer build.

## Auth and authorization

Seed hashes use `scrypt$16384$8$1$saltHex$digestHex`. `database/seed.py` generates independent random salts; verify using constant-time comparison. These development passwords are public and must be replaced. Issue opaque, hashed, expiring sessions using HttpOnly Secure SameSite cookies. Include CSRF protection and rate limits; do not use the frontend's sessionStorage user ID as identity.

Resolve scope server-side on every read AND write. CEO has all scopes; area manager/dispatcher only their areas; technicians only assigned sites and qualified technical work; clients only owned sites; supplier support only assigned nontechnical request metadata. Only CEO can enable/disable users or reset demo state. Supplier support must not receive video bytes. Return minimal data by service need; prevent direct object ID substitution from granting access.

## Proposed endpoints

| Method/path | Behavior |
| --- | --- |
| POST /api/auth/login | Verify password; create cookie session; return safe profile |
| POST /api/auth/logout | Revoke session |
| GET /api/me | Identity, capabilities and scope |
| GET /api/sites | Authorized installations only |
| GET /api/sites/{id}/energy | Normalized flows, timestamps, quality and source mode |
| PUT /api/me/preferences | Task, deadline and notification choice |
| POST /api/tasks | Validate task profile and idempotency key |
| POST /api/tasks/{id}/recommendations | Cost comparison and time-limited reserved offer |
| POST /api/recommendations/{id}/accept | Transactional expiry/revision/capacity check |
| POST /api/recommendations/{id}/cancel | Release all occupied reservations |
| GET /api/incidents | Authorized safety-ordered queue |
| PATCH /api/incidents/{id} | Revision check; owner/status/outcome; audit |
| POST /api/visits | Scoped report linked to incident |
| POST /api/visits/{id}/media | Quarantine, validate and store privately |
| GET /api/media/{id} | Authorized streaming; no public storage URL |
| POST /api/visits/{id}/replies | Qualified human response and timeline |
| GET /api/areas | Coverage denominators and source dates |
| GET /api/crews | Scope, qualifications, availability and shift |
| POST /api/assignments | Eligible crew proposal only |
| POST /api/assignments/{id}/confirm | Human authorization and overlap recheck |
| GET /api/audit | CEO-only decision history |

Error envelope: `{ "code": "CAPACITY_CONFLICT", "message": "Choose another window.", "request_id": "opaque-id" }`. Use 409 for stale revision, expiry and capacity conflicts, 413 for media size, 422 for invalid profiles, and a consistent 403/404 policy for unauthorized records. Add idempotency keys bound to user and operation.

## Important implementation work

1. For acceptance, BEGIN IMMEDIATE in SQLite, check offer expiry and revision, check capacity throughout every occupied interval and all overlapping tasks, commit the complete reservation and audit atomically. Preserve accepted start times. Expiry/cancellation releases all intervals. No expected-participation discount in admission.
2. For assignments, check ownership, skills, scope, shift and interval overlap transactionally. Technical review does not imply dispatch authorization. Record actor and decision version.
3. Store video outside the web root. Probe actual container and duration using bounded processing, quarantine and scan; browser metadata checks are UX only. Add size/rate limits, retention expiry, private streaming and media deletion.
4. Preserve UTC intervals, elapsed hours and source timestamps. Handle 23/25-hour local days. Distinguish replay time from actual receipt time. Do not fabricate zero when data is missing.
5. Add an ingestion/replay engine for the eight families; deduplicate active episodes. The frontend seed does not run detection. Keep unknown codes unmodified and abstain when evidence is absent.
6. Add real support contacts, staffing and reviewed safety copy before any real deployment. Do not issue generic equipment shutdown or reset instructions. No device-write API is in scope.
7. Poll authorized changes every five seconds, or implement authorized push. Cross-device persistence requires the backend; localStorage/IndexedDB only demonstrate the shared workflow in one browser.

## Validation completed in this frontend

Domain tests cover 4.50/2.25 RON arithmetic, invalid/no-benefit inputs, task deadline feasibility, full-duration capacity conflict, scope filtering, safety-first ranking, missing-data abstention, crew eligibility and time formatting. SQLite foreign-key and integrity checks run during seeding. Browser walkthrough covers client plan acceptance, text-only support submission, staff role navigation and review. These are not a security audit or a physical-system validation.
