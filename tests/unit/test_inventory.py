"""Unit tests for dotmatics_api.inventory.Inventory.

All network calls are mocked; no live Dotmatics instance is required.
"""

from unittest.mock import MagicMock, patch

import pytest

from dotmatics_api.inventory import AuthenticationError, Inventory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_inventory():
    """Return an Inventory with authentication mocked out."""
    with patch.object(Inventory, "_authenticate", return_value="fake-token"):
        inv = Inventory(
            user="u",
            password="p",
            dotmatics_instance="https://demo.example.org",
        )
    return inv


def mock_response(status: int, body=None, content: bytes = b""):
    """Build a MagicMock that mimics a requests.Response."""
    r = MagicMock()
    r.status_code = status
    r.content = content if content else (b"" if body is None else b"data")
    if body is not None:
        r.json.return_value = body
    else:
        r.json.side_effect = ValueError("no json")
    r.text = str(body)
    return r


# ---------------------------------------------------------------------------
# Constructor / URL validation
# ---------------------------------------------------------------------------


class TestInit:
    def test_requires_user_and_credentials(self):
        with pytest.raises(ValueError):
            Inventory(
                user=None, password="p", dotmatics_instance="https://demo.example.org"
            )

    def test_requires_password_or_token(self):
        with pytest.raises(ValueError):
            Inventory(user="u", dotmatics_instance="https://demo.example.org")

    def test_accepts_custom_host(self):
        with Inventory(
            user="u", token="tok", dotmatics_instance="https://custom.example.org:8443"
        ):
            pass

    def test_rejects_bad_scheme(self):
        with pytest.raises(ValueError):
            Inventory(
                user="u", password="p", dotmatics_instance="ftp://demo.example.org"
            )

    def test_rejects_url_with_path(self):
        with pytest.raises(ValueError):
            Inventory(
                user="u",
                password="p",
                dotmatics_instance="https://demo.example.org/extra",
            )

    def test_token_skips_authenticate(self):
        with patch.object(Inventory, "_authenticate") as mock_auth:
            inv = Inventory(
                user="u", token="tok", dotmatics_instance="https://demo.example.org"
            )
        mock_auth.assert_not_called()
        assert inv.token == "tok"

    def test_valid_construction(self):
        inv = make_inventory()
        assert inv.user == "u"
        assert inv.token == "fake-token"


# ---------------------------------------------------------------------------
# _make_request_path
# ---------------------------------------------------------------------------


class TestMakeRequestPath:
    def setup_method(self):
        self.inv = make_inventory()

    def test_basic(self):
        url = self.inv._make_request_path("containers/1")
        assert url == "https://demo.example.org/inventory/api/containers/1"

    def test_with_query_params(self):
        url = self.inv._make_request_path("containers", {"foo": "bar"})
        assert "foo=bar" in url

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError):
            self.inv._make_request_path("/containers")

    def test_rejects_question_mark(self):
        with pytest.raises(ValueError):
            self.inv._make_request_path("containers?id=1")


# ---------------------------------------------------------------------------
# _authenticate
# ---------------------------------------------------------------------------


class TestAuthenticate:
    def test_returns_token_on_200(self):
        resp = mock_response(200, {"token": "abc123"})
        with patch("requests.Session.get", return_value=resp):
            inv = Inventory(
                user="u", password="p", dotmatics_instance="https://demo.example.org"
            )
        assert inv.token == "abc123"

    def test_raises_on_401(self):
        resp = mock_response(401, None)
        resp.text = "Unauthorized"
        with patch("requests.Session.get", return_value=resp):
            with pytest.raises(AuthenticationError):
                Inventory(
                    user="u",
                    password="p",
                    dotmatics_instance="https://demo.example.org",
                )


# ---------------------------------------------------------------------------
# _get / _post / _put / _delete routing
# ---------------------------------------------------------------------------


class TestHTTPHelpers:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_returns_json_on_200(self):
        resp = mock_response(200, {"key": "val"})
        with patch("requests.Session.get", return_value=resp):
            result = self.inv._get("some/endpoint")
        assert result == {"key": "val"}

    def test_get_raw_returns_response(self):
        resp = mock_response(200, {"k": "v"})
        with patch("requests.Session.get", return_value=resp):
            result = self.inv._get("some/endpoint", raw=True)
        assert result is resp

    def test_get_raises_on_non_200(self):
        resp = mock_response(404, None)
        resp.text = "Not found"
        with patch("requests.Session.get", return_value=resp):
            with pytest.raises(ValueError):
                self.inv._get("missing")

    def test_post_returns_json_on_200(self):
        resp = mock_response(200, {"id": 1})
        with patch("requests.Session.post", return_value=resp):
            result = self.inv._post("endpoint", {"data": 1})
        assert result == {"id": 1}

    def test_post_returns_none_on_204(self):
        resp = mock_response(204, None)
        resp.content = b""
        with patch("requests.Session.post", return_value=resp):
            result = self.inv._post("endpoint", {})
        assert result is None

    def test_post_raises_on_error(self):
        resp = mock_response(400, None)
        resp.text = "Bad Request"
        with patch("requests.Session.post", return_value=resp):
            with pytest.raises(ValueError):
                self.inv._post("endpoint", {})

    def test_put_returns_json_on_200(self):
        resp = mock_response(200, {"updated": True})
        with patch("requests.Session.put", return_value=resp):
            result = self.inv._put("endpoint", {})
        assert result == {"updated": True}

    def test_put_returns_none_on_204(self):
        resp = mock_response(204, None)
        resp.content = b""
        with patch("requests.Session.put", return_value=resp):
            result = self.inv._put("endpoint", {})
        assert result is None

    def test_delete_returns_none_on_204(self):
        resp = mock_response(204, None)
        resp.content = b""
        with patch("requests.Session.delete", return_value=resp):
            result = self.inv._delete("endpoint")
        assert result is None

    def test_delete_raises_on_error(self):
        resp = mock_response(403, None)
        resp.text = "Forbidden"
        with patch("requests.Session.delete", return_value=resp):
            with pytest.raises(ValueError):
                self.inv._delete("endpoint")


# ---------------------------------------------------------------------------
# Version / Info
# ---------------------------------------------------------------------------


class TestVersionInfo:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_version(self):
        with patch.object(self.inv, "_get", return_value="1.2.3") as m:
            result = self.inv.get_version()
        m.assert_called_once_with("version")
        assert result == "1.2.3"

    def test_get_description(self):
        with patch.object(self.inv, "_get", return_value="desc") as m:
            self.inv.get_description()
        m.assert_called_once_with("description")

    def test_get_about(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_about()
        m.assert_called_once_with("about")


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class TestUser:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_user_profile(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_user_profile()
        m.assert_called_once_with("user/profile")

    def test_get_user_info(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_user_info()
        m.assert_called_once_with("user/info")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestSettings:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_settings(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_settings()
        m.assert_called_once_with("settings")

    def test_update_settings(self):
        with patch.object(self.inv, "_put") as m:
            self.inv.update_settings({"items": []})
        m.assert_called_once_with("settings", {"items": []})

    def test_add_setting(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.add_setting({"category": "c", "id": "i", "value": "v"})
        m.assert_called_once()

    def test_get_settings_by_category(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_settings_by_category("GENERAL")
        m.assert_called_once_with("settings/GENERAL")

    def test_get_setting(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_setting("GENERAL", "MY_KEY")
        m.assert_called_once_with("settings/GENERAL/MY_KEY")

    def test_update_setting(self):
        with patch.object(self.inv, "_put") as m:
            self.inv.update_setting("GENERAL", "MY_KEY", {"value": "x"})
        m.assert_called_once()

    def test_delete_setting(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_setting("GENERAL", "MY_KEY")
        m.assert_called_once_with("settings/GENERAL/MY_KEY")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


class TestUnits:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_units_no_state(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_units()
        m.assert_called_once_with("units", None)

    def test_get_units_with_state(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_units(state="ACTIVE")
        m.assert_called_once_with("units", {"state": "ACTIVE"})


# ---------------------------------------------------------------------------
# Conditions
# ---------------------------------------------------------------------------


class TestConditions:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_conditions(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_conditions()
        m.assert_called_once_with("conditions")

    def test_create_condition(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_condition({"name": "Cold", "type": "RANGE"})
        m.assert_called_once()

    def test_get_condition(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_condition(5)
        m.assert_called_once_with("conditions/5")

    def test_update_condition(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_condition(5, {"name": "Cold2", "type": "RANGE"})
        m.assert_called_once_with("conditions/5", {"name": "Cold2", "type": "RANGE"})

    def test_delete_condition(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_condition(5)
        m.assert_called_once_with("conditions/5")


# ---------------------------------------------------------------------------
# Custom Fields
# ---------------------------------------------------------------------------


class TestCustomFields:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_fields()
        m.assert_called_once()

    def test_create_field(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.create_field({"name": "F", "type": "STRING"})
        m.assert_called_once()

    def test_update_fields_bulk(self):
        with patch.object(self.inv, "_put") as m:
            self.inv.update_fields({"items": []})
        m.assert_called_once_with("fields", {"items": []})

    def test_get_field(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_field(7)
        m.assert_called_once_with("fields/7")

    def test_delete_field(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_field(7)
        m.assert_called_once_with("fields/7")


# ---------------------------------------------------------------------------
# Concentration Schemes
# ---------------------------------------------------------------------------


class TestConcentrationSchemes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_concentration_schemes(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_concentration_schemes()
        m.assert_called_once()

    def test_create_concentration_scheme(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_concentration_scheme({"name": "S1"})
        m.assert_called_once()

    def test_get_concentration_scheme(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_concentration_scheme(3)
        m.assert_called_once_with("concentration/schemes/3")

    def test_update_concentration_scheme(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_concentration_scheme(3, {"name": "S2"})
        m.assert_called_once_with("concentration/schemes/3", {"name": "S2"})

    def test_delete_concentration_scheme(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_concentration_scheme(3)
        m.assert_called_once_with("concentration/schemes/3")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


class TestTemplates:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_templates(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_templates()
        m.assert_called_once()

    def test_create_template(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_template({"name": "T", "masks": [], "templateType": "NAME"})
        m.assert_called_once()

    def test_get_template(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_template(10)
        m.assert_called_once_with("template/10")

    def test_update_template(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_template(
                10, {"name": "T2", "masks": [], "templateType": "NAME"}
            )
        m.assert_called_once()

    def test_delete_template(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_template(10)
        m.assert_called_once_with("template/10")

    def test_get_templates_with_type_filter(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_templates(type="NAME")
        args = m.call_args[0]
        assert args[0] == "template"
        assert args[1]["type"] == "NAME"


# ---------------------------------------------------------------------------
# Location Types
# ---------------------------------------------------------------------------


class TestLocationTypes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_location_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_types()
        m.assert_called_once()

    def test_create_location_type(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_location_type(
                {"id": 1, "name": "LT", "maxItems": 10, "type": "DEFAULT"}
            )
        m.assert_called_once()

    def test_get_location_type(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_type(1)
        m.assert_called_once_with("types/location/1")

    def test_update_location_type(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_location_type(
                1, {"id": 1, "name": "LT2", "maxItems": 10, "type": "DEFAULT"}
            )
        m.assert_called_once()

    def test_delete_location_type(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_location_type(1)
        m.assert_called_once_with("types/location/1")

    def test_get_location_type_relations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_type_relations(1)
        m.assert_called_once_with("types/location/1/relations")

    def test_get_location_type_available_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_type_available_fields(1)
        m.assert_called_once_with("types/location/1/available-fields")

    def test_get_location_type_auditing(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_type_auditing(1)
        m.assert_called_once()
        assert m.call_args[0][0] == "types/location/1/auditing"


# ---------------------------------------------------------------------------
# Container Types
# ---------------------------------------------------------------------------


class TestContainerTypes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_container_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_types()
        m.assert_called_once()

    def test_create_container_type(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_container_type({"name": "Vial"})
        m.assert_called_once()

    def test_get_container_type(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_type(2)
        m.assert_called_once_with("types/container/2")

    def test_update_container_type(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_container_type(2, {"name": "Vial2"})
        m.assert_called_once_with("types/container/2", {"name": "Vial2"})

    def test_delete_container_type(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_container_type(2)
        m.assert_called_once_with("types/container/2")

    def test_get_container_type_required_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_type_required_fields(2)
        m.assert_called_once_with("types/container/2/required-fields")

    def test_update_container_type_required_fields(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_container_type_required_fields(2, {"requiredFields": []})
        m.assert_called_once()

    def test_get_container_type_relations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_type_relations(2)
        m.assert_called_once_with("types/container/2/relations")

    def test_get_container_type_available_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_type_available_fields(2)
        m.assert_called_once_with("types/container/2/available-fields")

    def test_get_container_type_auditing(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_type_auditing(2)
        assert m.call_args[0][0] == "types/container/2/auditing"


# ---------------------------------------------------------------------------
# Storage Types
# ---------------------------------------------------------------------------


class TestStorageTypes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_storage_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_storage_types()
        m.assert_called_once()

    def test_create_storage_type(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_storage_type({"name": "Freezer"})
        m.assert_called_once()

    def test_get_storage_type(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_storage_type(4)
        m.assert_called_once_with("storage/types/4")

    def test_update_storage_type(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_storage_type(4, {"name": "Freezer2"})
        m.assert_called_once_with("storage/types/4", {"name": "Freezer2"})

    def test_delete_storage_type(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_storage_type(4)
        m.assert_called_once_with("storage/types/4")


# ---------------------------------------------------------------------------
# Plate Types
# ---------------------------------------------------------------------------


class TestPlateTypes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_plate_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_types()
        m.assert_called_once()

    def test_create_plate_type(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_plate_type({"name": "96-well"})
        m.assert_called_once()

    def test_get_plate_type(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type(6)
        m.assert_called_once_with("types/plate/6")

    def test_update_plate_type(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_plate_type(6, {"name": "384-well"})
        m.assert_called_once_with("types/plate/6", {"name": "384-well"})

    def test_delete_plate_type(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_plate_type(6)
        m.assert_called_once_with("types/plate/6")

    def test_get_plate_type_required_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_required_fields(6)
        m.assert_called_once_with("types/plate/6/fields/required")

    def test_get_plate_type_colors(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_colors()
        m.assert_called_once_with("types/plate/colors")

    def test_get_plate_type_bottoms(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_bottoms()
        m.assert_called_once_with("types/plate/bottoms")

    def test_get_plate_type_lids(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_lids()
        m.assert_called_once_with("types/plate/lids")

    def test_get_plate_type_materials(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_materials()
        m.assert_called_once_with("types/plate/materials")

    def test_get_plate_type_purposes(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_purposes()
        m.assert_called_once_with("types/plate/purposes")

    def test_get_plate_type_surface_treatments(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate_type_surface_treatments()
        m.assert_called_once_with("types/plate/surface/treatments")


# ---------------------------------------------------------------------------
# Sample Types
# ---------------------------------------------------------------------------


class TestSampleTypes:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_sample_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample_types()
        m.assert_called_once_with("types/sample", None)

    def test_get_sample_types_with_category(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample_types(category_id=3)
        m.assert_called_once_with("types/sample", {"categoryId": 3})

    def test_create_sample_type(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_sample_type({"name": "ST", "categoryId": 1})
        m.assert_called_once()

    def test_get_sample_type(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample_type(8)
        m.assert_called_once_with("types/sample/8")

    def test_delete_sample_type(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_sample_type(8)
        m.assert_called_once_with("types/sample/8")

    def test_get_sample_type_categories(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample_type_categories()
        m.assert_called_once_with("types/sample/category")

    def test_create_sample_type_category(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_sample_type_category({"name": "Cat"})
        m.assert_called_once()

    def test_get_sample_type_fields(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_sample_type_fields(8)
        assert m.call_args[0][0] == "types/sample/8/field"

    def test_delete_all_sample_type_fields(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_all_sample_type_fields(8)
        m.assert_called_once_with("types/sample/8/field")


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


class TestLayouts:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_layouts(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_layouts()
        m.assert_called_once()

    def test_create_layout(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_layout({"name": "L1"})
        m.assert_called_once()

    def test_get_layout(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_layout(5)
        m.assert_called_once_with("layouts/5")

    def test_update_layout(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_layout(5, {"name": "L2"})
        m.assert_called_once_with("layouts/5", {"name": "L2"})

    def test_delete_layout(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_layout(5)
        m.assert_called_once_with("layouts/5")


# ---------------------------------------------------------------------------
# Layout Grids
# ---------------------------------------------------------------------------


class TestLayoutGrids:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_layout_grids(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_layout_grids()
        m.assert_called_once()

    def test_create_layout_grid(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_layout_grid({"name": "G1", "numOfRows": 8, "numOfCols": 12})
        m.assert_called_once()

    def test_get_layout_grid(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_layout_grid(9)
        m.assert_called_once_with("layout/grids/9")

    def test_delete_layout_grid(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_layout_grid(9)
        m.assert_called_once_with("layout/grids/9")


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


class TestLocations:
    def setup_method(self):
        self.inv = make_inventory()

    def test_create_location(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_location({"id": None, "name": "Room1", "maxItems": 100})
        m.assert_called_once()

    def test_get_location(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location(11)
        m.assert_called_once_with("locations/11")

    def test_update_location(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_location(11, {"name": "Room2", "maxItems": 50, "id": 11})
        m.assert_called_once()

    def test_delete_location(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_location(11)
        m.assert_called_once_with("locations/11")

    def test_disable_location(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.disable_location(11)
        m.assert_called_once_with("locations/11/disable")

    def test_location_access_lock(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.location_access_lock_control(11, True)
        assert m.call_args[0][0] == "locations/11/access/control"

    def test_get_location_tree(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_location_tree(11)
        m.assert_called_once_with("locations/11/tree")

    def test_get_location_grid(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_location_grid(11)
        m.assert_called_once_with("locations/11/grid")

    def test_search_locations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.search_locations("room")
        assert m.call_args[0][0] == "locations/search"
        assert m.call_args[0][1]["query"] == "room"

    def test_get_location_hierarchy(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_location_hierarchy()
        m.assert_called_once_with("locations/hierarchy", None)

    def test_get_location_hierarchy_by_id(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_location_hierarchy_by_id(11)
        m.assert_called_once_with("locations/hierarchy/11", None)

    def test_get_favorite_locations(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_favorite_locations()
        m.assert_called_once_with("locations/favorite")

    def test_add_favorite_location(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.add_favorite_location(11)
        m.assert_called_once_with("locations/favorite/11")

    def test_remove_favorite_location(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.remove_favorite_location(11)
        m.assert_called_once_with("locations/favorite/11")

    def test_move_location(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.move_location(11, 22)
        m.assert_called_once_with("locations/11/move/22")

    def test_clone_location(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.clone_location(11, name="Copy", barcode="BC-99")
        assert m.call_args[0][0] == "locations/11/clone"

    def test_get_location_groups(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_location_groups(11)
        m.assert_called_once_with("locations/11/groups")

    def test_get_location_groups_auditing(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_location_groups_auditing(11)
        m.assert_called_once_with("locations/11/groups/auditing")

    def test_get_location_group_user_access_bulk(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.get_location_group_user_access_bulk([11, 22])
        m.assert_called_once_with("locations/groups/user/access", [11, 22])


# ---------------------------------------------------------------------------
# Containers
# ---------------------------------------------------------------------------


class TestContainers:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_container(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container(42)
        m.assert_called_once_with("containers/42")

    def test_fetch_container_by_id_alias(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.fetch_container_by_id(42)
        m.assert_called_once_with("containers/42")

    def test_update_container(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_container(42, {"typeId": 1})
        m.assert_called_once_with("containers/42", {"typeId": 1})

    def test_delete_container(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_container(42)
        m.assert_called_once_with("containers/42")

    def test_enable_container(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.enable_container(42)
        m.assert_called_once_with("containers/42/enable")

    def test_disable_container(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.disable_container(42)
        m.assert_called_once_with("containers/42/disable")

    def test_get_containers_by_ids(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.get_containers_by_ids([1, 2, 3])
        m.assert_called_once_with("containers", [1, 2, 3])

    def test_get_containers_by_location(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_containers_by_location(5)
        assert m.call_args[0][0] == "locations/5/containers"

    def test_create_container_in_location(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_container_in_location(5, {"typeId": 1})
        m.assert_called_once_with("locations/5/containers", {"typeId": 1})

    def test_move_containers(self):
        with patch.object(self.inv, "_post", return_value="ok") as m:
            self.inv.move_containers(1, 2, [{"id": 42}])
        m.assert_called_once_with("locations/1/containers/move/2", [{"id": 42}])

    def test_checkout_containers(self):
        with patch.object(self.inv, "_post", return_value="ok") as m:
            self.inv.checkout_containers(1, 2, [42, 43])
        m.assert_called_once_with("locations/1/containers/checkout/2", [42, 43])

    def test_checkin_containers(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.checkin_containers([42, 43])
        m.assert_called_once_with("containers/checkin", [42, 43])

    def test_aliquot_containers(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.aliquot_containers([{"parentContainerId": 1, "containers": []}])
        assert m.call_args[0][0] == "containers/aliquot"

    def test_validate_aliquot(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.validate_aliquot([])
        m.assert_called_once_with("containers/aliquot/validate", [])

    def test_mix_containers(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.mix_containers([{"typeId": 1}])
        m.assert_called_once_with("containers/mix", [{"typeId": 1}])

    def test_dissolve_container(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.dissolve_container([])
        m.assert_called_once_with("containers/dissolve", [])

    def test_get_dissolve_info(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.get_dissolve_info([42])
        m.assert_called_once_with("containers/dissolve/get", [42])

    def test_reserve_container(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.reserve_container(42)
        assert m.call_args[0][0] == "containers/42/reserve"

    def test_cancel_reserve_container(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.cancel_reserve_container(42)
        m.assert_called_once_with("containers/42/reserve")

    def test_reserve_container_amount(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.reserve_container_amount(42, "5.0")
        assert m.call_args[0][0] == "containers/42/reserve_amount"

    def test_get_container_template_name(self):
        with patch.object(self.inv, "_post", return_value="T-001") as m:
            self.inv.get_container_template_name({"containerTypeId": 1})
        m.assert_called_once_with("containers/template/name", {"containerTypeId": 1})

    def test_get_containers_by_batch_id(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.get_containers_by_batch_id("BATCH-001")
        m.assert_called_once_with("containers/batchId", "BATCH-001")

    def test_validate_container_barcode(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.validate_container_barcode("BC-001")
        assert m.call_args[1]["query_params"] == {"barcode": "BC-001"}

    def test_get_container_auditing(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_auditing(42)
        assert m.call_args[0][0] == "containers/42/auditing"

    def test_create_containers_bulk(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.create_containers_bulk(
                [{"locationId": 1, "containerDTO": {"typeId": 2}}]
            )
        assert m.call_args[0][0] == "containers/create"

    def test_update_containers_bulk(self):
        with patch.object(self.inv, "_post", return_value=[]) as m:
            self.inv.update_containers_bulk([{"typeId": 1}])
        assert m.call_args[0][0] == "containers/update"


# ---------------------------------------------------------------------------
# Container Cycles
# ---------------------------------------------------------------------------


class TestContainerCycles:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_container_cycles(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_container_cycles(42)
        m.assert_called_once_with("container/cycles/42")

    def test_assign_cycles_allowed(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.assign_cycles_allowed(42, 5)
        m.assert_called_once_with("container/cycles/42/5")


# ---------------------------------------------------------------------------
# Plates
# ---------------------------------------------------------------------------


class TestPlates:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_plates(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plates()
        m.assert_called_once()

    def test_create_plate(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_plate({})
        m.assert_called_once_with("plates", {})

    def test_get_plate(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_plate(7)
        m.assert_called_once_with("plates/7")

    def test_update_plate(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_plate(7, {"barcode": "P-001"})
        m.assert_called_once_with("plates/7", {"barcode": "P-001"})

    def test_delete_plate(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_plate(7)
        m.assert_called_once_with("plates/7")


# ---------------------------------------------------------------------------
# Samples
# ---------------------------------------------------------------------------


class TestSamples:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_sample(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample(3, "CMP-001")
        m.assert_called_once_with("samples/3", {"formattedId": "CMP-001"})

    def test_get_sample_by_path(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_sample_by_path(3, "CMP-001")
        m.assert_called_once_with("samples/3/CMP-001")

    def test_validate_sample(self):
        with patch.object(self.inv, "_get") as m:
            self.inv.validate_sample(3, "CMP-001")
        m.assert_called_once_with("samples/validate/3", {"formattedId": "CMP-001"})

    def test_render_smile(self):
        # render_smile posts directly and returns the raw (non-JSON) body bytes.
        resp = mock_response(200, content=b"<svg/>")
        with patch("requests.Session.post", return_value=resp) as m:
            result = self.inv.render_smile({"smile": "CC"})
        assert result == b"<svg/>"
        assert m.call_args[0][0].endswith("/inventory/api/samples/smile")


class TestDepictor:
    def setup_method(self):
        self.inv = make_inventory()

    def test_render_barcode_uses_flat_query_params(self):
        # Regression: the depictor GET binds flat params (value/height/width);
        # the depictorDTO.* prefix is rejected server-side ("value can not be empty").
        resp = mock_response(200, content=b"PNGDATA")
        with patch("requests.Session.get", return_value=resp) as m:
            result = self.inv.render_barcode("ABC", height=10, width=20)
        assert result == b"PNGDATA"
        url = m.call_args[0][0]
        assert "value=ABC" in url
        assert "depictorDTO" not in url


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


class TestSearch:
    def setup_method(self):
        self.inv = make_inventory()

    def test_quick_search(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.quick_search("aspirin")
        m.assert_called_once_with("search", {"query": "aspirin"})

    def test_search_locations_quick(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.search_locations_quick("fridge")
        assert m.call_args[0][0] == "search/locations"
        assert m.call_args[0][1]["query"] == "fridge"

    def test_search_containers_quick(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.search_containers_quick("vial")
        assert m.call_args[0][0] == "search/containers"

    def test_search_containers_heavy(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.search_containers_heavy("vial")
        assert m.call_args[0][0] == "search/containers/heavy"


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------


class TestCalculator:
    def setup_method(self):
        self.inv = make_inventory()

    def test_calculate(self):
        with patch.object(self.inv, "_post", return_value={"result": "6"}) as m:
            result = self.inv.calculate(2.0, 3.0, "multiply")
        m.assert_called_once_with(
            "calculator", {"var1": 2.0, "var2": 3.0, "operation": "multiply"}
        )
        assert result == {"result": "6"}


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------


class TestCart:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_cart(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_cart()
        m.assert_called_once()

    def test_add_to_cart(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.add_to_cart([1, 2])
        m.assert_called_once_with("cart", [1, 2])

    def test_remove_from_cart(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.remove_from_cart(
                {"selected": [1], "selectAll": False, "unselected": []}
            )
        m.assert_called_once()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestNotifications:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_notifications(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_notifications()
        m.assert_called_once()

    def test_mark_notification_read(self):
        with patch.object(self.inv, "_post") as m:
            self.inv.mark_notification_read(99)
        m.assert_called_once_with("notifications/99/read")

    def test_delete_notification(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_notification(99)
        m.assert_called_once_with("notifications/99")

    def test_delete_read_notifications(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_read_notifications()
        m.assert_called_once_with("notifications/read")


# ---------------------------------------------------------------------------
# Labvoice
# ---------------------------------------------------------------------------


class TestLabvoice:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_labvoice_container(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_labvoice_container("BC-001")
        m.assert_called_once_with("labvoice/containers", {"barcode": "BC-001"})


# ---------------------------------------------------------------------------
# Import History
# ---------------------------------------------------------------------------


class TestImportHistory:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_import_history(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_import_history()
        m.assert_called_once()

    def test_delete_import_history(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_import_history(55)
        m.assert_called_once_with("import/history/55")

    def test_delete_import_file(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_import_file(77)
        m.assert_called_once_with("import/files/77")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


class TestMigration:
    def setup_method(self):
        self.inv = make_inventory()

    def test_start_migration(self):
        with patch.object(self.inv, "_put", return_value="started") as m:
            self.inv.start_migration()
        m.assert_called_once_with("migration/start")

    def test_get_migration_status(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_migration_status()
        m.assert_called_once_with("migration/status")

    def test_get_all_migration_logs(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_all_migration_logs()
        assert m.call_args[0][0] == "migration/status/all"

    def test_get_migration_locations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_migration_locations()
        m.assert_called_once_with("migration/locations")

    def test_delete_migration_locations(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_migration_locations([1, 2])
        m.assert_called_once_with("migration/locations", [1, 2])

    def test_get_migration_location(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_migration_location(1)
        m.assert_called_once_with("migration/locations/1")

    def test_delete_migration_location(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_migration_location(1)
        m.assert_called_once_with("migration/locations/1")

    def test_search_migration_locations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.search_migration_locations("fridge")
        m.assert_called_once_with("migration/locations/search", {"query": "fridge"})

    def test_get_migration_location_hierarchy(self):
        with patch.object(self.inv, "_get", return_value=[]) as m:
            self.inv.get_migration_location_hierarchy()
        m.assert_called_once_with("migration/locations/hierarchy")

    def test_get_migration_containers(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_migration_containers(1)
        assert m.call_args[0][0] == "migration/locations/1/containers"

    def test_get_migration_container(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_migration_container(99)
        m.assert_called_once_with("migration/containers/99")

    def test_delete_migration_container(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_migration_container(99)
        m.assert_called_once_with("migration/containers/99")

    def test_delete_migration_containers(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_migration_containers([99, 100])
        m.assert_called_once_with("migration/containers", [99, 100])


# ---------------------------------------------------------------------------
# Integration endpoints
# ---------------------------------------------------------------------------


class TestIntegration:
    def setup_method(self):
        self.inv = make_inventory()

    def test_integration_get_units(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_units()
        m.assert_called_once_with("integration/units")

    def test_integration_get_sample_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_sample_types()
        m.assert_called_once_with("integration/sample/types")

    def test_integration_get_sample_types_by_query(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_sample_types_by_query("CMP")
        m.assert_called_once_with("integration/sample/types/CMP")

    def test_integration_get_locations(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_locations()
        m.assert_called_once_with("integration/locations")

    def test_integration_get_location_absolute_path_by_id(self):
        with patch.object(self.inv, "_get", return_value="path") as m:
            self.inv.integration_get_location_absolute_path_by_id(5)
        m.assert_called_once_with("integration/locations/absolute/path/5")

    def test_integration_get_location_absolute_paths_bulk(self):
        with patch.object(self.inv, "_post", return_value="paths") as m:
            self.inv.integration_get_location_absolute_paths_bulk([1, 2, 3])
        m.assert_called_once_with("integration/locations/absolute/path/bulk", [1, 2, 3])

    def test_integration_get_container_type_custom_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_container_type_custom_fields()
        m.assert_called_once_with("integration/custom/fields")

    def test_integration_create_container(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.integration_create_container({"typeId": 1, "locationId": 5})
        m.assert_called_once_with(
            "integration/container", {"typeId": 1, "locationId": 5}
        )

    def test_integration_create_samples(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.integration_create_samples([{"typeId": 1, "locationId": 5}])
        m.assert_called_once_with(
            "integration/create/samples", [{"typeId": 1, "locationId": 5}]
        )

    def test_integration_get_all_container_types(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_all_container_types()
        assert m.call_args[0][0] == "integration/container/type/all"

    def test_integration_get_allowed_containers_for_location(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_allowed_containers_for_location("BC-123")
        m.assert_called_once_with("integration/container/names/BC-123")

    def test_integration_get_container_core_fields(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.integration_get_container_core_fields(2)
        m.assert_called_once_with("integration/container/fields/2")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


class TestGroups:
    def setup_method(self):
        self.inv = make_inventory()

    def test_get_groups(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_groups()
        m.assert_called_once()

    def test_get_group(self):
        with patch.object(self.inv, "_get", return_value={}) as m:
            self.inv.get_group(3)
        m.assert_called_once_with("groups/3")

    def test_create_group(self):
        with patch.object(self.inv, "_post", return_value={}) as m:
            self.inv.create_group(3, {"name": "G"})
        m.assert_called_once_with("groups/3", {"name": "G"})

    def test_update_group(self):
        with patch.object(self.inv, "_put", return_value={}) as m:
            self.inv.update_group(3, {"name": "G2"})
        m.assert_called_once_with("groups/3", {"name": "G2"})

    def test_delete_group(self):
        with patch.object(self.inv, "_delete") as m:
            self.inv.delete_group(3)
        m.assert_called_once_with("groups/3")
