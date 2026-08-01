# cluster_validator

![PyPI version](https://img.shields.io/pypi/v/prevalidate.svg)

A language-agnostic dry-run tool that users can run on a cluster before `sbatch`, that profiles their task and flags cluster-unfriendly behavior

* [GitHub](https://github.com/florence-bockting/prevalidate/) | [PyPI](https://pypi.org/project/prevalidate/) | [Documentation](https://florence-bockting.github.io/prevalidate/)
* Created by [Florence Bockting](https://florence-bockting.github.io) | GitHub [@florence-bockting](https://github.com/florence-bockting) | PyPI [@florence-bockting](https://pypi.org/user/florence-bockting/)
* MIT License

## Features

* TODO

## Documentation

Documentation is built with [Zensical](https://zensical.org/) and deployed to GitHub Pages.

* **Live site:** https://florence-bockting.github.io/prevalidate/
* **Preview locally:** `just docs-serve` (serves at http://localhost:8000)
* **Build:** `just docs-build`

API documentation is auto-generated from docstrings using [mkdocstrings](https://mkdocstrings.github.io/).

Docs deploy automatically on push to `main` via GitHub Actions. To enable this, go to your repo's Settings > Pages and set the source to **GitHub Actions**.

## Development

To set up for local development:

```bash
# Clone your fork
git clone git@github.com:your_username/prevalidate.git
cd prevalidate

# Install in editable mode with live updates
uv tool install --editable .
```

This installs the CLI globally but with live updates - any changes you make to the source code are immediately available when you run `prevalidate`.

Run tests:

```bash
uv run pytest
```

Run quality checks (format, lint, type check, test):

```bash
just qa
```

## Author

cluster_validator was created in 2026 by Florence Bockting.

Built with [Cookiecutter](https://github.com/cookiecutter/cookiecutter) and the [audreyfeldroy/cookiecutter-pypackage](https://github.com/audreyfeldroy/cookiecutter-pypackage) project template.
