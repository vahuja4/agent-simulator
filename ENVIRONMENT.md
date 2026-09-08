# Environment

- Python: 3.12.12
- Virtual environment: repository-local `.venv`
- Python manager: standalone Homebrew `uv` at `/opt/homebrew/bin/uv`
- Dependency lockfile: `requirements.lock`
- Setup: `make setup`
- Health check: `make doctor`
- Offline tests: `make test`
- Expected offline baseline: 422 passed (17 pre-existing failures remain on main; see `docs/synthesis-cutover.md` for the 2026-09-08 removal)
- Reason: Miniconda base Python 3.12.9 has a corrupted native `readline` and was abandoned after diagnosis on 2026-08-17.
