# Upgrade plan: Django 3.2 → 5.2 LTS

**Current:** Django `3.2.19` · **Target:** Django `5.2.x` (LTS, supported until Apr 2028).
**Codebase:** ~1,400 Python files, 253 migrations, custom user model, encrypted DB
fields, family portal, billing, payment gateways.

This is a **4-major-version jump** (3.2 → 4.0 → 4.1 → 4.2 → 5.0 → 5.1 → 5.2). We do it
in **staged steps**, not one leap: each Django minor is a checkpoint where tests must be
green before moving on. The dependency stack is the hard part, not Django itself — the
code is already mostly modern (uses `path()`, no `ugettext`/`is_ajax`/`url()`).

> Progress is tracked with the checkboxes below. Tick as you go; keep this file in the repo.

---

## Known code-level blockers (found in this repo)

| # | Location | Issue | Removed in | Fix |
|---|----------|-------|-----------|-----|
| B1 | `noethysweb/settings.py:176` | `USE_L10N = True` | 5.0 | Delete the line — localization is always on in 5.x. Confirm French formats still apply (they will; `LANGUAGE_CODE='fr'`, `DATE_FORMAT` kept). |
| B2 | `noethysweb/settings.py:191` | `STATICFILES_STORAGE = ...` | 5.1 | Migrate to the `STORAGES` dict (test settings already do this — mirror it, keeping the custom `ForgivingManifestStaticFilesStorage`). |
| B3 | `core/models.py:12,271` | `from django.core.files.storage import get_storage_class` | 5.1 | Replace `get_storage_class(path)` with `django.utils.module_loading.import_string(path)` — returns the same class, drop-in. |
| B4 | `django_cryptography` (encrypted fields) | Package abandoned; no Django 4.2/5.x support | — | **Critical.** Replace with `django-cryptography-5==2.0.3` (drop-in, same API, Fernet keyed off `SECRET_KEY`). Existing ciphertext stays readable **iff `SECRET_KEY`/`CRYPTOGRAPHY_SALT` unchanged**. See manual test §0. |
| B5 | `core/models.py:34` `JOURS_SEMAINE = [(0,"L"),(1,"M"),…]` | `django-multiselectfield` 1.0 **drops integer choices**; used by `jours_scolaires`/`jours_vacances` on 3 models | (1.0) | Either pin multiselectfield to a pre-1.0 version compatible with 5.2, or convert `JOURS_SEMAINE` keys to strings (`"0"`,`"1"`,…) **with a data migration** for existing comma-separated integer values. Data-affecting — test carefully. |
| B6 | `settings.py` (no `CACHES`) | `django-select2` v8 needs a **shared cache** (LocMemCache default won't work for model widgets) | — | Add a `CACHES` backend (Redis/Memcached/DB/file). Affects Select2 autocomplete across the app. |

Not found (good — nothing to fix): `ugettext*`, `force_text`/`smart_text`,
`request.is_ajax()`, `NullBooleanField`, `default_app_config`, `providing_args`,
`index_together`, `django.conf.urls.url()`, `pytz`, `timezone.utc`.

Watch items:
- **CSRF (Django 4.0):** `Origin` header is now checked on secure requests. If the prod
  site is behind a proxy / uses a non-default port, add `CSRF_TRUSTED_ORIGINS`
  (must include scheme, e.g. `https://example.com`).
- **`SECRET_KEY_FALLBACKS`** available since 4.1 — useful if we ever rotate the key, but
  do NOT rotate `SECRET_KEY` during this upgrade (it is the encryption key — see B4).

---

## Dependency strategy

The Django bump is gated by third-party packages. Target versions are confirmed by the
compatibility check (`docs/django-5-upgrade/DEPENDENCIES.md`). High-risk ones first:

Full verified table in **`DEPENDENCIES.md`**. Highest-risk first:

| Package | Current → Target | Risk | Notes |
|---------|------------------|------|-------|
| `django-cryptography` | 1.0 → **django-cryptography-5 2.0.3** | 🔴 critical | Drop-in fork, same API, Fernet keyed off `SECRET_KEY`. **Data-compat is the #1 risk** — encrypted IBAN/BIC/passwords/addresses must still decrypt. Test on prod-data copy before deploy. |
| `django-datatable-view` | 2.1.6 → **git @ `098e00e`** | 🟠 medium | **Actively maintained** (last push 2026-05-07); PyPI is just stale. Commit `098e00e` supports `django>=5.2` (same package layout as 2.1.6). Install from Git, pin the SHA, verify API deltas on list views. Requires Python ≥3.12. Not a rewrite. |
| `django-multiselectfield` | 0.1.12 → **1.0.1** | 🟠 medium | 1.0 drops integer choices → blocker **B5** (data migration for `JOURS_SEMAINE`). |
| `django-crispy-forms` | 1.13.0 → **2.6** (+ `crispy-bootstrap4 2026.2`) | 🟠 medium | 2.x moved template packs out. Author already anticipated this (commented code in settings). 311 files use crispy. |
| `django-csp` | 3.7 → **4.0** | 🟠 medium | 4.0 replaces `CSP_*` settings with a nested `CONTENT_SECURITY_POLICY` dict → rewrite all `CSP_*` in settings.py. |
| `django-axes` | 5.26.0 → **8.3.1** | 🟠 medium | Big jump; `AXES_*` renames, backend/handler refactor, cache-key changes. Read 6.0 migration notes. |
| `django-select2` | 7.11.1 → **8.4.8** | 🟠 medium | v8 needs a shared cache backend → blocker **B6** (`CACHES`). |
| `django-turnstile` | 0.1.3 → **replace (django-cf-turnstile)** | 🟡 low | Original abandoned; `django-cf-turnstile` supports 5.2. |
| `django-sn` (summernote fork) | 0.8.11.9 → **django-summernote 0.8.20.0** | 🟡 low | Abandon fork, return to upstream. |
| `django-dbbackup` | 3.3.0 → **5.3.0** | 🟡 low | Major jump; review 4.x changelog. |
| `django-anymail` | 8.4 → **15.0** | 🟡 low | Big jump, stable API; check ESP notes. |
| `django-ipware` | 4.0.2 → **7.0.1** | 🟡 low | `get_client_ip` return signature evolved — check call sites. |
| `django-crontab` | 0.7.1 (keep) | 🟡 low | Unmaintained but thin; keep unless it breaks (fallback: system cron / django-cron-django5). |
| `-debug-toolbar 7.0.0`, `-extensions 4.1`, `-cleanup 9.0.0`, `-storages 1.14.6`, `-formtools 2.6.1`, `-appconf 1.2.0`, `-resized 1.0.3`, `-upload-form 0.5.0`, `-ranged-response 0.2.0` | bump | 🟢 | Low risk. See DEPENDENCIES.md. |

**Python:** Django 5.2 supports 3.10–3.13; **3.14 support was added in Django 5.2.8**.
CI currently runs 3.10 → move CI + prod to **3.13** (or 3.14 with `Django>=5.2.8`).

---

## Phased execution

### Phase 0 — Safety net & baseline
- [ ] Do the work on a branch; never rotate `SECRET_KEY`.
- [ ] Get a **copy of production data** (with real encrypted fields) into a staging DB.
- [ ] Confirm current test suite is green on 3.2 as the baseline (`pytest`).
- [ ] Enable deprecation warnings: run `python -W error::DeprecationWarning manage.py test`
      (or set filters) so each step surfaces removals early.
- [ ] Bump CI Python to the target (3.12/3.13) on a scratch branch to catch env issues.

### Phase 1 — Resolve the dependency wall (before touching Django)
- [ ] Finalize `DEPENDENCIES.md` target versions (pip resolver dry-run against Django 5.2).
- [ ] **B4 — cryptography (go/no-go gate):** swap `django-cryptography` →
      `django-cryptography-5==2.0.3`; on the prod-data copy verify old ciphertext
      decrypts **and** new writes round-trip (manual test §0). Never change `SECRET_KEY`.
- [ ] **datatable-view:** install from Git @ `098e00e` (`pip install
      git+https://github.com/pivotal-energy-solutions/django-datatable-view.git@098e00e`);
      spike one list end-to-end (search/sort/paginate/row actions) to surface any API
      deltas since 2.1.6, then confirm the rest. Fall back to django-tables2 only if the
      API drifted too far. Requires Python ≥3.12.
- [ ] **B5 — multiselectfield:** decide pin-vs-convert for `JOURS_SEMAINE`; if converting
      keys to strings, write + test the data migration.
- [ ] **B6 — cache:** add a `CACHES` backend for django-select2 v8.
- [ ] crispy-forms 2.x + `crispy-bootstrap4` (add to INSTALLED_APPS); smoke-test forms.
- [ ] django-csp 4.0: rewrite `CSP_*` → `CONTENT_SECURITY_POLICY` dict; check no CSP
      violations in browser console (manual test §1).
- [ ] django-axes 8.x: apply setting/backend migration; verify lockout still works.
- [ ] Replace `django-turnstile` → `django-cf-turnstile`; `django-sn` → `django-summernote`.

### Phase 2 — Django 4.0 → 4.1 → 4.2 (each a checkpoint)
- [ ] Fix **B1** (`USE_L10N`) and any 4.x deprecation warnings.
- [ ] Add `CSRF_TRUSTED_ORIGINS` for prod if needed (4.0 CSRF change).
- [ ] `makemigrations --check` clean; `migrate` on staging DB clean.
- [ ] `pytest` green at 4.2 (LTS) — treat 4.2 as a solid intermediate landing point.

### Phase 3 — Django 5.0 → 5.1 → 5.2
- [ ] At 5.0: confirm B1 done (`USE_L10N` gone).
- [ ] At 5.1: fix **B2** (`STORAGES`) and **B3** (`import_string`).
- [ ] Land on **5.2.x**; pin exact versions in `requirements.txt`.
- [ ] `manage.py check --deploy` clean; `makemigrations --check` clean.
- [ ] `pytest` green; `collectstatic` succeeds with the new `STORAGES` config.

### Phase 4 — Verification & deploy
- [ ] Full automated suite green (unit + Playwright) on target Python.
- [ ] Work through **`MANUAL_TESTS.md`** on the prod-data copy — §0 first (go/no-go).
- [ ] Deploy to staging mirroring prod (MySQL, gunicorn, real ESP/gateways in sandbox).
- [ ] Re-run crontab (`manage.py crontab add`), verify scheduled jobs.
- [ ] Production deploy in a maintenance window with a tested rollback (DB backup + prior
      release). **Keep the same `SECRET_KEY`.**

---

## Rollback

- Keep the pre-upgrade release deployable and a DB backup taken immediately before deploy.
- Because encrypted fields are tied to `SECRET_KEY`, rolling *back* the code is safe as
  long as `SECRET_KEY` never changed. Never change it as part of this upgrade.

## Deliverables in this folder
- `PLAN.md` — this file (staged plan + checklist).
- `MANUAL_TESTS.md` — features to test by hand after the upgrade.
- `DEPENDENCIES.md` — verified per-package target versions and gotchas.
