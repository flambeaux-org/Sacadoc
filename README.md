Sacadoc
==================
https://sacadoc.flambeaux.org/utilisateur/ -> Espace directeurs
https://sacadoc.flambeaux.org/ -> Espace famille
Python 3.11

## Tests

This project uses `pytest` for testing. All commands must be run from the `noethysweb/` subdirectory.

```bash
cd noethysweb

# Run the full test suite
pytest

# Run a single test file
pytest tests/parametrage/test_ajout_organisateur.py -v

# Run a single test by name
pytest tests/parametrage/test_ajout_organisateur.py::test_name -v
```

The test suite uses `--nomigrations --reuse-db` by default (configured in `pyproject.toml`), so the test database schema is created once and reused across runs for speed.
