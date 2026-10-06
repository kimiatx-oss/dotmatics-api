# API behavior and client design decisions

These notes explain API gotchas that motivated the client's handling and the
SQLite mirror example's validation. Endpoint descriptions alone may not establish
ordering, completeness, retention or application-level success. Check those
assumptions when adapting the code to your own deployment.

The observations below come from deployment experience; exact server versions and
configuration are not available for every finding. They have not been reproduced
across all server versions and are not universal API guarantees. Statements about
this client's behavior describe its implementation. Synthetic tests validate our
handling, not the server's behavior.

## Truncation and row limits

By default (under the versions we developed against), the Dotmatics API server
has a configurable limit on the maximum number of rows returned in a single
request (see the admin panel on the server). As a consequence, responses may be
incomplete even when a request succeeds. Possible row boundaries identified
during integration work include 10, 100, 1,000, 25,000, 50,000 and 100,000.
These are candidate warning boundaries, not a specification or grounds
for discarding a response: a legitimate result can have exactly that many rows.

Beware! The server’s response-row cap is distinct from the request’s `limit` and
the number of supplied IDs. One requested ID can expand into many result rows.
This means that, depending on table/view design, it can be extremely difficult to
reliably guarantee that a response is complete. In particular, a successful HTTP
status does not establish completeness. Matching all requested parent IDs does not
establish that every child row was returned. Even a single-ID request may exceed the
response cap; child-level enumeration or independent counts are needed to validate
completeness. Compare expected IDs with fetched IDs, validate the expected datasource
and row shape, and shrink explicit-ID batches when omissions are detected. A short
response or empty datasource is not sufficient evidence of deletion. These
observations do not establish a universal byte-size cap or row limit.

The [example enumeration tests](../examples/sqlite_mirror/tests/test_mirror.py)
cover detectable truncation, count skew, duplicate IDs, malformed payloads and
limit saturation. No count-based heuristic can prove that both the count and
the returned ID set were not jointly truncated.

## Offset paging can duplicate or omit records

On one hosted deployment, separate offset-paged requests returned overlapping
records. This motivates the mirror example's use of primary-ID enumeration
followed by explicit-ID batches: a page offset alone does not establish that
successive requests cover distinct records.

Do not rely on stable ordering across separate offset requests unless your
deployment explicitly provides and validates that contract. Enumerate IDs first,
fetch each by value, reject duplicates before converting an ID list to a set,
and reconcile expected versus returned IDs. Changing records can still make the
extraction inconsistent over time; this approach is not a server-side snapshot.

Enumerating an experiment ID does not prove that all its result rows were fetched.
The fictional example exposes each result through an independent `RESULT_ID`
primary key. Adapting a view that returns many child rows under one parent requires
independent child counts/IDs or explicitly unverified coverage.

## Query limits and count skew

On one hosted deployment, `/query` returned only 1,000 IDs when an explicit limit
was omitted. An omitted limit therefore should not be read as "return all IDs."
Always send a positive limit for an ID enumeration. The mirror example uses a
count-only call (`limit=0`), a positive ID limit with slack, and validation of the
returned list. Slack helps detect saturation; it does not correct an inaccurate
count or guarantee a complete result.

Treat an under-reported count as a warning rather than discarding surplus IDs.
An ID list shorter than its reported count, duplicate IDs, missing fields or
saturation at the requested limit should fail extraction. Under-reporting remains
a limitation: neither the ID-list length nor the count alone proves completeness.
The example bounds enumeration and refuses oversized work; stable-key partitioning
must be implemented and validated before adapting it to larger datasets.

## GET, POST and wildcard behavior

In this client, `fetch_data` uses GET for a single ID and POST for multiple IDs.
`run_query` uses POST for multiple datasources and GET for one. These query POSTs
are designated read-only and can receive read retries. `*` is valid only on the
single-ID GET path and cannot be combined with other IDs. An omitted ID collection
uses the wildcard path.

The helpers prepare form, JSON and multipart bodies according to the endpoint;
these encodings are not interchangeable. Multipart boundaries must be generated
by Requests; callers must not manually supply a bare multipart content type.
Tests in [test_browser.py](../tests/unit/test_browser.py) cover these wire formats.

## HTTP success and application errors

HTTP 200 does not necessarily mean that the requested operation succeeded.
Browser response parsing rejects JSON bodies containing `{"status": "error"}`
even with HTTP 200. Browser helpers also accept an empty successful body as an
empty dictionary. `raw=True` returns the response without this semantic validation;
callers own that validation.

Inventory helpers use endpoint-specific success codes and return shapes. They
do not uniformly apply Browser's error-body rule. Check the endpoint's returned
payload and the deployment's description before interpreting a write as successful.
Avoid logging full exception text in shared logs: it can include source data,
generated SQL, server error text or request paths.

## IDs, names and column aliases

Compare identifiers after normalizing their representation; otherwise an integer
ID and its string form can appear to be different records. Browser lookup
dictionaries use string IDs. Distinguish an API primary ID from a displayed compound
name, batch label or child row ID: these are not interchangeable. Duplicate checks
must compare IDs for the same entity. Check an ID list before converting it to a set;
checking decoded dictionary keys cannot reveal duplicates already collapsed during
decoding.

Project-name and project-ID maps need not have equal sizes: names can collide in
a name-indexed dictionary. Use explicit project/datasource IDs when ambiguity
matters; name-based access can overwrite an
earlier entry. The example's fictional names are required to be unique.

Browser exposes `alias_column_names`; the mirror uses internal column names
(`False`) to match its explicit schema. Aliases are deployment configuration,
not portable identifiers. Verify a mapping before changing a local database.

## Transport and authentication

In this client, connect retries default to 5 and read retries to 2, with exponential
backoff. GETs and explicitly read-only query POSTs can be resent after read failures.
Mutating POST, PUT, DELETE and upload calls do not receive read retries because the
server may already have applied the operation. Connect retries apply before a request
is sent. A timeout tuple bounds individual socket phases, not the total extraction or
an entire large download. A server that keeps sending bytes may exceed the read
timeout in total duration.

Exhausted adapter retries normally surface as Requests `ConnectionError` rather
than the initial timeout type. HTTP error statuses are not retried by this client.
The [loopback transport tests](../tests/unit/test_transport.py) exercise real
dropped connections and write non-replay, not just mocked Session methods.

Constructor password authentication requests a token lifetime of 86,400 seconds;
the server decides the effective lifetime. Existing tokens can be passed directly.
There is no automatic renewal or re-authentication on expiry. Obtain a fresh token
or construct a new client when necessary. Do not silently replay a failed mutation
while renewing credentials. Browser and Inventory use different token endpoints.

## Upload retention

An upload response is not a guarantee of durable storage. Treat temporary upload
retention as deployment-specific; no universal purge schedule is established by
these observations. Attach files to the intended experiment promptly and confirm
retention with your
deployment administrator. The public client does not promise fixed purge timings.

## Audit refresh, deletions and recovery

New registrations alone do not capture edits or deletions. An audit view
must report the right entity primary key, retain deletion evidence and cover
changes to child rows. A days-based lookback is not a durable change cursor.

The fictional example replays an overlapping window idempotently and requires
explicit tombstones for missing entities. A local refresh transaction rolls back
deletions and inserts together if fetching, parsing, constraints or validation
fails. This keeps existing data intact if replacement reads fail, rather than
leaving a partially refreshed database. A full load is published only after its
staged file validates, so a failed extraction does not replace the existing mirror.

If an outage exceeds the lookback or source audit retention, enlarge the window
or rebuild. Source changes during extraction remain possible; a local transaction
cannot turn separate API requests into a consistent server snapshot.

## Schema and parsing lessons

`CREATE TABLE IF NOT EXISTS` does not alter an existing table, so the example
explicitly checks the stored schema and applies compatible additions. SQLite
appends added columns, so positional inserts can misplace values when schema
fields are inserted in the middle.
Use explicit column lists. The example permits nullable additive columns and
requires a rebuild for incompatible changes.

Replacing malformed or missing numeric data with zero or null can hide a parsing
failure or change its meaning. Distinguish missing optional data from malformed
values; the example's parsers reject malformed values unless permissive coercion
is explicitly configured. Do not assume that a field holds a scalar numeric value
without checking its actual representation: it may contain multiple values.
Preserve source semantics rather than silently nulling an unexpected representation.

Instrument date strings may use different locale orderings. The example accepts
ISO forms and requires explicit slash-date and timezone policies instead of
guessing. Boolean strings must be parsed explicitly:
Python's `bool('False')` evaluates to true. Unit conversion must name its source
unit field and reject unknown units. Unit normalization can also change numeric
range requirements in downstream stores; choose types deliberately.
