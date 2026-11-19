# Django 5.2 upgrade — manual test checklist

These are the features that must be tested **by hand** after the upgrade. They are
listed here because they are too costly or too fragile to automate reliably:
external services (payment gateways, email, Dropbox), binary output (PDF / Word / SEPA
files opened in real software), scheduled jobs, encrypted data round-trips, and
rich-client JS widgets.

> **How to use:** run through this on a **copy of production data** (real encrypted
> fields, real volumes) against the upgraded build, before deploying. Tick each box,
> note the tester + date. Anything that fails → open an issue and link it here.

Legend: `[ ]` not tested · `[x]` passed · `[!]` failed (link issue)

---

## 0. Critical prerequisites (do first — everything else depends on these)

- [ ] **Encrypted fields decrypt correctly.** Open a family/individu created *before*
      the upgrade and confirm encrypted fields are still readable (not garbage / not
      errors). Fields encrypted via `django_cryptography`: postal address, email,
      SEPA IBAN / BIC / ICS code, bank account numbers, mail-server password/host/user.
      → This validates that the cryptography replacement package uses the **same key
      derivation from `SECRET_KEY`**. If this fails, STOP — do not deploy.
- [ ] Save a record with an encrypted field, reload it, confirm the new value persists
      and re-reads correctly (write path, not just read path).
- [ ] Log in as an existing administrator, an existing "utilisateur" (bureau), and an
      existing portail family account — all with pre-upgrade password hashes.
- [ ] Static files load (CSS/JS/images present, no 404s) — the `STORAGES` /
      manifest-storage migration is exercised here. Check both `administrateur/` and
      `utilisateur/` and the portail.

---

## 1. Authentication & security

- [ ] Login / logout for each role (admin, bureau, portail family).
- [ ] django-axes brute-force lockout: fail login N times → account/IP locked →
      lockout page (`/locked`) shown → cooloff releases it.
- [ ] Password expiry flow (`DUREE_VALIDITE_MDP`): expired password forces reset.
- [ ] Password reset by email (token email arrives, link works, sets new password).
- [ ] Turnstile captcha on the portail login (if `TURNSTILE_ENABLE=True` in prod).
- [ ] CSP headers present and pages render (maps, Google fonts, YouTube embeds,
      Turnstile challenge, jsdelivr/cdnjs scripts all load — check browser console for
      CSP violations). django-csp 4.x changed the settings format — verify nothing is
      silently blocked.
- [ ] Session behaviour: "remember me", session timeout, X-Frame-Options / clickjacking.

## 2. Families & individuals (fiche_famille / fiche_individu / individus)

- [ ] Create a new family, add individuals, set relationships.
- [ ] Edit a family with encrypted fields (address, bank details) and save.
- [ ] Photo upload + resize (django-resized → WEBP conversion, 1024px cap) displays.
- [ ] Document upload (allowed types, 10 MB limit enforced).
- [ ] Summernote rich-text editors (notes, portail texts): toolbar loads, image insert,
      content saves and renders.
- [ ] Select2 dropdowns (autocomplete search) work across forms.
- [ ] DataTables lists (families, individuals): pagination, search, sort, per-column
      filters, row actions.

## 3. Activities & registrations (consommations / parametrage activités)

- [ ] Create/configure an activity, groups, units, rates (tarifs).
- [ ] Register an individual, fill the consumption grid (grille), save.
- [ ] Bulk registration / calendar operations.
- [ ] Waitlist / capacity limits behave.

## 4. Billing (facturation)

- [ ] Generate invoices for a period (batch run over many families).
- [ ] Invoice PDF: open in a real PDF reader — layout, totals, logo, barcode
      (pystrich/reportlab) all correct.
- [ ] Email invoices to families (see §8 email).
- [ ] Credit notes / avoirs, re-billing, deletion of a billing run.
- [ ] Quotient familial / CAF rate calculations produce the same numbers as pre-upgrade.

## 5. Payments & gateways (reglements)

> External services — cannot be automated. Use gateway sandbox/test credentials.

- [ ] Record a manual payment (règlement), allocate to invoices, print receipt.
- [ ] SEPA direct debit (prélèvement): generate the SEPA XML file → validate it opens
      in the bank tool / passes an ISO 20022 validator. IBAN/BIC come from **encrypted**
      fields — confirm they are correct in the file.
- [ ] Online payment via each configured gateway: **Stripe**, **eopayment** (PayFiP /
      other), **HelloAsso** — run a sandbox transaction end-to-end, confirm callback /
      webhook marks the payment as received.
- [ ] TPE / card terminal token flow (PaiementTPE / TokenHA) if used.
- [ ] Refund / cancellation path.

## 6. Accounting (comptabilite)

- [ ] Ventilation / journal entries generated from payments.
- [ ] Accounting exports (check the exported file opens correctly in target software).

## 7. Documents: PDF, Word mail-merge, exports

- [ ] Word mail-merge (docx-mailmerge2, `utils_fusion_word`): generate a document from a
      Word template with merge fields → open in Word/LibreOffice, fields filled.
- [ ] Configurable Word templates (parametrage/modeles_word) upload + generate.
- [ ] All PDF outputs (attestations, receipts, invoices, lists): open each in a real
      reader — fonts, accents (French), tables, images render.
- [ ] Excel/CSV exports (xlsxwriter/xlrd): open in Excel/LibreOffice, encoding + accents OK.

## 8. Email (django-anymail + editeur_emails)

- [ ] Send a single email from the email editor (summernote HTML body).
- [ ] Bulk email send to a family list.
- [ ] Anymail ESP delivery (real ESP in prod config): message actually delivered,
      tracking/webhook works.
- [ ] Attachments (invoice PDF) attach and open.
- [ ] Admin error emails (`mail_admins`) still fire on a 500 in production.

## 9. Family portal (portail)

- [ ] Family self-registration / account creation flow.
- [ ] Portail login (+ Turnstile if enabled).
- [ ] View & edit family/individual info from the portail (writes to encrypted fields).
- [ ] Online registration to an activity.
- [ ] Online payment from the portail (ties into §5 gateways).
- [ ] Document consultation / upload from the portail.
- [ ] Messaging / notes between structure and family.
- [ ] (See existing scenarios in `noethysweb/tests/portail/` — extend, don't force-green.)

## 10. Backups & scheduled jobs

- [ ] `outils/views/sauvegarde_creer` — create a manual backup (django-dbbackup).
- [ ] Dropbox backup: refresh-token flow (`get_refresh_token_dropbox`) + a backup
      actually lands in Dropbox.
- [ ] Restore a backup into a scratch DB and confirm integrity (esp. encrypted fields).
- [ ] django-crontab jobs (`noethysweb/cron.py`): re-add crontab
      (`manage.py crontab add`) and confirm each scheduled job runs (reminders, auto
      backups, etc.).

## 11. Tools & admin (outils / aide / collaborateurs)

- [ ] Django admin site loads and CRUD works for a couple of models.
- [ ] Collaborateurs (staff) management.
- [ ] Aide / help pages render.
- [ ] Any import tools (import familles/individus) run to completion.
- [ ] Multi-select fields (django-multiselectfield) save/read correctly.

## 12. Cross-cutting / regressions to eyeball

- [ ] French localisation: dates as `dd/mm/YYYY`, decimal comma, phone formatting
      (`USE_L10N` was removed in Django 5.0 — formats must still be French).
- [ ] Timezone: `USE_TZ=False` — datetimes display as before (no UTC shift).
- [ ] File upload widget (django-upload-form) drag/drop + size validation.
- [ ] Plugins (if any enabled in prod) load and their URLs resolve.
- [ ] No deprecation warnings / errors in `debug.log` after a normal browsing session.
- [ ] Performance sanity: large DataTables lists and billing runs are not dramatically
      slower.

---

## Sign-off

| Area | Tester | Date | Result |
|------|--------|------|--------|
| Critical prerequisites (§0) | | | |
| Auth & security (§1) | | | |
| Families/individuals (§2) | | | |
| Activities (§3) | | | |
| Billing (§4) | | | |
| Payments (§5) | | | |
| Accounting (§6) | | | |
| Documents (§7) | | | |
| Email (§8) | | | |
| Portail (§9) | | | |
| Backups/cron (§10) | | | |
| Tools/admin (§11) | | | |
| Cross-cutting (§12) | | | |
