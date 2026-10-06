# Dotmatics API

Python clients for the Dotmatics Browser and Inventory REST APIs, with original
[API behavior notes](docs/api-behavior.md) and a runnable
[SQLite mirror example](examples/sqlite_mirror/README.md).

Shared by Kimia Therapeutics as a community reference and starter-code release.
The goal is to share practical learnings and help others build their own integrations.

## Project status

This repository is not actively maintained. It is provided as-is, with no planned
ongoing updates, support, security fixes or compatibility testing. Issues and pull
requests may not receive a response or be merged. We encourage you to fork, adapt
and maintain the code for your own needs.

The behavior notes describe historical findings, not a current server compatibility
guarantee. Validate the code, dependencies and deployment-specific assumptions
before production use. See [security considerations](SECURITY.md).

Requires Python 3.11 or newer. Runtime dependencies are Requests and urllib3;
SOCKS proxies use the optional `proxy` extra. A live deployment requires your own
licensed instance, API-enabled account, and appropriate permissions. This client
does not provide a server or deploy the fictional example views.

## Install

From a repository clone:

```sh
python -m pip install -e '.[dev,proxy]'
python -m pytest
python -m examples.sqlite_mirror.demo demo.db
```

For a tagged GitHub release (once that tag is published):

```sh
python -m pip install 'dotmatics-api @ git+https://github.com/kimiatx-oss/dotmatics-api.git@v2.0.0'
```

Distribution is through GitHub; no PyPI upload is configured. Examples and tests
run from a clone and are not included in the installed client wheel.

## Quickstart

Set `DOTMATICS_INSTANCE`, `DOTMATICS_USER` and `DOTMATICS_PASSWORD` in your environment.
Keep credentials out of source files and shell history. The URL has no default.

```python
import os
from dotmatics_api import Browser, Inventory

credentials = dict(
    user=os.environ["DOTMATICS_USER"],
    password=os.environ["DOTMATICS_PASSWORD"],
    dotmatics_instance=os.environ["DOTMATICS_INSTANCE"],
)
with Browser(**credentials) as browser:
    print(sorted(browser.projects_by_name))
    # Replace these fictional mappings with your deployment's names.
    rows = browser.fetch_data(
        project="Registry", datasources=["DEMO_COMPOUND_VW"], ids=["1"]
    )

with Inventory(**credentials) as inventory:
    version = inventory.get_about()
```

Use `token=...` instead of `password=...` with an existing token. Browser and
Inventory authenticate through different endpoints; do not assume their tokens
are interchangeable. Tokens are not automatically renewed. URL validation accepts
custom hosts and ports, normalizes a trailing `/`, and rejects deployment subpaths,
embedded credentials, query strings and fragments. Use HTTPS on live deployments;
certificate verification remains enabled.

GETs and explicitly designated read-only POST queries retry dropped connections.
Mutating requests do not retry ambiguous read failures. See
[transport and authentication notes](docs/api-behavior.md#transport-and-authentication)
for retry bounds, exception behavior and token lifetime.

## Documentation

- [Observed API behavior and practical limits](docs/api-behavior.md)
- [Inventory model and transport notes](docs/inventory-notes.md)
- [Exporting your instance's Inventory OpenAPI description](docs/regenerating-the-openapi-spec.md)
- [Architecture](ARCHITECTURE.md)
- [Adapting the code and live test configuration](CONTRIBUTING.md)
- [Security considerations](SECURITY.md)

Server module and version compatibility varies; a passing synthetic test is
evidence about this client, not a certification of a particular deployment.

Not affiliated with, endorsed by, or sponsored by Dotmatics or Revvity.
“Dotmatics” is a trademark of its respective owner.

Licensed under [BSD-3-Clause](LICENSE).
