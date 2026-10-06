# Architecture

`dotmatics_api` exports `Browser`, `Inventory` and `AuthenticationError`.
`base.py` implements URL validation, token exchange, endpoint construction and
two persistent Requests sessions. The normal session permits read retries for
GETs; the query session also permits read retries for explicitly read-only POSTs.
Connect failures have separate bounded retries. `close()` releases both pools;
context managers call it automatically.

Browser owns `/browser/api` wire formats, error-body parsing, project/datasource
name-to-ID caches, and a thread pool for internal parallel GETs. `lazy=True`
defers metadata reads until needed. Inventory owns `/inventory/api` endpoint
families and their differing status-code, file and payload conventions. Both
authenticate under `/browser/api`, through separate authentication endpoints.

Internal Browser parallel requests share its sessions without modifying session
configuration. Configure a client before using it. Concurrent application-level
mutation of a client, its caches, headers or sessions is unsupported; create
separate clients for independent workers. This release does not promise general
Requests Session thread safety.

The SQLite example is separate from the installed library. `schema.py` defines
the fictional views, parsers and SQLite constraints; `mirror.py` implements
bounded enumeration, explicit-ID reads and staging-file publication;
`incremental.py` applies an overlapping audit window in a single transaction.
`demo.py` provides synthetic Browser replies for offline demonstrations and tests.

The example owns its schema contract. It is not a general-purpose ORM, scheduler,
cloud pipeline or server-side snapshot mechanism. Its limitations are described
in its README. Vendor API descriptions are not bundled; consult your own
instance's exported description as described in the documentation.
