# S3-8: ARCHITECTURE.md Auth Design Record + S3 Integration Check

**Date**: 2026-05-25
**Branch**: feature/s3-8-architecture-auth-design
**Goal**: Document the authentication layer design decisions in ARCHITECTURE.md
in English, and verify all four S3 auth flows end-to-end.

---

## Step C Walkthrough

### What was built

Added **Section 7 — Authentication & Authorization Design** to `ARCHITECTURE.md`,
covering four design decisions:

| Section | Topic |
|---|---|
| 7.1 | Why JWT over server-side sessions |
| 7.2 | Why RBAC over ABAC |
| 7.3 | Why native PostgreSQL enum for the `role` column |
| 7.4 | Why uniform error messages for auth failures |

Each section follows the pattern: **Decision → What was rejected → Rationale → Trade-off**.

### Verification — four curl flows (PowerShell)

```powershell
# Flow 1: obtain JWT
$response = Invoke-RestMethod -Method Post `
  -Uri "http://localhost:8000/api/v1/auth/login" `
  -ContentType "application/json" `
  -Body '{"email":"admin@example.com","password":"password"}'
$ADMIN_TOKEN = $response.access_token

# Flow 2: protected GET with admin JWT → 200
$headers = @{ Authorization = "Bearer $ADMIN_TOKEN" }
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/v1/accounts" -Headers $headers

# Flow 3: POST /transactions with admin JWT → 201
$body = @{
  description      = "S3-8 test"
  transaction_date = "2026-05-25"
  entries = @(
    @{ account_id = $DR_ID; direction = "debit";  amount = 1000; currency = "EUR" }
    @{ account_id = $CR_ID; direction = "credit"; amount = 1000; currency = "EUR" }
  )
} | ConvertTo-Json -Depth 3
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/v1/transactions" `
  -Headers $headers -ContentType "application/json" -Body $body

# Flow 4: POST /transactions with auditor JWT → 403
# (caught as exception; detail: "Admin role required")
```

---

## Key Takeaways

### What did I learn?

- Writing design decisions in the **Decision → Rejected → Rationale → Trade-off**
  format forces clarity about *why* a choice was made, not just *what* was chosen.
  The act of writing "what was rejected" is where the real design thinking happens.
- JWT's statelessness benefit (no shared session store, easy horizontal scaling)
  is intuitive; the harder part to articulate is the revocation problem — a
  valid token stays valid until expiry even if the user is disabled. Knowing this
  trade-off is a standard interview question.
- RBAC vs ABAC: the right mental model is "how many independent dimensions does
  access control depend on?" Two roles and one resource type → RBAC. Fine-grained
  attributes, environments, or resource ownership → ABAC.
- PostgreSQL native enum provides type safety at two layers (DB and ORM) at the
  cost of migration friction. Worth it at 2 values; reconsider at 10+.

### What would I do differently?

- Set up test users (admin + auditor) as part of the project's seed script or
  Docker entrypoint from the beginning. Manually inserting users via psql and
  then updating the role with a separate UPDATE is error-prone during demos.
- Avoid using single-line PowerShell JSON strings for long request bodies. The
  `ConvertTo-Json` hashtable approach is more readable and immune to terminal
  line-wrap issues.

### What surprised me?

- Swagger UI's "Authorize" button uses `OAuth2PasswordRequestForm` (form data,
  `username` field), but the `/auth/login` endpoint expects a JSON body with an
  `email` field. The two are incompatible out of the box. Workaround: execute
  `POST /auth/login` directly in Swagger UI to get the token, then paste it
  into the Authorize dialog manually.
- FastAPI validates the **request body before running auth dependencies** when
  both fail simultaneously. A 422 (body validation error) takes precedence over
  a 403 (auth failure) — the auth check never runs if the body is malformed.
  This means an invalid-body request from an auditor returns 422, not 403.
  The 403 is correctly returned once the body is valid.

### What is worth remembering for future goals?

- The `Decision → Rejected → Rationale → Trade-off` structure is reusable for
  any ADR or interview question. Practicing this structure on every design choice
  makes answers feel natural rather than rehearsed.
- When testing role-based access, always confirm the token is valid first
  (check a permissive endpoint like `GET /accounts`) before testing the
  restricted one. This isolates whether the failure is auth or business logic.
- TD-007 (ADR numbering inconsistency in ARCHITECTURE.md) is still open.
  The new Section 7 deliberately avoids ADR-XXX numbering to prevent making
  the inconsistency worse. Fix in a dedicated docs sprint before portfolio
  publication.
