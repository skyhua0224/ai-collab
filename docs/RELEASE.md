# Release Guide

This guide outlines the release workflow for publishing to GitHub and PyPI.

## 1) Release Requirements

Before creating a release, confirm:

1. Documentation is updated (`README.md`, `README_EN.md`, `QUICKSTART.md`, `docs/USAGE.md`)
2. Package metadata is correct (`pyproject.toml`, `ai_collab/__init__.py`)
3. Test suite passes
4. Build and metadata checks pass

## 2) Local Validation

### Install build tools

```bash
python3 -m pip install --upgrade build twine
```

### Run tests

```bash
pytest -q
```

### Build and validate artifacts

```bash
python3 -m build
python3 -m twine check dist/*
```

Expected result:

1. Wheel and sdist are generated
2. `twine check` returns `PASSED`

## 3) Git Release Preparation

If the repository is not initialized:

```bash
git init
git branch -M main
```

Create a release commit and tag:

```bash
git add .
git commit -m "chore(release): prepare v0.1.0"
git tag -a v0.1.0 -m "v0.1.0"
```

## 4) Publish to GitHub

```bash
git remote add origin git@github.com:<your-account>/ai-collab.git
# or
# git remote add origin https://github.com/<your-account>/ai-collab.git

git push -u origin main
git push origin v0.1.0
```

Then create a GitHub Release from the `v0.1.0` tag.

## 5) Publish to PyPI

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-xxxxxxxxxxxxxxxx
python3 -m twine upload dist/*
```

Optional staged release to TestPyPI:

```bash
python3 -m twine upload --repository testpypi dist/*
```

## 6) GitHub Actions

Included workflows:

1. `.github/workflows/ci.yml`
2. `.github/workflows/publish-pypi.yml`

Required secrets:

1. `PYPI_API_TOKEN`
2. `TEST_PYPI_API_TOKEN`

## 7) Post-release Verification

```bash
python3 -m venv /tmp/ai-collab-verify
source /tmp/ai-collab-verify/bin/activate
python3 -m pip install -U pip
python3 -m pip install ai-collab
ai-collab --help
ai-collab run --help
```

## 8) Hotfix Policy

1. Never overwrite published artifacts
2. Release a patch version (`vX.Y.Z+1`) for fixes
3. Document fixes and migration notes in release notes
