Sacadoc
==================
https://sacadoc.flambeaux.org/utilisateur/ -> Espace directeurs
https://sacadoc.flambeaux.org/ -> Espace famille
Python 3.11

## Tests

This project uses `pytest` for testing.

```bash
# Run the full test suite
pytest

# Run a single test file
pytest noethysweb/tests/parametrage/test_ajout_organisateur.py -v

# Run a single test by name
pytest noethysweb/tests/parametrage/test_ajout_organisateur.py::test_name -v
```

The test suite uses `--reuse-db` by default (configured in `pytest.ini`), so the test database schema is created once and reused across runs for speed.
