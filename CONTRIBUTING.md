# Adapting and contributing

This is an unmaintained community reference and starter-code release. Forks and
adaptations are welcome under the BSD-3-Clause license. There is no commitment to
review issues or pull requests, merge contributions, provide support or publish
future releases. For changes you need, maintain them in your own fork rather than
depending on an upstream response.

The guidance below is for people developing and validating their own adaptations.

## Development setup

Install and test from a clone using Python 3.11–3.14:

```sh
uv sync --all-extras
uv run --no-sync pytest
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv build
sh scripts/check_no_internal_refs.sh
```

Dependency installation/builds may need network. Default tests require no external
network, credentials or live server. `transport` tests bind a loopback HTTP server
to exercise real retry behavior; they never connect to a deployment. Default
testpaths include both unit and example tests. Fixtures use paths relative to
their source files, so tests can run from other directories.

## Live tests

Select live tests explicitly:

```sh
uv run --no-sync pytest tests/integration -m integration -rs
```

Set `DOTMATICS_INSTANCE`, `DOTMATICS_USER` and `DOTMATICS_PASSWORD` or
`DOTMATICS_TOKEN`. Optional `DOTMATICS_PROXY` configures a SOCKS proxy. No `.env`
file is automatically loaded and no deployment hostname is inferred.

Browser query tests additionally need `DOTMATICS_TEST_PROJECT`,
`DOTMATICS_TEST_DATASOURCE`, `DOTMATICS_TEST_COLUMN` and `DOTMATICS_TEST_VALUE`.
The test runs an equals query and fetches its returned IDs. Missing deployment
configuration causes an explicit skip.

Mutating tests require a dedicated isolated deployment and
`DOTMATICS_TEST_MUTATIONS=isolated-test-instance`. Studies lifecycle tests also
require `DOTMATICS_TEST_PROTOCOL_ID` for a dedicated test protocol. Upload tests
use a synthetic aspirin structure; uploaded temporary files are left to the
deployment's retention policy and no persistent compound registration is performed.
Inventory tests create/read/delete run-specific objects and clean up only IDs
created by their own run. They never sweep all `itest-` names or clear unrelated
relationships. Killed processes or creates with no returned ID may require manual
cleanup; investigate cleanup failures before another run. No config imports are tested.

The live mirror test requires the documented fictional views and
`DOTMATICS_TEST_DEMO_SCHEMA=configured`. It writes only a temporary local SQLite
file. Record server versions/modules, tested/skipped families, configuration and
cleanup outcomes with live test results. A skipped family is not verified coverage.

## Documentation and releases in your fork

Use synthetic data in tests, issue reports and examples. Do not commit instance
exports, databases, compound structures from private registries, credentials,
vendor API descriptions or internal deployment configuration. Claims about server
behavior should identify supporting evidence and unknowns; a mock is not a server
observation. Add a regression test for a meaningful failure mode.

Before distributing an adaptation, run the Python matrix, wheel/sdist installation
checks, default suite and disclosure/secret scans, then inspect docs and artifacts.
Keep the
`Private :: Do Not Upload` classifier while distribution is GitHub-only. There is
no automated publishing workflow. Tag reviewed releases with semantic versions;
constructor API breaks require a major version. If you maintain a public fork,
establish your own support policy and private security-reporting channel, and
confirm publishing rights and copyright attribution. This repository does not
provide ongoing fixes or a monitored support channel; see [SECURITY.md](SECURITY.md).
