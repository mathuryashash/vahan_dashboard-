# Production Hardening Plan (superseded)

**This plan is done. Its live successor is
[`docs/PRODUCTION_HARDENING_CHECKLIST.md`](docs/PRODUCTION_HARDENING_CHECKLIST.md).**

The original body described the app as having "no auth of any kind" and "every
endpoint public". That stopped being true months ago, and a document that
understates the security posture of a commercial product is worse than no
document -- someone reads it as current state. The text is preserved in git
history (`git log --follow -- PRODUCTION_HARDENING.md`) rather than kept here.

What it proposed, and what actually shipped instead:

| Its plan | What exists now |
|---|---|
| A single shared static API key, gating `/refresh/` only | Per-user accounts: bcrypt (cost 12), JWT in an httpOnly cookie, `samesite=lax`, `secure` derived from the request scheme. `get_current_user` re-reads the user row on every request, so deactivating a user or changing their role takes effect immediately rather than at token expiry. See `backend/app/core/auth.py`. |
| "Don't build per-user auth speculatively" | A three-tier role and scope hierarchy did turn out to be the product (national / state / RTO, plus an orthogonal vehicle-category scope), enforced as real SQL predicates -- see `backend/app/core/scope.py` and `query_filters.py`. |
| Rate limiting listed as unimplemented | Blanket 120/min per IP via slowapi, keyed on `X-Real-IP` behind nginx, plus a per-email login lockout (5 attempts / 5 min). See `backend/app/core/rate_limit.py`. |
| Postgres migration listed as pending | Done. Postgres 18, ~18M rows, with an idempotent `ensure_*` migration chain in `backend/app/core/migrations.py`. |

Still genuinely open, and tracked in the new checklist: TLS termination, the
default `vahan:vahan` Postgres password, removing the demo accounts from a
production deployment, and the published `8020:8020` port that lets callers
bypass nginx.
