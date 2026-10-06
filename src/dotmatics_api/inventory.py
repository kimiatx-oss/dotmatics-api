from typing import IO

import requests

from .base import AuthenticationError, DotmaticsClient

__all__ = ["AuthenticationError", "Inventory"]


class Inventory(DotmaticsClient):
    """Encapsulates interactions with the Dotmatics Inventory REST API.

    Authenticate with a username/password pair or a previously obtained token::

        >>> inv = Inventory(user=DOTMATICS_USER, password=DOTMATICS_PASSWORD,
        ...                 dotmatics_instance="https://demo.example.org")
    """

    _API_PREFIX = "/inventory/api"
    _AUTH_ENDPOINT = "authenticate/inventory"

    def __init__(
        self,
        user: str,
        password: str | None = None,
        token: str | None = None,
        *,
        dotmatics_instance: str,
        socks5_proxy: str | None = None,
        max_threads: int = 4,
        connection_timeout: int = 10,
        read_timeout: int = 100,
        connect_retries: int = 5,
        read_retries: int = 2,
    ):
        """
        Args:
            user: Dotmatics username.
            password: Password for the given user (required if token is not provided).
            token: Bearer token from a prior /authenticate call (alternative to password).
            dotmatics_instance: Base URL of the Dotmatics instance.
            socks5_proxy: Optional SOCKS5 proxy URL, e.g. ``socks5://localhost:1080``.
            max_threads: Max concurrent GET requests.
            connection_timeout: Socket connection timeout in seconds.
            read_timeout: Socket read timeout in seconds.
            connect_retries: Retries for connection-phase failures (DNS, refused
                or timed-out connect, SOCKS negotiation) with exponential
                backoff; see DotmaticsClient for details.
            read_retries: Retries (GET only) for requests whose connection died
                after sending; see DotmaticsClient for details.
        """
        super().__init__(
            user=user,
            password=password,
            token=token,
            dotmatics_instance=dotmatics_instance,
            socks5_proxy=socks5_proxy,
            connection_timeout=connection_timeout,
            read_timeout=read_timeout,
            connect_retries=connect_retries,
            read_retries=read_retries,
        )

        # Retained for backwards compatibility; the request path is built from
        # _API_PREFIX in the base class.
        self.api_url = self._build_url("/inventory/")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_auth_response(self, response: requests.Response) -> str:
        """Extract the bearer token from the Inventory auth payload.

        Unlike the Browser auth endpoint, /authenticate/inventory wraps the
        token in a JSON object: ``{"token": "..."}``.
        """
        return response.json()["token"]

    def _headers(self) -> dict:
        """Bearer auth plus a JSON content type for request bodies."""
        return {**self._bearer_headers(), "Content-Type": "application/json"}

    def _post(
        self,
        endpoint: str,
        payload=None,
        query_params: dict | None = None,
        files: dict | None = None,
    ):
        """Issue an authenticated POST request."""
        url = self._make_request_path(endpoint, query_params)
        if files:
            response = self._session.post(
                url,
                headers=self._bearer_headers(),
                files=files,
                proxies=self.proxies,
                timeout=(self.connection_timeout, self.read_timeout),
            )
        else:
            response = self._session.post(
                url,
                headers=self._headers(),
                json=payload,
                proxies=self.proxies,
                timeout=(self.connection_timeout, self.read_timeout),
            )
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise ValueError(
            {
                "status": response.status_code,
                "path": endpoint,
                "response": response.text,
            }
        )

    def _put(self, endpoint: str, payload=None, query_params: dict | None = None):
        """Issue an authenticated PUT request."""
        url = self._make_request_path(endpoint, query_params)
        response = self._session.put(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise ValueError(
            {
                "status": response.status_code,
                "path": endpoint,
                "response": response.text,
            }
        )

    def _delete(self, endpoint: str, payload=None, query_params: dict | None = None):
        """Issue an authenticated DELETE request."""
        url = self._make_request_path(endpoint, query_params)
        response = self._session.delete(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.content:
                return None
            return response.json()
        raise ValueError(
            {
                "status": response.status_code,
                "path": endpoint,
                "response": response.text,
            }
        )

    # ------------------------------------------------------------------
    # Version / Info
    # ------------------------------------------------------------------

    def get_version(self) -> str:
        """GET /api/version — Return the application version string."""
        return self._get("version")

    def get_description(self) -> str:
        """GET /api/description — Return the application description."""
        return self._get("description")

    def get_about(self) -> dict:
        """GET /api/about — Return installed application info (version, license, etc.)."""
        return self._get("about")

    # ------------------------------------------------------------------
    # User
    # ------------------------------------------------------------------

    def get_user_profile(self) -> dict:
        """GET /api/user/profile — Return the current user's profile."""
        return self._get("user/profile")

    def get_user_info(self) -> dict:
        """GET /api/user/info — Return the current user's info."""
        return self._get("user/info")

    # ------------------------------------------------------------------
    # Users / Groups
    # ------------------------------------------------------------------

    def get_user_groups(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str | None = None,
    ) -> dict:
        """GET /api/users/groups — List user groups (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "userGroupSearchFilter.filter": filter or "",
        }
        return self._get("users/groups", params)

    def get_groups(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str | None = None,
    ) -> dict:
        """GET /api/groups — List location groups (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "groupSearchFilter.filter": filter or "",
        }
        return self._get("groups", params)

    def get_group(self, group_id: int) -> dict:
        """GET /api/groups/{id} — Get a location group by ID."""
        return self._get(f"groups/{group_id}")

    def create_group(self, group_id: int, payload: dict) -> dict:
        """POST /api/groups/{id} — Create a location group."""
        return self._post(f"groups/{group_id}", payload)

    def update_group(self, group_id: int, payload: dict) -> dict:
        """PUT /api/groups/{id} — Update a location group."""
        return self._put(f"groups/{group_id}", payload)

    def delete_group(self, group_id: int) -> None:
        """DELETE /api/groups/{id} — Delete a location group."""
        return self._delete(f"groups/{group_id}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_settings(self) -> dict:
        """GET /api/settings — Return all application settings."""
        return self._get("settings")

    def update_settings(self, payload: dict) -> None:
        """PUT /api/settings — Update all application settings."""
        return self._put("settings", payload)

    def add_setting(self, payload: dict) -> None:
        """POST /api/settings — Add a new application setting."""
        return self._post("settings", payload)

    def get_settings_by_category(self, category: str) -> list:
        """GET /api/settings/{category} — Return settings for a category."""
        return self._get(f"settings/{category}")

    def get_setting(self, category: str, setting_id: str) -> dict:
        """GET /api/settings/{category}/{id} — Return a single setting."""
        return self._get(f"settings/{category}/{setting_id}")

    def update_setting(self, category: str, setting_id: str, payload: dict) -> None:
        """PUT /api/settings/{category}/{id} — Update a single setting."""
        return self._put(f"settings/{category}/{setting_id}", payload)

    def delete_setting(self, category: str, setting_id: str) -> None:
        """DELETE /api/settings/{category}/{id} — Delete a single setting."""
        return self._delete(f"settings/{category}/{setting_id}")

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------

    def get_units(self, state: str | None = None) -> dict:
        """GET /api/units — Return all units, optionally filtered by state."""
        params = {"state": state} if state else None
        return self._get("units", params)

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------

    def get_conditions(self) -> dict:
        """GET /api/conditions — Return all conditions."""
        return self._get("conditions")

    def create_condition(self, payload: dict) -> dict:
        """POST /api/conditions — Create a new condition."""
        return self._post("conditions", payload)

    def get_condition(self, condition_id: int) -> dict:
        """GET /api/conditions/{id} — Return a condition by ID."""
        return self._get(f"conditions/{condition_id}")

    def update_condition(self, condition_id: int, payload: dict) -> dict:
        """PUT /api/conditions/{id} — Update a condition."""
        return self._put(f"conditions/{condition_id}", payload)

    def delete_condition(self, condition_id: int) -> None:
        """DELETE /api/conditions/{id} — Delete a condition."""
        return self._delete(f"conditions/{condition_id}")

    # ------------------------------------------------------------------
    # Custom Fields
    # ------------------------------------------------------------------

    def get_fields(self, sort: str | None = None) -> dict:
        """GET /api/fields — Return all custom fields."""
        params = {"sortConfigurationFilter.sort": sort or ""}
        return self._get("fields", params)

    def update_fields(self, payload: dict) -> None:
        """PUT /api/fields — Bulk-update custom fields."""
        return self._put("fields", payload)

    def create_field(self, payload: dict) -> None:
        """POST /api/fields — Create a custom field."""
        return self._post("fields", payload)

    def get_field(self, field_id: int) -> dict:
        """GET /api/fields/{id} — Return a custom field by ID."""
        return self._get(f"fields/{field_id}")

    def delete_field(self, field_id: int) -> None:
        """DELETE /api/fields/{id} — Delete a custom field."""
        return self._delete(f"fields/{field_id}")

    # ------------------------------------------------------------------
    # Concentration Schemes
    # ------------------------------------------------------------------

    def get_concentration_schemes(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/concentration/schemes — List concentration schemes (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("concentration/schemes", params)

    def create_concentration_scheme(self, payload: dict) -> dict:
        """POST /api/concentration/schemes — Create a concentration scheme."""
        return self._post("concentration/schemes", payload)

    def get_concentration_scheme(self, scheme_id: int) -> dict:
        """GET /api/concentration/schemes/{id} — Return a scheme by ID."""
        return self._get(f"concentration/schemes/{scheme_id}")

    def update_concentration_scheme(self, scheme_id: int, payload: dict) -> dict:
        """PUT /api/concentration/schemes/{id} — Update a scheme."""
        return self._put(f"concentration/schemes/{scheme_id}", payload)

    def delete_concentration_scheme(self, scheme_id: int) -> None:
        """DELETE /api/concentration/schemes/{id} — Delete a scheme."""
        return self._delete(f"concentration/schemes/{scheme_id}")

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def get_templates(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
        type: str | None = None,
    ) -> dict:
        """GET /api/template — List templates (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        if type:
            params["type"] = type
        return self._get("template", params)

    def create_template(self, payload: dict) -> dict:
        """POST /api/template — Create a template."""
        return self._post("template", payload)

    def get_template(self, template_id: int) -> dict:
        """GET /api/template/{id} — Return a template by ID."""
        return self._get(f"template/{template_id}")

    def update_template(self, template_id: int, payload: dict) -> dict:
        """PUT /api/template/{id} — Update a template."""
        return self._put(f"template/{template_id}", payload)

    def delete_template(self, template_id: int) -> None:
        """DELETE /api/template/{id} — Delete a template."""
        return self._delete(f"template/{template_id}")

    # ------------------------------------------------------------------
    # Location Types
    # ------------------------------------------------------------------

    def get_location_types(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/types/location — List location types (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("types/location", params)

    def create_location_type(self, payload: dict) -> dict:
        """POST /api/types/location — Create a location type."""
        return self._post("types/location", payload)

    def get_location_type(self, location_type_id) -> dict:
        """GET /api/types/location/{id} — Return a location type by ID."""
        return self._get(f"types/location/{location_type_id}")

    def update_location_type(self, location_type_id, payload: dict) -> dict:
        """PUT /api/types/location/{id} — Update a location type."""
        return self._put(f"types/location/{location_type_id}", payload)

    def delete_location_type(self, location_type_id) -> None:
        """DELETE /api/types/location/{id} — Delete a location type."""
        return self._delete(f"types/location/{location_type_id}")

    def get_location_type_relations(self, location_type_id: int) -> dict:
        """GET /api/types/location/{id}/relations — Return parent/child relations."""
        return self._get(f"types/location/{location_type_id}/relations")

    def get_location_type_available_fields(self, location_type_id: int) -> dict:
        """GET /api/types/location/{id}/available-fields — Return available fields."""
        return self._get(f"types/location/{location_type_id}/available-fields")

    def get_location_type_auditing(
        self,
        location_type_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/types/location/{id}/auditing — Return audit log for a location type."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"types/location/{location_type_id}/auditing", params)

    # ------------------------------------------------------------------
    # Container Types
    # ------------------------------------------------------------------

    def get_container_types(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/types/container — List container types (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("types/container", params)

    def create_container_type(self, payload: dict) -> dict:
        """POST /api/types/container — Create a container type."""
        return self._post("types/container", payload)

    def get_container_type(self, container_type_id: int) -> dict:
        """GET /api/types/container/{id} — Return a container type by ID."""
        return self._get(f"types/container/{container_type_id}")

    def update_container_type(self, container_type_id: int, payload: dict) -> dict:
        """PUT /api/types/container/{id} — Update a container type."""
        return self._put(f"types/container/{container_type_id}", payload)

    def delete_container_type(self, container_type_id: int) -> None:
        """DELETE /api/types/container/{id} — Delete a container type."""
        return self._delete(f"types/container/{container_type_id}")

    def get_container_type_required_fields(self, container_type_id: int) -> dict:
        """GET /api/types/container/{id}/required-fields — Return required fields."""
        return self._get(f"types/container/{container_type_id}/required-fields")

    def update_container_type_required_fields(
        self, container_type_id: int, payload: dict
    ) -> dict:
        """PUT /api/types/container/{id}/required-fields — Update required fields."""
        return self._put(
            f"types/container/{container_type_id}/required-fields", payload
        )

    def get_container_type_relations(self, container_type_id: int) -> dict:
        """GET /api/types/container/{id}/relations — Return relations for a container type."""
        return self._get(f"types/container/{container_type_id}/relations")

    def get_container_type_available_fields(self, container_type_id: int) -> dict:
        """GET /api/types/container/{id}/available-fields — Return available fields."""
        return self._get(f"types/container/{container_type_id}/available-fields")

    def get_container_type_auditing(
        self,
        container_type_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/types/container/{id}/auditing — Return audit log for a container type."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"types/container/{container_type_id}/auditing", params)

    def get_container_types_for_aliquot(
        self,
        location_type_id: int,
        container_type_id: int | None = None,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/types/container/aliquot/{locationTypeId} — Container types usable for aliquot."""
        params = {"sort.sort": sort or "", "filter": filter}
        if container_type_id is not None:
            params["containerTypeId"] = container_type_id
        return self._get(f"types/container/aliquot/{location_type_id}", params)

    # ------------------------------------------------------------------
    # Storage Types
    # ------------------------------------------------------------------

    def get_storage_types(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/storage/types — List storage types (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("storage/types", params)

    def create_storage_type(self, payload: dict) -> dict:
        """POST /api/storage/types — Create a storage type."""
        return self._post("storage/types", payload)

    def get_storage_type(self, storage_type_id: int) -> dict:
        """GET /api/storage/types/{id} — Return a storage type by ID."""
        return self._get(f"storage/types/{storage_type_id}")

    def update_storage_type(self, storage_type_id: int, payload: dict) -> dict:
        """PUT /api/storage/types/{id} — Update a storage type."""
        return self._put(f"storage/types/{storage_type_id}", payload)

    def delete_storage_type(self, storage_type_id: int) -> None:
        """DELETE /api/storage/types/{id} — Delete a storage type."""
        return self._delete(f"storage/types/{storage_type_id}")

    # ------------------------------------------------------------------
    # Sample Types
    # ------------------------------------------------------------------

    def get_sample_types(self, category_id: int | None = None) -> dict:
        """GET /api/types/sample — Return all sample types."""
        params = {"categoryId": category_id} if category_id is not None else None
        return self._get("types/sample", params)

    def create_sample_type(self, payload: dict) -> dict:
        """POST /api/types/sample — Create a sample type."""
        return self._post("types/sample", payload)

    def get_sample_type(self, sample_type_id: int) -> dict:
        """GET /api/types/sample/{id} — Return a sample type by ID."""
        return self._get(f"types/sample/{sample_type_id}")

    def update_sample_type(self, sample_type_id: int, payload: dict) -> dict:
        """PUT /api/types/sample/{id} — Update a sample type."""
        return self._put(f"types/sample/{sample_type_id}", payload)

    def delete_sample_type(self, sample_type_id: int) -> None:
        """DELETE /api/types/sample/{id} — Delete a sample type."""
        return self._delete(f"types/sample/{sample_type_id}")

    def get_sample_type_categories(self) -> dict:
        """GET /api/types/sample/category — Return all sample type categories."""
        return self._get("types/sample/category")

    def create_sample_type_category(self, payload: dict) -> dict:
        """POST /api/types/sample/category — Create a sample type category."""
        return self._post("types/sample/category", payload)

    def get_sample_type_category(self, category_id: int) -> dict:
        """GET /api/types/sample/category/{id} — Return a category by ID."""
        return self._get(f"types/sample/category/{category_id}")

    def delete_sample_type_category(self, category_id: int) -> None:
        """DELETE /api/types/sample/category/{id} — Delete a sample type category."""
        return self._delete(f"types/sample/category/{category_id}")

    def get_sample_type_fields(
        self, sample_type_id: int, sort: str | None = None
    ) -> list:
        """GET /api/types/sample/{sampleTypeId}/field — Return fields for a sample type."""
        params = {"sort.sort": sort or ""}
        return self._get(f"types/sample/{sample_type_id}/field", params)

    def create_sample_type_field(self, sample_type_id: int, payload: dict) -> dict:
        """POST /api/types/sample/{sampleTypeId}/field — Add a field to a sample type."""
        return self._post(f"types/sample/{sample_type_id}/field", payload)

    def delete_all_sample_type_fields(self, sample_type_id: int) -> None:
        """DELETE /api/types/sample/{sampleTypeId}/field — Delete all fields for a sample type."""
        return self._delete(f"types/sample/{sample_type_id}/field")

    def get_sample_type_field(self, field_id: int) -> dict:
        """GET /api/types/sample/field/{id} — Return a sample type field by ID."""
        return self._get(f"types/sample/field/{field_id}")

    def update_sample_type_field(self, field_id: int, payload: dict) -> dict:
        """PUT /api/types/sample/field/{id} — Update a sample type field."""
        return self._put(f"types/sample/field/{field_id}", payload)

    def delete_sample_type_field(self, field_id: int) -> None:
        """DELETE /api/types/sample/field/{id} — Delete a sample type field."""
        return self._delete(f"types/sample/field/{field_id}")

    # ------------------------------------------------------------------
    # Plate Types
    # ------------------------------------------------------------------

    def get_plate_types(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/types/plate — List plate types (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("types/plate", params)

    def create_plate_type(self, payload: dict) -> dict:
        """POST /api/types/plate — Create a plate type."""
        return self._post("types/plate", payload)

    def get_plate_type(self, plate_type_id: int) -> dict:
        """GET /api/types/plate/{id} — Return a plate type by ID."""
        return self._get(f"types/plate/{plate_type_id}")

    def update_plate_type(self, plate_type_id: int, payload: dict) -> dict:
        """PUT /api/types/plate/{id} — Update a plate type."""
        return self._put(f"types/plate/{plate_type_id}", payload)

    def delete_plate_type(self, plate_type_id: int) -> None:
        """DELETE /api/types/plate/{id} — Delete a plate type."""
        return self._delete(f"types/plate/{plate_type_id}")

    def get_plate_type_required_fields(self, plate_type_id: int) -> dict:
        """GET /api/types/plate/{id}/fields/required — Return required fields for a plate type."""
        return self._get(f"types/plate/{plate_type_id}/fields/required")

    def update_plate_type_required_fields(
        self, plate_type_id: int, payload: dict
    ) -> dict:
        """PUT /api/types/plate/{id}/fields/required — Update required fields for a plate type."""
        return self._put(f"types/plate/{plate_type_id}/fields/required", payload)

    def get_plate_type_colors(self) -> dict:
        """GET /api/types/plate/colors — Return available plate colors."""
        return self._get("types/plate/colors")

    def get_plate_type_bottoms(self) -> dict:
        """GET /api/types/plate/bottoms — Return available plate bottoms."""
        return self._get("types/plate/bottoms")

    def get_plate_type_lids(self) -> dict:
        """GET /api/types/plate/lids — Return available plate lids."""
        return self._get("types/plate/lids")

    def get_plate_type_materials(self) -> dict:
        """GET /api/types/plate/materials — Return available plate materials."""
        return self._get("types/plate/materials")

    def get_plate_type_purposes(self) -> dict:
        """GET /api/types/plate/purposes — Return available plate purposes."""
        return self._get("types/plate/purposes")

    def get_plate_type_surface_treatments(self) -> dict:
        """GET /api/types/plate/surface/treatments — Return available surface treatments."""
        return self._get("types/plate/surface/treatments")

    # ------------------------------------------------------------------
    # Layout Well Types
    # ------------------------------------------------------------------

    def get_layout_well_types(self, page_number: int = 1, page_size: int = 20) -> dict:
        """GET /api/types/layout-wells — List layout well types (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
        }
        return self._get("types/layout-wells", params)

    def create_layout_well_type(self, payload: dict) -> dict:
        """POST /api/types/layout-wells — Create a layout well type."""
        return self._post("types/layout-wells", payload)

    def get_layout_well_type(self, well_type_id: int) -> dict:
        """GET /api/types/layout-wells/{id} — Return a layout well type by ID."""
        return self._get(f"types/layout-wells/{well_type_id}")

    def update_layout_well_type(self, well_type_id: int, payload: dict) -> dict:
        """PUT /api/types/layout-wells/{id} — Update a layout well type."""
        return self._put(f"types/layout-wells/{well_type_id}", payload)

    def delete_layout_well_type(self, well_type_id: int) -> None:
        """DELETE /api/types/layout-wells/{id} — Delete a layout well type."""
        return self._delete(f"types/layout-wells/{well_type_id}")

    # ------------------------------------------------------------------
    # Layouts
    # ------------------------------------------------------------------

    def get_layouts(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/layouts — List layouts (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("layouts", params)

    def create_layout(self, payload: dict, create_storage_type: bool = True) -> dict:
        """POST /api/layouts — Create a layout."""
        params = {"createStorageType": str(create_storage_type).lower()}
        return self._post("layouts", payload, query_params=params)

    def get_layout(self, layout_id: int) -> dict:
        """GET /api/layouts/{id} — Return a layout by ID."""
        return self._get(f"layouts/{layout_id}")

    def update_layout(self, layout_id: int, payload: dict) -> dict:
        """PUT /api/layouts/{id} — Update a layout."""
        return self._put(f"layouts/{layout_id}", payload)

    def delete_layout(self, layout_id: int) -> None:
        """DELETE /api/layouts/{id} — Delete a layout."""
        return self._delete(f"layouts/{layout_id}")

    def import_layout(self, file: IO) -> dict:
        """POST /api/layout/import — Import layout from a file."""
        return self._post("layout/import", files={"file": file})

    def export_layout_xlsx_template(self, payload: list) -> bytes:
        """POST /api/layout/template/xlsx — Export an xlsx layout template."""
        url = self._make_request_path("layout/template/xlsx")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def export_layout_csv_template(self) -> bytes:
        """GET /api/layout/template/csv — Export a CSV layout template."""
        return self._get("layout/template/csv", raw=True).content

    # ------------------------------------------------------------------
    # Layout Grids
    # ------------------------------------------------------------------

    def get_layout_grids(self, page_number: int = 1, page_size: int = 20) -> dict:
        """GET /api/layout/grids — List layout grids (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
        }
        return self._get("layout/grids", params)

    def create_layout_grid(self, payload: dict) -> dict:
        """POST /api/layout/grids — Create a layout grid."""
        return self._post("layout/grids", payload)

    def get_layout_grid(self, grid_id: int) -> dict:
        """GET /api/layout/grids/{id} — Return a layout grid by ID."""
        return self._get(f"layout/grids/{grid_id}")

    def update_layout_grid(self, grid_id: int, payload: dict) -> dict:
        """PUT /api/layout/grids/{id} — Update a layout grid."""
        return self._put(f"layout/grids/{grid_id}", payload)

    def delete_layout_grid(self, grid_id: int) -> None:
        """DELETE /api/layout/grids/{id} — Delete a layout grid."""
        return self._delete(f"layout/grids/{grid_id}")

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------

    def create_location(self, payload: dict, groups: bool = False) -> dict:
        """POST /api/locations — Create a location."""
        params = {"groups": str(groups).lower()}
        return self._post("locations", payload, query_params=params)

    def get_location(self, location_id: int) -> dict:
        """GET /api/locations/{id} — Return a location by ID."""
        return self._get(f"locations/{location_id}")

    def update_location(self, location_id: int, payload: dict) -> dict:
        """PUT /api/locations/{id} — Update a location."""
        return self._put(f"locations/{location_id}", payload)

    def delete_location(self, location_id: int) -> None:
        """DELETE /api/locations/{id} — Delete a location."""
        return self._delete(f"locations/{location_id}")

    def disable_location(self, location_id: int) -> dict:
        """PUT /api/locations/{id}/disable — Disable a location."""
        return self._put(f"locations/{location_id}/disable")

    def location_access_lock_control(self, location_id: int, is_locked: bool) -> dict:
        """PUT /api/locations/{id}/access/control — Lock or unlock location access."""
        return self._put(
            f"locations/{location_id}/access/control",
            query_params={"isLocked": str(is_locked).lower()},
        )

    def get_location_groups(self, location_id: int) -> dict:
        """GET /api/locations/{id}/groups — Return groups for a location."""
        return self._get(f"locations/{location_id}/groups")

    def update_location_groups(
        self, location_id: int, payload: dict, cascade: bool | None = None
    ) -> dict:
        """PUT /api/locations/{id}/groups — Update groups for a location."""
        params = {"cascade": str(cascade).lower()} if cascade is not None else None
        return self._put(
            f"locations/{location_id}/groups", payload, query_params=params
        )

    def update_location_group_override(
        self,
        location_id: int,
        group_id: int,
        payload: dict,
        cascade: bool | None = None,
    ) -> dict:
        """POST /api/locations/{id}/groups/{groupId}/override — Set group permission override."""
        params = {"cascade": str(cascade).lower()} if cascade is not None else None
        return self._post(
            f"locations/{location_id}/groups/{group_id}/override",
            payload,
            query_params=params,
        )

    def get_location_group_user_permissions(self, location_id: int) -> dict:
        """GET /api/locations/{id}/groups/user/permissions — Return user permissions for location."""
        return self._get(f"locations/{location_id}/groups/user/permissions")

    def get_location_group_user_access(self, location_id: int) -> dict:
        """GET /api/locations/{id}/groups/user/access — Return user operational permissions."""
        return self._get(f"locations/{location_id}/groups/user/access")

    def get_location_group_user_access_bulk(self, location_ids: list[int]) -> dict:
        """POST /api/locations/groups/user/access — Bulk-fetch user permissions for locations."""
        return self._post("locations/groups/user/access", location_ids)

    def get_location_groups_auditing(self, location_id: int) -> list:
        """GET /api/locations/{id}/groups/auditing — Return group audit log for a location."""
        return self._get(f"locations/{location_id}/groups/auditing")

    def get_location_tree(self, location_id: int) -> list:
        """GET /api/locations/{id}/tree — Return breadcrumb tree for a location."""
        return self._get(f"locations/{location_id}/tree")

    def get_child_locations(
        self, location_id: int, page_number: int = 1, page_size: int = 20
    ) -> dict:
        """GET /api/locations/{id}/locations — Return child locations."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
        }
        return self._get(f"locations/{location_id}/locations", params)

    def get_location_grid(self, location_id: int) -> list:
        """GET /api/locations/{id}/grid — Return grid positions for a location."""
        return self._get(f"locations/{location_id}/grid")

    def get_location_auditing(
        self,
        location_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/locations/{id}/auditing — Return audit log for a location."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"locations/{location_id}/auditing", params)

    def move_location(self, location_id: int, parent_id: int) -> None:
        """POST /api/locations/{id}/move/{parentId} — Move a location to a new parent."""
        return self._post(f"locations/{location_id}/move/{parent_id}")

    def clone_location(
        self,
        location_id: int,
        name: str | None = None,
        barcode: str | None = None,
    ) -> dict:
        """POST /api/locations/{id}/clone — Clone a location."""
        params = {}
        if name:
            params["name"] = name
        if barcode:
            params["barcode"] = barcode
        return self._post(f"locations/{location_id}/clone", query_params=params or None)

    def search_locations(
        self,
        query: str,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/locations/search — Search locations with vacant space."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "query": query,
        }
        return self._get("locations/search", params)

    def get_location_hierarchy(self, query: str | None = None) -> list:
        """GET /api/locations/hierarchy — Return root location hierarchy."""
        params = {"query": query} if query else None
        return self._get("locations/hierarchy", params)

    def get_location_hierarchy_by_id(
        self, location_id: int, query: str | None = None
    ) -> list:
        """GET /api/locations/hierarchy/{id} — Return hierarchy under a location."""
        params = {"query": query} if query else None
        return self._get(f"locations/hierarchy/{location_id}", params)

    def get_favorite_locations(self) -> list:
        """GET /api/locations/favorite — Return user's favorite locations."""
        return self._get("locations/favorite")

    def add_favorite_location(self, location_id: int) -> None:
        """POST /api/locations/favorite/{locationId} — Add a location to favorites."""
        return self._post(f"locations/favorite/{location_id}")

    def remove_favorite_location(self, location_id: int) -> None:
        """DELETE /api/locations/favorite/{locationId} — Remove a location from favorites."""
        return self._delete(f"locations/favorite/{location_id}")

    def import_locations(self, file: IO) -> bytes:
        """POST /api/locations/import — Import locations from an Excel file."""
        url = self._make_request_path("locations/import")
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def export_locations_xlsx(self) -> bytes:
        """GET /api/locations/export/xlsx — Export all locations as xlsx."""
        return self._get("locations/export/xlsx", raw=True).content

    def export_locations_xls(self) -> bytes:
        """GET /api/locations/export/xls — Export all locations as xls."""
        return self._get("locations/export/xls", raw=True).content

    def export_locations_csv(self) -> bytes:
        """GET /api/locations/export/csv — Export all locations as CSV."""
        return self._get("locations/export/csv", raw=True).content

    def get_location_xlsx_template(self) -> bytes:
        """GET /api/locations/template/xlsx — Download locations xlsx template."""
        return self._get("locations/template/xlsx", raw=True).content

    def get_location_xls_template(self) -> bytes:
        """GET /api/locations/template/xls — Download locations xls template."""
        return self._get("locations/template/xls", raw=True).content

    def get_location_csv_template(self) -> bytes:
        """GET /api/locations/template/csv — Download locations CSV template."""
        return self._get("locations/template/csv", raw=True).content

    def save_location_file(self, location_id: int, file: IO) -> dict:
        """POST /api/locations/{id}/file — Attach a file to a location."""
        return self._post(f"locations/{location_id}/file", files={"file": file})

    def get_location_file(self, location_id: int, file_id: int) -> bytes:
        """GET /api/locations/{locationId}/file/{id} — Download a location attachment."""
        return self._get(f"locations/{location_id}/file/{file_id}", raw=True).content

    def delete_location_file(self, location_id: int, file_id: int) -> None:
        """DELETE /api/locations/{locationId}/file/{id} — Delete a location attachment."""
        return self._delete(f"locations/{location_id}/file/{file_id}")

    # ------------------------------------------------------------------
    # Containers
    # ------------------------------------------------------------------

    def get_container(self, container_id: int) -> dict:
        """GET /api/containers/{id} — Return a container by ID."""
        return self._get(f"containers/{container_id}")

    # Alias kept for backwards compatibility
    fetch_container_by_id = get_container

    def update_container(self, container_id: int, payload: dict) -> dict:
        """PUT /api/containers/{id} — Update a container."""
        return self._put(f"containers/{container_id}", payload)

    def delete_container(self, container_id: int) -> None:
        """DELETE /api/containers/{id} — Delete a container."""
        return self._delete(f"containers/{container_id}")

    def enable_container(self, container_id: int) -> dict:
        """PUT /api/containers/{id}/enable — Enable a container."""
        return self._put(f"containers/{container_id}/enable")

    def disable_container(self, container_id: int) -> dict:
        """PUT /api/containers/{id}/disable — Disable a container."""
        return self._put(f"containers/{container_id}/disable")

    def get_containers_by_ids(self, container_ids: list[int]) -> list:
        """POST /api/containers — Fetch multiple containers by a list of IDs."""
        return self._post("containers", container_ids)

    def get_containers_by_location(
        self,
        location_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/locations/{locationId}/containers — List containers in a location."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get(f"locations/{location_id}/containers", params)

    def create_container_in_location(self, location_id: int, payload: dict) -> dict:
        """POST /api/locations/{locationId}/containers — Create a container in a location."""
        return self._post(f"locations/{location_id}/containers", payload)

    def create_batch_containers(self, location_id: int, payload: dict) -> dict:
        """POST /api/locations/{locationId}/containers/batch — Batch-create containers."""
        return self._post(f"locations/{location_id}/containers/batch", payload)

    def create_containers_bulk(
        self, payload: list[dict], allow_individual_fails: bool = False
    ) -> list:
        """POST /api/containers/create — Bulk-create containers."""
        params = {"allowIndividualFails": str(allow_individual_fails).lower()}
        return self._post("containers/create", payload, query_params=params)

    def update_containers_bulk(
        self, payload: list[dict], allow_individual_fails: bool = False
    ) -> list:
        """POST /api/containers/update — Bulk-update containers."""
        params = {"allowIndividualFails": str(allow_individual_fails).lower()}
        return self._post("containers/update", payload, query_params=params)

    def move_containers(
        self, location_id: int, new_location_id: int, payload: list[dict]
    ) -> str:
        """POST /api/locations/{locationId}/containers/move/{newLocationId} — Move containers."""
        return self._post(
            f"locations/{location_id}/containers/move/{new_location_id}", payload
        )

    def checkout_containers(
        self, location_id: int, new_location_id: int, container_ids: list[int]
    ) -> str:
        """POST /api/locations/{locationId}/containers/checkout/{newLocationId} — Check out containers."""
        return self._post(
            f"locations/{location_id}/containers/checkout/{new_location_id}",
            container_ids,
        )

    def checkout_containers_with_grid(
        self, location_id: int, new_location_id: int, payload: list[dict]
    ) -> None:
        """POST /api/v2/locations/{locationId}/containers/checkout/{newLocationId} — Check out with grid."""
        return self._post(
            f"v2/locations/{location_id}/containers/checkout/{new_location_id}", payload
        )

    def checkin_containers(self, container_ids: list[int]) -> None:
        """POST /api/containers/checkin — Check in containers."""
        return self._post("containers/checkin", container_ids)

    def get_checkout_containers(
        self,
        location_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/locations/{locationId}/containers/checkout — List checked-out containers."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get(f"locations/{location_id}/containers/checkout", params)

    def aliquot_containers(
        self, payload: list[dict], allow_individual_fails: bool = False
    ) -> list:
        """POST /api/containers/aliquot — Aliquot containers."""
        params = {"allowIndividualFails": str(allow_individual_fails).lower()}
        return self._post("containers/aliquot", payload, query_params=params)

    def validate_aliquot(self, payload: list[dict]) -> list:
        """POST /api/containers/aliquot/validate — Validate aliquot operation."""
        return self._post("containers/aliquot/validate", payload)

    def mix_containers(self, payload: list[dict]) -> None:
        """POST /api/containers/mix — Mix containers."""
        return self._post("containers/mix", payload)

    def dissolve_container(self, payload: list[dict]) -> None:
        """POST /api/containers/dissolve — Dissolve containers."""
        return self._post("containers/dissolve", payload)

    def get_dissolve_info(self, container_ids: list[int]) -> list:
        """POST /api/containers/dissolve/get — Get dissolve info for containers."""
        return self._post("containers/dissolve/get", container_ids)

    def reserve_container(
        self, container_id: int, reserve_for: str | None = None
    ) -> None:
        """POST /api/containers/{id}/reserve — Reserve a container."""
        params = {"reserveFor": reserve_for} if reserve_for else None
        return self._post(f"containers/{container_id}/reserve", query_params=params)

    def cancel_reserve_container(self, container_id: int) -> None:
        """DELETE /api/containers/{id}/reserve — Cancel a container reservation."""
        return self._delete(f"containers/{container_id}/reserve")

    def reserve_container_amount(
        self, container_id: int, amount: str, reserve_for: str | None = None
    ) -> None:
        """POST /api/containers/{id}/reserve_amount — Reserve an amount from a container."""
        params = {"amount": amount}
        if reserve_for:
            params["reserveFor"] = reserve_for
        return self._post(
            f"containers/{container_id}/reserve_amount", query_params=params
        )

    def update_container_amount(self, container_id: int, amount: str) -> None:
        """PUT /api/containers/reserve_amount/{id} — Update the reserved amount."""
        return self._put(
            f"containers/reserve_amount/{container_id}", query_params={"amount": amount}
        )

    def cancel_reserve_container_amount(self, container_id: int) -> None:
        """DELETE /api/containers/reserve_amount/{id} — Cancel amount reservation."""
        return self._delete(f"containers/reserve_amount/{container_id}")

    def get_container_template_name(self, payload: dict) -> str:
        """POST /api/containers/template/name — Get the template name for a container."""
        return self._post("containers/template/name", payload)

    def get_container_template_name_v2(self, payload: dict) -> str:
        """POST /api/containers/template/name/v2 — Get the template name (v2)."""
        return self._post("containers/template/name/v2", payload)

    def get_container_template_barcode(self, payload: dict) -> str:
        """POST /api/containers/template/barcode — Get the template barcode for a container."""
        return self._post("containers/template/barcode", payload)

    def get_container_template_barcode_v2(self, payload: dict) -> str:
        """POST /api/containers/template/barcode/v2 — Get the template barcode (v2)."""
        return self._post("containers/template/barcode/v2", payload)

    def get_aliquot_templates(self, payload: list[dict]) -> list:
        """POST /api/containers/template/v2 — Get name/barcode for aliquot containers."""
        return self._post("containers/template/v2", payload)

    def validate_container_barcode(self, barcode: str) -> None:
        """POST /api/containers/batch — Validate a container barcode."""
        return self._post("containers/batch", query_params={"barcode": barcode})

    def get_containers_by_batch_id(self, batch_id: str) -> dict:
        """POST /api/containers/batchId — Fetch containers by batch ID."""
        return self._post("containers/batchId", batch_id)

    def get_containers_list(
        self,
        is_disabled: bool,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/list/{isDisabled} — List enabled or disabled containers."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"list/{str(is_disabled).lower()}", params)

    def get_container_auditing(
        self,
        container_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/containers/{id}/auditing — Return audit log for a container."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"containers/{container_id}/auditing", params)

    def save_container_file(self, container_id: int, file: IO) -> dict:
        """POST /api/containers/{containerId}/file — Attach a file to a container."""
        return self._post(f"containers/{container_id}/file", files={"file": file})

    def get_container_file(self, container_id: int, file_id: int) -> bytes:
        """GET /api/containers/{containerId}/file/{id} — Download a container attachment."""
        return self._get(f"containers/{container_id}/file/{file_id}", raw=True).content

    def delete_container_file(self, container_id: int, file_id: int) -> None:
        """DELETE /api/containers/{containerId}/file/{id} — Delete a container attachment."""
        return self._delete(f"containers/{container_id}/file/{file_id}")

    def import_containers(
        self, file: IO, is_tare: bool = False, strategy: str = "FAILED"
    ) -> bytes:
        """POST /api/container/import — Import containers from an Excel file."""
        url = self._make_request_path(
            "container/import", {"isTare": str(is_tare).lower(), "strategy": strategy}
        )
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def export_containers_xlsx(self) -> bytes:
        """GET /api/container/export/xlsx — Export all containers as xlsx."""
        return self._get("container/export/xlsx", raw=True).content

    def export_containers_xlsx_by_location(
        self, location_id: int, cascade: bool | None = None
    ) -> bytes:
        """GET /api/container/export/xlsx/{locationId} — Export containers for a location."""
        params = {"cascade": str(cascade).lower()} if cascade is not None else None
        return self._get(
            f"container/export/xlsx/{location_id}", params, raw=True
        ).content

    def export_containers_xls(self) -> bytes:
        """GET /api/container/export/xls — Export all containers as xls."""
        return self._get("container/export/xls", raw=True).content

    def export_containers_xls_by_location(
        self, location_id: int, cascade: bool | None = None
    ) -> bytes:
        """GET /api/container/export/xls/{locationId} — Export containers for a location as xls."""
        params = {"cascade": str(cascade).lower()} if cascade is not None else None
        return self._get(
            f"container/export/xls/{location_id}", params, raw=True
        ).content

    def export_containers_csv(self) -> bytes:
        """GET /api/container/export/csv — Export all containers as CSV."""
        return self._get("container/export/csv", raw=True).content

    def export_containers_csv_by_location(
        self, location_id: int, cascade: bool | None = None
    ) -> bytes:
        """GET /api/container/export/csv/{locationId} — Export containers for a location as CSV."""
        params = {"cascade": str(cascade).lower()} if cascade is not None else None
        return self._get(
            f"container/export/csv/{location_id}", params, raw=True
        ).content

    def get_container_xlsx_template(self, is_tare: bool = False) -> bytes:
        """GET /api/container/template/xlsx — Download container xlsx template."""
        return self._get(
            "container/template/xlsx", {"isTare": str(is_tare).lower()}, raw=True
        ).content

    def get_container_xls_template(self, is_tare: bool = False) -> bytes:
        """GET /api/container/template/xls — Download container xls template."""
        return self._get(
            "container/template/xls", {"isTare": str(is_tare).lower()}, raw=True
        ).content

    def get_container_csv_template(self, is_tare: bool = False) -> bytes:
        """GET /api/container/template/csv — Download container CSV template."""
        return self._get(
            "container/template/csv", {"isTare": str(is_tare).lower()}, raw=True
        ).content

    # ------------------------------------------------------------------
    # Container Cycles
    # ------------------------------------------------------------------

    def get_container_cycles(self, container_id: int) -> dict:
        """GET /api/container/cycles/{containerId} — Return cycle status for a container."""
        return self._get(f"container/cycles/{container_id}")

    def assign_cycles_allowed(self, container_id: int, cycles_allowed: int) -> dict:
        """PUT /api/container/cycles/{containerId}/{cyclesAllowed} — Set cycles allowed."""
        return self._put(f"container/cycles/{container_id}/{cycles_allowed}")

    # ------------------------------------------------------------------
    # Plates
    # ------------------------------------------------------------------

    def get_plates(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/plates — List plates (paginated)."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get("plates", params)

    def create_plate(self, payload: dict) -> dict:
        """POST /api/plates — Create a plate."""
        return self._post("plates", payload)

    def get_plate(self, plate_id: int) -> dict:
        """GET /api/plates/{id} — Return a plate by ID."""
        return self._get(f"plates/{plate_id}")

    def update_plate(self, plate_id: int, payload: dict) -> dict:
        """PUT /api/plates/{id} — Update a plate."""
        return self._put(f"plates/{plate_id}", payload)

    def delete_plate(self, plate_id: int) -> None:
        """DELETE /api/plates/{id} — Delete a plate."""
        return self._delete(f"plates/{plate_id}")

    # ------------------------------------------------------------------
    # Samples
    # ------------------------------------------------------------------

    def get_sample(self, sample_type_id: int, formatted_id: str) -> dict:
        """GET /api/samples/{sampleTypeId} — Return sample data by type and formatted ID."""
        return self._get(f"samples/{sample_type_id}", {"formattedId": formatted_id})

    def get_sample_by_path(self, sample_type_id: int, formatted_id: str) -> dict:
        """GET /api/samples/{sampleTypeId}/{formattedId} — Return sample by path params."""
        return self._get(f"samples/{sample_type_id}/{formatted_id}")

    def validate_sample(self, sample_type_id: int, formatted_id: str) -> None:
        """GET /api/samples/validate/{sampleTypeId} — Validate a sample."""
        return self._get(
            f"samples/validate/{sample_type_id}", {"formattedId": formatted_id}
        )

    def validate_sample_by_path(self, sample_type_id: int, formatted_id: str) -> None:
        """GET /api/samples/validate/{sampleTypeId}/{formattedId} — Validate sample by path."""
        return self._get(f"samples/validate/{sample_type_id}/{formatted_id}")

    def render_smile(self, payload: dict) -> bytes:
        """POST /api/samples/smile — Render a SMILES structure.

        Returns the rendered depiction bytes (the endpoint replies with a
        non-JSON body, e.g. SVG, so the response is returned raw rather than
        JSON-decoded). ``payload`` is a SmileDTO, e.g. ``{"smile": "CCO"}``.
        """
        url = self._make_request_path("samples/smile")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def wrap_text_to_file(self, text: str, extension: str) -> bytes:
        """POST /api/samples/wrapTextToFile/{extension} — Wrap text content into a file."""
        url = self._make_request_path(f"samples/wrapTextToFile/{extension}")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=text,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def quick_search(self, query: str) -> dict:
        """GET /api/search — Quick-search across locations and containers."""
        return self._get("search", {"query": query})

    def search_locations_quick(
        self,
        query: str,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/search/locations — Quick-search locations."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "query": query,
        }
        return self._get("search/locations", params)

    def search_containers_quick(
        self,
        query: str,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/search/containers — Quick-search containers."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "query": query,
        }
        return self._get("search/containers", params)

    def search_containers_heavy(
        self,
        query: str,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/search/containers/heavy — Heavy search for containers."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "query": query,
        }
        return self._get("search/containers/heavy", params)

    # ------------------------------------------------------------------
    # Calculator
    # ------------------------------------------------------------------

    def calculate(self, var1: float, var2: float, operation: str) -> dict:
        """POST /api/calculator — Evaluate a mathematical expression."""
        return self._post(
            "calculator", {"var1": var1, "var2": var2, "operation": operation}
        )

    # ------------------------------------------------------------------
    # Cart
    # ------------------------------------------------------------------

    def get_cart(
        self, page: int = 0, size: int = 20, filter: str | None = None
    ) -> dict:
        """GET /api/cart — Return the current user's cart."""
        params = {"pageable.page": page, "pageable.size": size}
        if filter:
            params["filter"] = filter
        return self._get("cart", params)

    def add_to_cart(self, container_ids: list[int]) -> None:
        """POST /api/cart — Add containers to the cart."""
        return self._post("cart", container_ids)

    def remove_from_cart(self, payload: dict) -> None:
        """DELETE /api/cart — Remove containers from the cart."""
        return self._delete("cart", payload)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def get_notifications(self, page: int = 0, size: int = 20) -> dict:
        """GET /api/notifications — Return the current user's notifications."""
        return self._get(
            "notifications", {"pageable.page": page, "pageable.size": size}
        )

    def mark_notification_read(self, notification_id: int) -> None:
        """POST /api/notifications/{id}/read — Mark a notification as read."""
        return self._post(f"notifications/{notification_id}/read")

    def mark_notifications_read_bulk(self, payload: dict) -> None:
        """POST /api/notifications/read — Bulk mark notifications as read."""
        return self._post("notifications/read", payload)

    def delete_notification(self, notification_id: int) -> None:
        """DELETE /api/notifications/{id} — Delete a notification."""
        return self._delete(f"notifications/{notification_id}")

    def delete_read_notifications(self) -> None:
        """DELETE /api/notifications/read — Delete all read notifications."""
        return self._delete("notifications/read")

    def delete_notifications_bulk(self, payload: dict) -> None:
        """DELETE /api/notifications — Bulk-delete notifications."""
        return self._delete("notifications", payload)

    # ------------------------------------------------------------------
    # Depictor (barcode / QR code)
    # ------------------------------------------------------------------

    def render_barcode(
        self,
        value: str,
        height: int = 50,
        width: int = 200,
        position: str | None = None,
    ) -> bytes:
        """GET /api/public/depictor/barcode — Render a barcode image."""
        params = {"value": value, "height": height, "width": width}
        if position:
            params["position"] = position
        return self._get("public/depictor/barcode", params, raw=True).content

    def render_barcode_post(self, payload: dict) -> bytes:
        """POST /api/public/depictor/barcode — Render a barcode image (POST)."""
        url = self._make_request_path("public/depictor/barcode")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def render_barcode_pdf(
        self, value: str, height: int = 50, width: int = 200
    ) -> bytes:
        """GET /api/public/depictor/barcode/pdf — Render a barcode as PDF."""
        params = {"value": value, "height": height, "width": width}
        return self._get("public/depictor/barcode/pdf", params, raw=True).content

    def render_barcode_pdf_post(self, payload: dict) -> bytes:
        """POST /api/public/depictor/barcode/pdf — Render a barcode as PDF (POST)."""
        url = self._make_request_path("public/depictor/barcode/pdf")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def render_qrcode(self, value: str, height: int = 200, width: int = 200) -> bytes:
        """GET /api/public/depictor/qrcode — Render a QR code image."""
        params = {"value": value, "height": height, "width": width}
        return self._get("public/depictor/qrcode", params, raw=True).content

    def render_qrcode_post(self, payload: dict) -> bytes:
        """POST /api/public/depictor/qrcode — Render a QR code image (POST)."""
        url = self._make_request_path("public/depictor/qrcode")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    def render_qrcode_pdf(
        self, value: str, height: int = 200, width: int = 200
    ) -> bytes:
        """GET /api/public/depictor/qrcode/pdf — Render a QR code as PDF."""
        params = {"value": value, "height": height, "width": width}
        return self._get("public/depictor/qrcode/pdf", params, raw=True).content

    def render_qrcode_pdf_post(self, payload: dict) -> bytes:
        """POST /api/public/depictor/qrcode/pdf — Render a QR code as PDF (POST)."""
        url = self._make_request_path("public/depictor/qrcode/pdf")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=payload,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    # ------------------------------------------------------------------
    # Labvoice
    # ------------------------------------------------------------------

    def get_labvoice_container(self, barcode: str) -> dict:
        """GET /api/labvoice/containers — Return container info by barcode (Labvoice)."""
        return self._get("labvoice/containers", {"barcode": barcode})

    # ------------------------------------------------------------------
    # Import History
    # ------------------------------------------------------------------

    def get_import_history(
        self,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        """GET /api/import/history — Return Excel import audit history."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        return self._get("import/history", params)

    def delete_import_history(self, history_id: int) -> None:
        """DELETE /api/import/history/{id} — Delete an import history record."""
        return self._delete(f"import/history/{history_id}")

    def get_import_file(self, file_id: int) -> bytes:
        """GET /api/import/files/{id} — Download an import file."""
        return self._get(f"import/files/{file_id}", raw=True).content

    def delete_import_file(self, file_id: int) -> None:
        """DELETE /api/import/files/{id} — Delete an import file."""
        return self._delete(f"import/files/{file_id}")

    def delete_import_files_bulk(self, payload: dict) -> None:
        """DELETE /api/import/files — Bulk-delete import files."""
        return self._delete("import/files", payload)

    # ------------------------------------------------------------------
    # Migration
    # ------------------------------------------------------------------

    def start_migration(self) -> str:
        """PUT /api/migration/start — Start a data migration."""
        return self._put("migration/start")

    def get_migration_status(self) -> dict:
        """GET /api/migration/status — Return the last migration log entry."""
        return self._get("migration/status")

    def get_all_migration_logs(
        self, page_number: int = 1, page_size: int = 20, sort: str | None = None
    ) -> dict:
        """GET /api/migration/status/all — Return all migration log entries."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get("migration/status/all", params)

    def get_migration_audit(
        self,
        migration_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
    ) -> dict:
        """GET /api/migration/audit/{id} — Return audit for a specific migration run."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
        }
        return self._get(f"migration/audit/{migration_id}", params)

    def get_migration_locations(self) -> dict:
        """GET /api/migration/locations — Return locations pending migration."""
        return self._get("migration/locations")

    def delete_migration_locations(self, location_ids: list[int]) -> None:
        """DELETE /api/migration/locations — Delete migration locations by ID list."""
        return self._delete("migration/locations", location_ids)

    def get_migration_location(self, location_id: int) -> dict:
        """GET /api/migration/locations/{id} — Return a migration location by ID."""
        return self._get(f"migration/locations/{location_id}")

    def delete_migration_location(self, location_id: int) -> None:
        """DELETE /api/migration/locations/{id} — Delete a single migration location."""
        return self._delete(f"migration/locations/{location_id}")

    def search_migration_locations(self, query: str) -> dict:
        """GET /api/migration/locations/search — Search migration locations."""
        return self._get("migration/locations/search", {"query": query})

    def get_migration_location_hierarchy(self) -> list:
        """GET /api/migration/locations/hierarchy — Return migration location hierarchy."""
        return self._get("migration/locations/hierarchy")

    def get_migration_location_hierarchy_by_id(self, location_id: int) -> list:
        """GET /api/migration/locations/hierarchy/{id} — Return sub-hierarchy."""
        return self._get(f"migration/locations/hierarchy/{location_id}")

    def get_migration_containers(
        self,
        location_id: int,
        page_number: int = 1,
        page_size: int = 20,
        sort: str | None = None,
        filter: str = "",
    ) -> dict:
        """GET /api/migration/locations/{locationId}/containers — List migration containers."""
        params = {
            "paginationConfigurationFilter.pageNumber": page_number,
            "paginationConfigurationFilter.pageSize": page_size,
            "sortConfigurationFilter.sort": sort or "",
            "filter": filter,
        }
        return self._get(f"migration/locations/{location_id}/containers", params)

    def get_migration_container(self, container_id: int) -> dict:
        """GET /api/migration/containers/{id} — Return a migration container by ID."""
        return self._get(f"migration/containers/{container_id}")

    def delete_migration_container(self, container_id: int) -> None:
        """DELETE /api/migration/containers/{id} — Delete a single migration container."""
        return self._delete(f"migration/containers/{container_id}")

    def delete_migration_containers(self, container_ids: list[int]) -> None:
        """DELETE /api/migration/containers — Bulk-delete migration containers."""
        return self._delete("migration/containers", container_ids)

    # ------------------------------------------------------------------
    # Integration
    # ------------------------------------------------------------------

    def integration_get_units(self) -> dict:
        """GET /api/integration/units — Retrieve all units (integration)."""
        return self._get("integration/units")

    def integration_get_sample_types(self) -> dict:
        """GET /api/integration/sample/types — Retrieve all sample types (integration)."""
        return self._get("integration/sample/types")

    def integration_get_sample_types_by_query(self, query: str) -> dict:
        """GET /api/integration/sample/types/{query} — Retrieve sample types by query."""
        return self._get(f"integration/sample/types/{query}")

    def integration_get_locations(self) -> dict:
        """GET /api/integration/locations — Retrieve locations for user's groups."""
        return self._get("integration/locations")

    def integration_get_location_absolute_path(
        self,
        query: str,
        sort: str = "DESC",
        page_number: int = 1,
        page_size: int = 20,
        samples: int | None = None,
    ) -> dict:
        """GET /api/integration/locations/absolute/path — Search locations by barcode query."""
        params = {
            "query": query,
            "sort": sort,
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        if samples is not None:
            params["samples"] = samples
        return self._get("integration/locations/absolute/path", params)

    def integration_get_location_absolute_path_by_id(self, location_id: int) -> str:
        """GET /api/integration/locations/absolute/path/{id} — Get path by location ID."""
        return self._get(f"integration/locations/absolute/path/{location_id}")

    def integration_get_location_absolute_paths_bulk(
        self, location_ids: list[int]
    ) -> str:
        """POST /api/integration/locations/absolute/path/bulk — Get paths for multiple IDs."""
        return self._post("integration/locations/absolute/path/bulk", location_ids)

    def integration_get_location_by_container_type(
        self, type_name: str, location_barcode: str
    ) -> dict:
        """GET /api/integration/location/{typeName}/{locationBarcode} — Get location by container type."""
        return self._get(f"integration/location/{type_name}/{location_barcode}")

    def integration_get_container_type_custom_fields(self) -> dict:
        """GET /api/integration/custom/fields — Get custom fields for active container types."""
        return self._get("integration/custom/fields")

    def integration_get_container_types(
        self, query: str, sort: str = "DESC", page_number: int = 1, page_size: int = 20
    ) -> dict:
        """GET /api/integration/container/type — Search container types (paginated)."""
        return self._get(
            "integration/container/type",
            {
                "query": query,
                "sort": sort,
                "pageNumber": page_number,
                "pageSize": page_size,
            },
        )

    def integration_get_container_types_by_query(self, query: str):
        """GET /api/integration/container/type/query/{query} — Search container types by query."""
        return self._get(f"integration/container/type/query/{query}")

    def integration_get_container_types_by_location(
        self,
        location_id: int,
        sort: str = "DESC",
        page_number: int = 1,
        page_size: int = 20,
    ) -> dict:
        """GET /api/integration/container/type/location/id/{id} — Container types for a location."""
        return self._get(
            f"integration/container/type/location/id/{location_id}",
            {"sort": sort, "pageNumber": page_number, "pageSize": page_size},
        )

    def integration_get_all_container_types(
        self, sort: str = "DESC", page_number: int = 1, page_size: int = 20
    ) -> dict:
        """GET /api/integration/container/type/all — All enabled container types (paginated)."""
        return self._get(
            "integration/container/type/all",
            {"sort": sort, "pageNumber": page_number, "pageSize": page_size},
        )

    def integration_get_allowed_containers_for_location(self, barcode: str) -> dict:
        """GET /api/integration/container/names/{barcode} — Allowed containers for a location barcode."""
        return self._get(f"integration/container/names/{barcode}")

    def integration_get_container_core_fields(self, container_type_id: int) -> dict:
        """GET /api/integration/container/fields/{containerTypeId} — Core fields for a container type."""
        return self._get(f"integration/container/fields/{container_type_id}")

    def integration_create_container(self, payload: dict) -> dict:
        """POST /api/integration/container — Create a container (integration)."""
        return self._post("integration/container", payload)

    def integration_get_template_name(self, payload: dict) -> str:
        """POST /api/integration/container/containers/template/name — Get template name."""
        return self._post("integration/container/containers/template/name", payload)

    def integration_get_template_name_v2(self, payload: dict) -> str:
        """POST /api/integration/container/containers/template/name/v2 — Get template name (v2)."""
        return self._post("integration/container/containers/template/name/v2", payload)

    def integration_get_template_barcode(self, payload: dict) -> str:
        """POST /api/integration/container/containers/template/barcode — Get template barcode."""
        return self._post("integration/container/containers/template/barcode", payload)

    def integration_get_template_barcode_v2(self, payload: dict) -> str:
        """POST /api/integration/container/containers/template/barcode/v2 — Get template barcode (v2)."""
        return self._post(
            "integration/container/containers/template/barcode/v2", payload
        )

    def integration_create_samples(self, payload: list[dict]) -> dict:
        """POST /api/integration/create/samples — Batch-create samples (integration)."""
        return self._post("integration/create/samples", payload)

    def integration_import_programmatic(
        self, file: IO, strategy: str = "FAILED"
    ) -> None:
        """POST /api/integration/import/programatic — Import containers programmatically."""
        url = self._make_request_path(
            "integration/import/programatic", {"strategy": strategy}
        )
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code not in (200, 201, 204):
            raise ValueError(
                {"status": response.status_code, "response": response.text}
            )

    def integration_import_sdf(
        self, sample: str, file: IO, strategy: str = "FAILED"
    ) -> bytes:
        """POST /api/integration/sdf/import/{sample} — Import SDF file (integration)."""
        url = self._make_request_path(
            f"integration/sdf/import/{sample}", {"strategy": strategy}
        )
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    # ------------------------------------------------------------------
    # Configuration Staging
    # ------------------------------------------------------------------

    def upload_configuration(self, file: IO, is_check_mode: bool = False) -> dict:
        """POST /api/configuration/staging/upload — Upload a configuration bundle."""
        url = self._make_request_path(
            "configuration/staging/upload", {"isCheckMode": str(is_check_mode).lower()}
        )
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.json()
        raise ValueError({"status": response.status_code, "response": response.text})

    def create_configuration(self, staged_types: list[str]) -> bytes:
        """POST /api/configuration/staging/create — Create a configuration export file."""
        url = self._make_request_path("configuration/staging/create")
        response = self._session.post(
            url,
            headers=self._headers(),
            json=staged_types,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})

    # ------------------------------------------------------------------
    # User Group Excel Import/Export
    # ------------------------------------------------------------------

    def get_usergroup_xlsx_template(self) -> bytes:
        """GET /api/usergroup/template/xlsx — Download user group xlsx template."""
        return self._get("usergroup/template/xlsx", raw=True).content

    def get_usergroup_xls_template(self) -> bytes:
        """GET /api/usergroup/template/xls — Download user group xls template."""
        return self._get("usergroup/template/xls", raw=True).content

    def get_usergroup_csv_template(self) -> bytes:
        """GET /api/usergroup/template/csv — Download user group CSV template."""
        return self._get("usergroup/template/csv", raw=True).content

    def import_usergroup(self, file: IO) -> bytes:
        """POST /api/usergroup/import — Import user groups from a file."""
        url = self._make_request_path("usergroup/import")
        response = self._session.post(
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            files={"file": file},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response.content
        raise ValueError({"status": response.status_code, "response": response.text})
