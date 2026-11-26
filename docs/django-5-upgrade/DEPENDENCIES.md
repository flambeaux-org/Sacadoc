# Dependency compatibility matrix — Django 5.2 target

Verified against the PyPI JSON API and package changelogs (early–mid 2026). Confirm exact
resolved versions with a `pip install "Django>=5.2.8" -r requirements.txt` dry-run at
execution time, since patch releases land continuously.

## Python support
Django 5.2 (LTS, 2025-04-02) supports **Python 3.10 / 3.11 / 3.12 / 3.13**.
**Python 3.14 support was added in Django 5.2.8** → if you run 3.14, pin `Django>=5.2.8`.
Recommendation: run CI + prod on **3.13** (or 3.14 with `Django>=5.2.8`).

## Package matrix

| Package (current) | 5.2 OK? | Target | Risk | Notes / gotchas |
|---|---|---|---|---|
| **django-cryptography 1.0** | ❌ (dead, max 4.0) | **django-cryptography-5 ==2.0.3** (saaspegasus fork) | 🔴 | Drop-in: same `from django_cryptography.fields import encrypt`. Fernet keyed off `SECRET_KEY` (+ optional `CRYPTOGRAPHY_SALT`) → existing IBAN/password/address ciphertext stays readable **iff those settings are unchanged**. Classifiers stop at 5.1; verify a read of existing rows in staging. Avoid the `django-cryptography-django5` fork (only claims ≤5.0). |
| **django-datatable-view 2.1.6** | ⚠️ PyPI stale, but repo supports 5.2 | **install from Git @ `098e00e`** | 🟠 | **NOT abandoned** — repo actively maintained (last push 2026-05-07). PyPI is frozen at 2.1.6 (2021, Django ≤3.2). Commit `098e00e` (just before master bumped to Django-6-only) declares `django>=5.2`, classifiers Django 5.2 + 6.0, Python 3.12–3.14. Same package layout as 2.1.6 (`columns`/`datatables`/`helpers`/`views`) → imports intact. Pin the git SHA; verify API deltas across the 2021→2026 gap on your list views. Requires Python ≥3.12. Fallback if the API drifted too much: django-tables2. |
| **django-crispy-forms 1.13.0** | ❌ | **2.6** + **crispy-bootstrap4 ==2026.2** | 🟠 | 2.x moved template packs out. Add both `crispy_forms` and `crispy_bootstrap4` to INSTALLED_APPS; `CRISPY_TEMPLATE_PACK` now raises if unset (already set). Removed: `FormHelper.form_style`, `html5_required`, `render_field(form_style=…)`. |
| **django-csp 3.7** | ❌ | **4.0** | 🟠 | 4.0 replaces flat `CSP_*` settings with nested `CONTENT_SECURITY_POLICY = {"DIRECTIVES": {...}}`. Rewrite all CSP settings (see migration guide). |
| **django-axes 5.26.0** | ❌ | **8.3.1** | 🟠 | Big jump. Breaking across 6/7/8.x: handler/backend refactor, `AXES_*` renames/removals, cache-key changes, `AxesStandaloneBackend` setup. Read the 6.0 migration notes. |
| **django-select2 7.11.1** | ❌ | **8.4.8** | 🟠 | v8 **requires the admin app in INSTALLED_APPS** (present) **and a proper shared cache** (NOT LocMemCache) for model widgets → must configure `CACHES` (Redis/Memcached/DB). |
| **django-sn 0.8.11.9** (summernote fork) | ❌ (stale) | **django-summernote ==0.8.20.0** | 🟡 | Abandon the fork, return to upstream `django-summernote` (actively maintained). Verify app-name/template differences vs the fork. |
| **django-debug-toolbar 3.2.2** | ❌ | **7.0.0** | 🟢 | Dev-only. Just bump. |
| **django-extensions 3.1.3** | ❌ | **4.1** | 🟢 | Straightforward. |
| **django-cleanup 7.0.0** | ~ | **9.0.0** | 🟢 | Jazzband; follows Django supported versions. Simple bump. |
| **django-storages 1.13.1** | ❌ | **1.14.6** | 🟢 | Declares ≤5.1, functional on 5.2. Bump again when a 5.2-classifier release lands. |
| **django-dbbackup 3.3.0** | ❌ | **5.3.0** | 🟡 | Major jump; review 4.x changelog for command/settings changes. |
| **django-crontab 0.7.1** | ~ (unmaintained) | keep 0.7.1 or migrate | 🟡 | Thin `crontab` wrapper, low Django coupling → usually still runs. If it breaks: `django-cron-django5`, system cron, or Celery beat. |
| **django-formtools 2.3** | ❌ | **2.6.1** | 🟢 | Clean bump. |
| **django-anymail 8.4** | ❌ | **15.0** | 🟡 | Big jump, stable API; check ESP backend notes. |
| **django-resized 1.0.3** | ~ (max 5.1) | 1.0.3 (latest) | 🟢 | Already latest. Test image save/resize on 5.2. |
| **django-multiselectfield 0.1.12** | ❌ | **1.0.1** | 🟠 | **1.0 breaking: integer choices dropped.** This repo uses integer keys in `JOURS_SEMAINE` → see blocker B5. |
| **django-turnstile 0.1.3** | ❌ (max 4.0) | **replace → django-cf-turnstile** | 🟡 | Original near-abandoned. `django-cf-turnstile` (ronaldgrn) supports 4.2 + 5.2. Implicit widget rendering only. |
| **django-upload-form 0.5.0** | ? (undeclared) | 0.5.0 (latest) | 🟡 | Thin Form wrapper; likely runs but untested on 5.2 — verify upload flow. |
| **django-appconf 1.0.5** | ❌ | **1.2.0** | 🟢 | Clean bump (transitive dep of others too). |
| **django-ipware 4.0.2** | ~ | **7.0.1** | 🟡 | 7.x wraps `python-ipware`; `get_client_ip` return signature evolved — check call sites. |
| **django-ranged-response 0.2.0** | ~ (abandoned) | 0.2.0 (only version) | 🟢 | Tiny StreamingHttpResponse subclass, no Django coupling. Works on 5.2. |

## Config rewrites required (not just version bumps)
- **django-csp 4.0** → nested `CONTENT_SECURITY_POLICY` dict.
- **django-crispy-forms 2.x** → add `crispy-bootstrap4` package + app.
- **django-axes 8.x** → settings/backend migration.
- **django-select2 8.x** → add a shared `CACHES` backend (LocMemCache won't do).

## Replace / abandon
- `django-cryptography` → `django-cryptography-5`
- `django-datatable-view` → **keep it**, install from Git @ `098e00e` (PyPI stale but repo active & 5.2-ready); django-tables2 only as a fallback if the API drifted
- `django-turnstile` → `django-cf-turnstile`
- `django-sn` → upstream `django-summernote`
- `django-crontab` → keep unless it breaks, else `django-cron-django5` / system cron

## Data-affecting
- **django-multiselectfield 1.0** dropped integer choices → audit `JOURS_SEMAINE` (blocker B5).
