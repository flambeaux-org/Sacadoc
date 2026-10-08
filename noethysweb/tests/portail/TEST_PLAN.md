# Portail test plan & progress tracker

The `portail` app is the family self-service portal (`request.user.categorie == "famille"`)
— the only interface exposed to external non-staff users, so the most security-sensitive
surface of Noethysweb. ~70 routes, currently only one test (`test_signin.py`).

**Goal:** comprehensive coverage of every page and functionality.
**Approach:** layered — fast Django-test-client **integration** tests for breadth +
**Playwright E2E** for critical real-browser flows.
**Out of scope:** payment gateway internals (Payzen/PayFip/HelloAsso/Stripe/TPE return
handlers, IPN callbacks). Billing/receipt *pages* are still covered.

> ⚠️ **Tests are not expected to all pass on first write.** There are known bugs in the
> portail. A failing test may be surfacing a real bug — when that happens, record it under
> "Bugs found" below and leave the test failing (or `xfail` with a reference) rather than
> weakening the assertion to force green. The point of this suite is partly to *find* these.

> **Status: implemented.** 229 tests pass, 5 `xfail(strict)` mark the 4 documented bugs.
> Test files use a `test_portail_*` prefix because pytest's prepend import mode requires
> globally-unique module basenames (a bare `test_auth.py` collides with
> `tests/integration/test_auth.py`). No `__init__.py` under `tests/portail/` — that would
> shadow the real `portail` app package.

---

## Phase 0 — Foundations (unblocks everything) ✅

- [x] Expanded `tests/unit/factories.py`: `IndividuFactory`, `RattachementFactory`,
      `ActiviteFactory`, `GroupeFactory`, `InscriptionFactory`, `TypePieceFactory`,
      `PieceFactory`, `PortailMessageFactory`, `SondageFactory`, `FactureFactory`,
      and `create_famille_complete()` helper (famille + titulaire individu + child).
      (`ReglementFactory`/`PrestationFactory` skipped — heavy FK graph; billing covered
      via empty-state + `Facture`.)
- [x] Added `tests/portail/conftest.py`: `famille_user`, `other_famille`, `staff_user`,
      `organisateur` (pk=1), `logged_client`, autouse `clear_cache`.
      (`PortailParametre` seeding unnecessary — `utils_portail.Get_dict_parametres()`
      returns working defaults.)

## Phase 1 — Authorization suite (highest priority) ✅ — `test_portail_authorization.py` (54 tests)

- [x] Unauthenticated access → redirect to `portail_connexion` (all simple + rattachement routes).
- [x] Staff user (`categorie="utilisateur"`) blocked by `CustomView.test_func()` — 403 (accueil → 302).
- [x] Cross-family isolation: family A → family B's `idrattachement` returns 403 (15 routes); own access 200.
- [x] AJAX endpoint probes — `test_portail_ajax_authorization.py` (49 tests): all 16 `@secure_ajax_portail`
      endpoints reject anonymous (403), staff (403) and non-AJAX (400); famille positive case clears the decorator.

## Phase 2 — Integration breadth (`tests/portail/integration/`) ✅

- [x] `test_portail_auth.py` — reset/done pages, inscription_famille, profil, profil_password_change, deconnexion
- [x] `test_portail_accueil.py` — dashboard render + unread-message count
- [x] `test_portail_pages.py` — render-smoke for all 13 no-arg pages + cotisations
- [x] `test_portail_renseignements.py` — all individu consulter/modifier fiches + famille fiches; identite save
- [x] `test_portail_individu_crud.py` — contacts add (POST creates) + delete (POST removes)
- [x] `test_portail_membres.py` — add child (creates Individu+Rattachement), add parent form
- [x] `test_portail_activites.py` — activites list + shows inscription, inscrire form, cotisations
- [x] `test_portail_documents.py` — documents list, piece listing, upload form, supprimer_piece (+security xfails)
- [x] `test_portail_billing.py` — facturation (empty + with Facture), reglements, payzen return pages
- [x] `test_portail_surveys.py` — sondage intro/questions/conclusion + POST saves repondant/response
- [x] `test_portail_contact.py` — contact hub + conversation (marks read), messagerie send
- [x] `test_portail_misc.py` — mentions, desinscription, album (valid code)
- [x] `test_portail_reservations.py` — reservations list, planning render + test_func authorization (no inscription / cross-family → 403)
- [x] `test_portail_wizard.py` — inscription AJAX steps: get_activites_par_structure, get_form_extra, valid_form (invalid → 400)

## Phase 3 — E2E flows (`tests/portail/e2e/`, Playwright + `auto_login_user`) ✅

- [x] `test_portail_e2e_navigation.py` — dashboard + navigate main pages, no server error
- [x] `test_portail_e2e_add_child.py` — add-child form submission creates Individu
- [x] `test_portail_e2e_edit_identite.py` — edit child identity, change persists (validation workflow)
- [x] Login/logout + registration already covered by `tests/test_login.py` and `tests/portail/test_signin.py`
- [x] `test_portail_e2e_messagerie.py` — post a message via the summernote editor
- [x] `test_portail_e2e_document_upload.py` — upload a file (file input) → Piece created
- [x] `test_portail_e2e_inscription_wizard.py` — structure→activité AJAX cascade populates the dropdown
- [x] `test_portail_e2e_planning.py` — reservation planning grid renders in-browser

## Remaining / deferred

- Planning grid **cell-toggle + Save_grille** submission (needs Unite/tariff object graph + grille JS internals) —
  the planning E2E currently verifies render only.
- Full inscription **Valid_form** happy-path (creates the demande) — needs the tariff/pieces object graph; the
  wizard tests cover the AJAX cascade and the invalid→400 path.
- `Reglement`-populated reglements page (needs ModeReglement/Payeur/CompteBancaire/ModeleImpression factories).

---

## Verification commands

```bash
uv run pytest noethysweb/tests/portail/ -v
uv run pytest noethysweb/tests/portail/integration/test_authorization.py -v
HEADLESS=1 uv run pytest noethysweb/tests/portail/e2e/ -v
uv run pytest            # full suite
uvx ruff check . && uvx ruff format --check .
```

---

## Bugs found

_Document failing tests that reveal real bugs here (route, expected vs actual, test name)._

| # | Route / area | Test | Symptom | Status |
|---|---|---|---|---|
| 1 | `portail_famille_parametres_modifier` (famille_parametres.Modifier) | `test_portail_renseignements.py::test_famille_parametres_modifier_renders` | **500 Internal Server Error.** `utils_onglets.py:27` has the `famille_parametres` onglet commented out, so `Get_onglet("famille_parametres")` returns `None` and `famille_parametres.py:37` raises `AttributeError: 'NoneType' object has no attribute 'validation_auto'`. The Consulter page works; only Modifier crashes. Fix: uncomment the onglet (or guard the `None` case). | xfail(strict) — open |
| 2 | `supprimer_piece` (documents.py:75) | `test_portail_documents.py::test_anonymous_cannot_delete_piece`, `test_cannot_delete_other_family_piece` | **Security: missing auth + ownership check.** Plain function view with no `@login_required` and no famille check — `get_object_or_404(Piece, pk)` then deletes on POST. Any anonymous user can delete any `Piece` by pk; any family can delete another family's pieces. Fix: require login + verify the piece belongs to `request.user.famille`. | 2× xfail(strict) — open |
| 3 | `supprimer_piece` GET (documents.py:81) | `test_portail_documents.py::test_confirmation_page_renders_for_owner` | **500.** GET renders `core/confirmation_suppression.html`, which does not exist anywhere → `TemplateDoesNotExist`. The confirmation page is unreachable; only direct POST works. Fix: add the template or point to an existing one. | xfail(strict) — open |
| 4 | `portail_documents_modifier` (transmettre_piece.Modifier, documents/forms `Modifier.get_queryset`) | `test_portail_documents.py::TestModifierPiece::test_cannot_open_other_family_piece` | **Security (low impact): missing ownership check.** `get_queryset` returns `Piece.objects.filter(pk=self.kwargs["pk"])` with **no famille filter**, despite a comment claiming "l'utilisateur ne peut modifier que ses propres documents". Family A can open/modify family B's piece via `/documents/modifier/<pk>/`. Impact is **metadata-only** (title/dates/individu): the edit form uses a `FileInput` widget and renders no link to the stored file, so document content is *not* exposed via this route (that is finding #5). Fix: add `famille=self.request.user.famille` to the queryset filter. | xfail(strict) — open |
| 5 | Private media serving (`MEDIA_URL=/media/`, `Piece.document` storage `get_storage("piece")`, `get_uuid_path` at `core/models.py:261`) | _Not Django-testable — infra/reverse-proxy concern, documented here only_ | **Security (high impact): unauthenticated file access.** Uploaded family documents are stored at `pieces/<uuid>.<ext>` and served directly off disk by the reverse proxy under `/media/`. Django auth never runs, so anyone with a file URL (guessed, leaked via logs/Referer/email, or shared) can download any family's documents with no login. The UUID filename is obscurity, not access control — and if nginx has `autoindex on` for the media location the UUIDs are enumerable. Fix: stop serving private files directly; route through an authenticated Django view that checks `request.user.famille` ownership and hands off via `X-Accel-Redirect` / `django-sendfile2`. | infra — open |
