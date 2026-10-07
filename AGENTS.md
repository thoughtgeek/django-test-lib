# Instructions for agents

This is a Django 5.1 app (the MDN "Local Library" tutorial). Facility runs it in a workspace.

## Python and tooling

The workspace image has only a bare `python3` (no `python`, no `pip`, no Django on the default
PATH). The project's real interpreter is the virtual environment in the repository root:

    .venv/bin/python

Always use `.venv/bin/python` (for example `.venv/bin/python manage.py test`). Do not use
`python`, `python3`, or `pip` directly. `uv` is installed under
`/workspace/.facility/home/.local/bin`; add it to PATH if you need it.

## Before running tests

`locallibrary/settings.py` uses WhiteNoise's `CompressedManifestStaticFilesStorage`. Without a
static manifest, about half the tests fail with `Missing staticfiles manifest entry`. Run this first,
and again after any change under `catalog/static/`:

    .venv/bin/python manage.py collectstatic --noinput

## Checks

    .venv/bin/python manage.py collectstatic --noinput
    .venv/bin/python manage.py check
    .venv/bin/python manage.py test

All 40 tests pass on a clean checkout. Do not skip, weaken or delete tests to get a pass.

## The dev server

Facility's `start` command already launches `manage.py runserver` in the background on port 8000.
Do not start a second one. Check it with `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/`
(a 301 redirect to `/catalog/` is normal). Server output is in `/tmp/runserver.log`.

## Conventions

- Commit subjects are Conventional Commits (`feat:`, `fix:`, `docs:`, ...).
- Never commit `db.sqlite3`, `.venv/` or `staticfiles/`.
- Do not merge pull requests.
