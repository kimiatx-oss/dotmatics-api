"""Integration tests for dotmatics_api.inventory.Inventory.

These hit a live Dotmatics Inventory instance using the credentials in the
environment (see tests/integration/conftest.py). They are marked ``integration``
and skipped by default.

Coverage goal: exactly one endpoint per endpoint family.
  * Read-shaped families are exercised with a safe GET (or an inherently
    non-mutating POST compute, e.g. the calculator / structure renderers).
  * Config-CRUD families that support it are exercised with a create -> read ->
    delete round-trip whose payload is cloned from an existing record, with
    teardown in a ``finally`` block so nothing is left behind.

Payloads for CRUD round-trips are cloned from an existing record where one
exists, else supplied by synthetic fallback builders. Cleanup is limited to IDs
created by the current run; interrupted processes may leave records needing manual cleanup.

Policy: fail-hard, relaxed from analysis of live runs. A few families are
exercised read-only because create/delete is not cleanly reversible:
  * custom_fields / location_types / layout_well_types — no id returned on
    create, or the cloned record inherits links / 500s, so testing them
    read-only avoids orphaning data.

storage_types and configuration_staging get bespoke tests (not the clone
helper): a StorageType is backed by a saved Layout, and configuration/staging's
create endpoint is a non-mutating export (upload is import-only file I/O).
"""

import uuid

import pytest

pytestmark = pytest.mark.integration

# Unique-ish suffix so cloned records don't collide with real data or each other.
_SUFFIX = uuid.uuid4().hex[:8]


# ---------------------------------------------------------------------------
# Helpers for the clone-based CRUD round-trips
# ---------------------------------------------------------------------------


def _extract_items(listing):
    """Pull the list of records out of a list or paginated-dict response."""
    if isinstance(listing, list):
        return listing
    if isinstance(listing, dict):
        for key in ("data", "items", "content", "results", "list"):
            value = listing.get(key)
            if isinstance(value, list):
                return value
    return []


def _extract_id(obj):
    """Pull the identifier out of a create response (object or scalar)."""
    if isinstance(obj, dict):
        for key in ("id", "ID", "Id"):
            if key in obj:
                return obj[key]
        if isinstance(obj.get("data"), dict):
            return _extract_id(obj["data"])
        return None
    return obj


def _clone_payload(item):
    """Build a create payload from an existing record: drop its id, rename it."""
    payload = {k: v for k, v in item.items() if k.lower() != "id"}
    for key in ("name", "label", "title", "displayName"):
        if isinstance(payload.get(key), str):
            payload[key] = f"itest-{_SUFFIX}-record"
            break
    return payload


# ---------------------------------------------------------------------------
# Read-shaped families: one safe call each
# ---------------------------------------------------------------------------


def test_version_info(inventory):
    assert inventory.get_about() is not None


def test_user(inventory):
    assert isinstance(inventory.get_user_profile(), dict)


def test_users_groups(inventory):
    assert isinstance(inventory.get_groups(), dict)


def test_settings(inventory):
    assert inventory.get_settings() is not None


def test_units(inventory):
    assert inventory.get_units() is not None


def test_containers(inventory):
    assert isinstance(inventory.get_containers_list(is_disabled=False), dict)


def test_container_cycles(inventory):
    containers = _extract_items(inventory.get_containers_list(is_disabled=False))
    if not containers:
        pytest.skip("no containers available to query cycles for")
    assert inventory.get_container_cycles(_extract_id(containers[0])) is not None


def test_plates(inventory):
    assert isinstance(inventory.get_plates(), dict)


def test_search(inventory):
    assert inventory.quick_search("test") is not None


def test_calculator(inventory):
    # Valid operations (per the server's 400 validator) are SUM, DIV, MULTIPLY, SUBTRACT.
    assert inventory.calculate(2, 3, "SUM") is not None


def test_cart(inventory):
    assert inventory.get_cart() is not None


def test_notifications(inventory):
    assert inventory.get_notifications() is not None


def test_import_history(inventory):
    assert isinstance(inventory.get_import_history(), dict)


def test_migration(inventory):
    assert inventory.get_all_migration_logs() is not None


def test_integration(inventory):
    assert inventory.integration_get_units() is not None


def test_usergroup_template(inventory):
    template = inventory.get_usergroup_csv_template()
    assert isinstance(template, bytes) and len(template) > 0


def test_layouts(inventory):
    # Layout creation needs grids + well types wired up, so the read endpoint
    # is the representative for this family.
    assert isinstance(inventory.get_layouts(), dict)


def test_labvoice(inventory):
    # Needs a real barcode; a dummy correctly 404s, so derive one from an
    # existing container (skip if this instance has none with a barcode).
    containers = _extract_items(inventory.get_containers_list(is_disabled=False))
    barcodes = [
        c.get("barcode") for c in containers if isinstance(c, dict) and c.get("barcode")
    ]
    if not barcodes:
        pytest.skip("no container barcode available to look up via Labvoice")
    assert inventory.get_labvoice_container(barcodes[0]) is not None


# Read-only representatives for CRUD families that are not cleanly reversible:
#   custom_fields: create_field returns no id (typed -> None), so no round-trip.
#   location_types: a cloned type inherits "permitted location types" links, and
#                   delete is rejected ("Remove all 'Permitted location types'
#                   before deletion") — round-trips would orphan data.
#   layout_well_types: create returns 500 on a cloned payload.


def test_custom_fields(inventory):
    assert inventory.get_fields() is not None


def test_location_types(inventory):
    assert isinstance(inventory.get_location_types(), dict)


def test_layout_well_types(inventory):
    assert isinstance(inventory.get_layout_well_types(), dict)


def test_depictor(inventory):
    image = inventory.render_barcode("ITEST-123")
    assert isinstance(image, bytes) and len(image) > 0


def test_samples_render_smile(inventory):
    # SmileDTO's field is 'smile' (not 'smiles'); the endpoint returns the
    # rendered depiction (SVG) as raw bytes.
    svg = inventory.render_smile({"smile": "CCO"})
    assert isinstance(svg, bytes) and len(svg) > 0


def test_configuration_staging(inventory):
    # create_configuration is a non-mutating export: it returns a config bundle
    # for the requested staged types (enum incl. UNIT/CONDITION/...). The other
    # endpoint, upload, is import-only multipart file I/O.
    bundle = inventory.create_configuration(["UNIT"])
    assert isinstance(bundle, bytes) and len(bundle) > 0


def test_storage_types(inventory, mutation_opt_in):
    # A StorageType is backed by a saved Layout (create_storage_type embeds a
    # layoutDTO that must reference a persisted layout, else the server 500s with
    # 'layout.db.load'). So: create a layout WITHOUT its auto storage type, then
    # a storage type referencing that layout. Teardown deletes the storage type
    # first (it blocks layout deletion), then the layout.
    grids = _extract_items(inventory.get_layout_grids())
    well_types = _extract_items(inventory.get_layout_well_types())
    if not grids or not well_types:
        pytest.skip(
            "need an existing layout grid and well type to build a storage layout"
        )

    grid = grids[0]
    last_row = chr(ord("A") + int(grid.get("numOfRows", 8)) - 1)
    last_col = int(grid.get("numOfCols", 12))
    layout_payload = {
        "name": f"itest-{_SUFFIX}-layout",
        "type": "SINGLE_POINT",
        "active": True,
        "layoutGrid": grid,
        "mixtureType": "MIX_IN_WELLS",
        "sampleDropWells": 0,
        "wellConfigurations": [
            {
                "fromCoordinate": "A1",
                "toCoordinate": f"{last_row}{last_col}",
                "wellType": well_types[0],
                "direction": "HORIZONTAL",
                "replicateType": "NONE",
                "replicates": 1,
                "dozes": 1,
                "override": False,
            }
        ],
        "wellPropertyConfigurations": [],
    }

    layout_id = _extract_id(
        inventory.create_layout(layout_payload, create_storage_type=False)
    )
    storage_id = None
    try:
        saved_layout = inventory.get_layout(layout_id)
        created = inventory.create_storage_type(
            {
                "name": f"itest-{_SUFFIX}-storage",
                "active": True,
                "layoutDTO": saved_layout,
            }
        )
        storage_id = _extract_id(created)
        assert storage_id is not None
        assert inventory.get_storage_type(storage_id) is not None
    finally:
        if storage_id is not None:
            inventory.delete_storage_type(storage_id)
        inventory.delete_layout(layout_id)


# ---------------------------------------------------------------------------
# Config-CRUD families: create -> read -> delete round-trip, with teardown.
#
# Each family supplies a payload one of two ways:
#   * clone an existing record from its list endpoint (preferred — matches the
#     instance's own conventions), or
#   * fall back to a minimal payload built from synthetic fallback builders when the instance has no record to clone.
# A family with neither an existing record nor a fallback skips gracefully.
# ---------------------------------------------------------------------------


def _concentration_scheme_payload():
    # ConcentrationSchemeDTO: only `name` is required; concentrations is a number array.
    return {
        "name": f"itest-{_SUFFIX}-concentration",
        "description": "integration test scheme",
        "concentrations": [1.0, 10.0, 100.0],
    }


def _plate_type_payload():
    # PlateTypeDTO: only `name` is required; the string fields below take values
    # from the plate-type reference endpoints (colors/bottoms/materials/...).
    return {
        "name": f"itest-{_SUFFIX}-plate",
        "shortName": "IT",
        "material": "Polystyrene",
        "colour": "Clear",
        "bottom": "Flat",
    }


CRUD_FAMILIES = [
    # (id, list_m, create_m, get_m, delete_m, fallback_payload_builder)
    (
        "conditions",
        "get_conditions",
        "create_condition",
        "get_condition",
        "delete_condition",
        None,
    ),
    (
        "concentration_schemes",
        "get_concentration_schemes",
        "create_concentration_scheme",
        "get_concentration_scheme",
        "delete_concentration_scheme",
        _concentration_scheme_payload,
    ),
    (
        "templates",
        "get_templates",
        "create_template",
        "get_template",
        "delete_template",
        None,
    ),
    (
        "container_types",
        "get_container_types",
        "create_container_type",
        "get_container_type",
        "delete_container_type",
        None,
    ),
    (
        "sample_type_categories",
        "get_sample_type_categories",
        "create_sample_type_category",
        "get_sample_type_category",
        "delete_sample_type_category",
        None,
    ),
    (
        "plate_types",
        "get_plate_types",
        "create_plate_type",
        "get_plate_type",
        "delete_plate_type",
        _plate_type_payload,
    ),
    (
        "layout_grids",
        "get_layout_grids",
        "create_layout_grid",
        "get_layout_grid",
        "delete_layout_grid",
        None,
    ),
]


@pytest.mark.parametrize(
    "list_m,create_m,get_m,delete_m,fallback",
    [(c[1], c[2], c[3], c[4], c[5]) for c in CRUD_FAMILIES],
    ids=[c[0] for c in CRUD_FAMILIES],
)
def test_crud_roundtrip(
    inventory, mutation_opt_in, list_m, create_m, get_m, delete_m, fallback
):
    items = _extract_items(getattr(inventory, list_m)())
    if items:
        payload = _clone_payload(items[0])
    elif fallback is not None:
        payload = fallback()
    else:
        pytest.skip(
            f"no existing records from {list_m}() and no synthetic fallback payload"
        )

    created = getattr(inventory, create_m)(payload)
    new_id = _extract_id(created)
    assert new_id is not None, (
        f"could not determine new id from {create_m} response: {created!r}"
    )

    try:
        assert getattr(inventory, get_m)(new_id) is not None
    finally:
        getattr(inventory, delete_m)(new_id)
