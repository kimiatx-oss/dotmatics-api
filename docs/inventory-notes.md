# Inventory notes

These original notes derive from June 2026 client development and accompanying
tests on an anonymized deployment. Server version/configuration was not recorded.
They were reviewed against the local client in October 2026; live reproduction
on a public release candidate remains deployment-specific validation.

## Storage types and layouts

The development notes record a server failure with `layout.db.load` when creating
a StorageType with an unsaved Layout. Save the layout first using
`create_layout(payload, create_storage_type=False)`, then pass the returned saved
layout in `layoutDTO` when creating the storage type. Delete a created storage
type before deleting its layout. The live storage-type test exercises this order
only when mutation testing is explicitly enabled.

## Depictors

GET renderers such as `render_barcode` and `render_qrcode` send flat query parameters
(`value`, `height`, `width`), rather than `depictorDTO.*`. `render_smile` returns raw
body bytes, normally SVG, rather than JSON. Unit tests cover the wire format;
rendered output and endpoint availability vary by installed server modules.

## Configuration staging

`create_configuration` is named like a CRUD operation but exports a configuration
bundle as bytes. `upload_configuration` imports a bundle and can change server
configuration; its `isCheckMode` flag requests validation mode. Verify server
semantics before using imports. The integration suite does not import bundles or
perform other configuration-wide changes.

## Endpoint coverage and cleanup

The client includes many Inventory endpoint families. Synthetic tests cover
request construction and return handling; they cannot establish live availability
on every deployment. The live suite reports skips when required records or
modules are absent. Record tested families and server versions when evaluating
compatibility.

Mutating integration tests use run-specific names and track the IDs returned by
their own creates. Cleanup never sweeps all names beginning with `itest-`, and
never clears relationships on an unrelated existing record. A process killed
before it receives a create response may leave an object needing deliberate manual
cleanup. Relationship-heavy cloned payloads can fail cleanup; use an isolated
deployment and inspect reported failures before another run.
