import json
from unittest.mock import MagicMock, patch

import pytest

from dotmatics_api import AuthenticationError, Browser

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_browser(projects=None, datasources=None):
    """Return a lazy Browser with auth mocked out and optional pre-populated indices."""
    token = {"token": "fake-token"}
    with patch.object(Browser, "_authenticate", return_value=token):
        b = Browser(
            user="u",
            password="p",
            dotmatics_instance="https://demo.example.org",
            lazy=True,
        )

    if projects is not None:
        b.projects_by_id = projects
        b.projects_by_name = {v["projectName"]: v for v in projects.values()}
    if datasources is not None:
        b.datasources_by_id = datasources
        b.datasources_by_name = {
            b.projects_by_id[pid]["projectName"]: {
                dsinfo["name"]: dsinfo for dsinfo in ds.values()
            }
            for pid, ds in datasources.items()
        }
    return b


PROJECTS = {
    "10": {
        "projectID": "10",
        "projectName": "Assays",
        "dataSources": {
            "101": {"dsID": "101", "name": "DEMO_PLATE_RESULTS_VW"},
            "102": {"dsID": "102", "name": "DEMO_COMPOUND_VW"},
        },
    },
}

DATASOURCES = {
    "10": {
        "101": {"dsID": "101", "name": "DEMO_PLATE_RESULTS_VW"},
        "102": {"dsID": "102", "name": "DEMO_COMPOUND_VW"},
    }
}


# ---------------------------------------------------------------------------
# __init__ URL validation
# ---------------------------------------------------------------------------


class TestInitURLValidation:
    def _make(self, url):
        with patch.object(Browser, "_authenticate", return_value={}):
            with patch.object(Browser, "_populate_projects"):
                with patch.object(Browser, "_populate_datasources"):
                    return Browser(user="u", password="p", dotmatics_instance=url)

    def test_valid_https(self):
        self._make("https://demo.example.org")

    def test_valid_http(self):
        self._make("http://demo.example.org")

    def test_accepts_custom_host(self):
        self._make("https://custom.example.org:8443")

    def test_rejects_bad_scheme(self):
        with pytest.raises(ValueError):
            self._make("ftp://demo.example.org")

    def test_rejects_url_with_path(self):
        with pytest.raises(ValueError):
            self._make("https://demo.example.org/extra")

    def test_rejects_url_with_query(self):
        with pytest.raises(ValueError):
            self._make("https://demo.example.org?foo=bar")


# ---------------------------------------------------------------------------
# _make_request_path
# ---------------------------------------------------------------------------


class TestMakeRequestPath:
    def setup_method(self):
        self.b = make_browser()

    def test_basic_endpoint(self):
        url = self.b._make_request_path("projects/")
        assert url == "https://demo.example.org/browser/api/projects/"

    def test_endpoint_with_query_params(self):
        url = self.b._make_request_path(
            "authenticate/requestToken", {"expiration": 86400}
        )
        assert "expiration=86400" in url
        assert url.startswith("https://demo.example.org/browser/api/")

    def test_rejects_leading_slash(self):
        with pytest.raises(ValueError):
            self.b._make_request_path("/projects/")

    def test_rejects_endpoint_with_question_mark(self):
        with pytest.raises(ValueError):
            self.b._make_request_path("projects/?foo=bar")


# ---------------------------------------------------------------------------
# AuthenticationError
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_raises_on_401(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        with patch("requests.Session.get", return_value=mock_response):
            with pytest.raises(AuthenticationError):
                Browser(
                    user="u",
                    password="wrong",
                    dotmatics_instance="https://demo.example.org",
                    lazy=True,
                )

    def test_token_auth_skips_authenticate(self):
        with patch.object(Browser, "_authenticate") as mock_auth:
            with patch.object(Browser, "_populate_projects"):
                with patch.object(Browser, "_populate_datasources"):
                    b = Browser(
                        user="u",
                        token={"token": "t"},
                        dotmatics_instance="https://demo.example.org",
                    )
        mock_auth.assert_not_called()
        assert b.token == {"token": "t"}


# ---------------------------------------------------------------------------
# _normalize_project_ds_ids
# ---------------------------------------------------------------------------


class TestNormalizeProjectDsIds:
    def setup_method(self):
        self.b = make_browser(projects=PROJECTS, datasources=DATASOURCES)

    def test_name_to_id(self):
        pname, pid, dsnames, dsids = self.b._normalize_project_ds_ids(
            project="Assays", datasources=["DEMO_PLATE_RESULTS_VW"]
        )
        assert pid == "10"
        assert dsids == ["101"]
        assert pname == "Assays"
        assert dsnames == ["DEMO_PLATE_RESULTS_VW"]

    def test_id_to_name(self):
        pname, pid, dsnames, dsids = self.b._normalize_project_ds_ids(
            pid="10", dsids=["101"]
        )
        assert pname == "Assays"
        assert dsnames == ["DEMO_PLATE_RESULTS_VW"]

    def test_multiple_datasources(self):
        _, _, dsnames, dsids = self.b._normalize_project_ds_ids(
            pid="10", dsids=["101", "102"]
        )
        assert dsids == ["101", "102"]
        assert dsnames == ["DEMO_PLATE_RESULTS_VW", "DEMO_COMPOUND_VW"]

    def test_raises_if_both_project_and_pid(self):
        with pytest.raises(ValueError):
            self.b._normalize_project_ds_ids(project="Assays", pid="10", dsids=["101"])

    def test_raises_if_neither_project_nor_pid(self):
        with pytest.raises(ValueError):
            self.b._normalize_project_ds_ids(dsids=["101"])

    def test_raises_if_both_datasources_and_dsids(self):
        with pytest.raises(ValueError):
            self.b._normalize_project_ds_ids(
                pid="10", datasources=["DEMO_PLATE_RESULTS_VW"], dsids=["101"]
            )

    def test_raises_if_neither_datasources_nor_dsids(self):
        with pytest.raises(ValueError):
            self.b._normalize_project_ds_ids(pid="10")

    def test_ids_are_coerced_to_strings(self):
        _, pid, _, dsids = self.b._normalize_project_ds_ids(pid=10, dsids=[101])
        assert pid == "10"
        assert dsids == ["101"]


# ---------------------------------------------------------------------------
# fetch_data routing
# ---------------------------------------------------------------------------


class TestFetchDataRouting:
    def setup_method(self):
        self.b = make_browser(projects=PROJECTS, datasources=DATASOURCES)

    def test_single_id_uses_get(self):
        with patch.object(self.b, "_get", return_value={}) as mock_get:
            self.b.fetch_data(pid="10", dsids=["101"], ids=["ABC123"])
        mock_get.assert_called_once()
        assert "ABC123" in mock_get.call_args[0][0]

    def test_wildcard_uses_get(self):
        with patch.object(self.b, "_get", return_value={}) as mock_get:
            self.b.fetch_data(pid="10", dsids=["101"])
        mock_get.assert_called_once()

    def test_multiple_ids_uses_post(self):
        with patch.object(self.b, "_post", return_value={}) as mock_post:
            self.b.fetch_data(pid="10", dsids=["101"], ids=["A1", "A2"])
        mock_post.assert_called_once()

    def test_string_ids_raises_type_error(self):
        with pytest.raises(TypeError):
            self.b.fetch_data(pid="10", dsids=["101"], ids="ABC123")

    def test_wildcard_mixed_with_ids_raises_value_error(self):
        with pytest.raises(ValueError):
            self.b.fetch_data(pid="10", dsids=["101"], ids=["*", "A1"])

    def test_limit_and_offset_included_in_params(self):
        with patch.object(self.b, "_get", return_value={}) as mock_get:
            self.b.fetch_data(pid="10", dsids=["101"], limit=10, offset=5)
        query_params = mock_get.call_args[0][1]
        assert query_params["limit"] == 10
        assert query_params["offset"] == 5

    def test_negative_limit_omitted_from_params(self):
        with patch.object(self.b, "_get", return_value={}) as mock_get:
            self.b.fetch_data(pid="10", dsids=["101"])
        query_params = mock_get.call_args[0][1]
        assert "limit" not in query_params
        assert "offset" not in query_params


# ---------------------------------------------------------------------------
# run_query routing
# ---------------------------------------------------------------------------


class TestRunQueryRouting:
    def setup_method(self):
        self.b = make_browser(projects=PROJECTS, datasources=DATASOURCES)

    def test_single_dsid_uses_get(self):
        with patch.object(self.b, "_get", return_value={}) as mock_get:
            self.b.run_query(
                column="BATCH_ID",
                operator="equals",
                value="X",
                pid="10",
                dsids=["101"],
            )
        mock_get.assert_called_once()
        assert "BATCH_ID" in mock_get.call_args[0][0]
        assert "equals" in mock_get.call_args[0][0]

    def test_multiple_dsids_uses_post(self):
        with patch.object(self.b, "_post", return_value={}) as mock_post:
            self.b.run_query(
                column="BATCH_ID",
                operator="equals",
                value="X",
                pid="10",
                dsids=["101", "102"],
            )
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# _delete helper
# ---------------------------------------------------------------------------


class TestDelete:
    def setup_method(self):
        self.b = make_browser()

    def test_delete_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": "deleted"}'
        with patch("requests.Session.delete", return_value=mock_response) as mock_del:
            result = self.b._delete("studies/experiment/42")
        mock_del.assert_called_once()
        assert result["status"] == "ok"

    def test_delete_raises_on_non_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"status": "error", "message": "not found"}'
        with patch("requests.Session.delete", return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                self.b._delete("studies/experiment/99")
        assert exc_info.value.args[0]["status_code"] == 404

    def test_delete_raises_on_error_status(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "error", "message": "cannot delete"}'
        with patch("requests.Session.delete", return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                self.b._delete("studies/experiment/99")
        assert exc_info.value.args[0]["message"] == "cannot delete"

    def test_delete_sends_bearer_token(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.delete", return_value=mock_response) as mock_del:
            self.b._delete("studies/experiment/1")
        headers = mock_del.call_args[1]["headers"]
        assert headers["Authorization"].startswith("Bearer ")


# ---------------------------------------------------------------------------
# _post — thin dispatcher
# ---------------------------------------------------------------------------


class TestPostDispatcher:
    def setup_method(self):
        self.b = make_browser(projects=PROJECTS, datasources=DATASOURCES)

    def _ok(self):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {}
        m.text = json.dumps({})
        return m

    def test_sets_content_type_header_for_json(self):
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post(
                "some/endpoint", data='{"x":1}', content_type="application/json"
            )
        headers = mock_post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_does_not_set_content_type_for_multipart(self):
        """requests must add the Content-Type with boundary for multipart."""
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post(
                "some/endpoint",
                {},
                files={"f": ("a.sdf", b"")},
                content_type="multipart/form-data",
            )
        headers = mock_post.call_args[1]["headers"]
        assert "Content-Type" not in headers

    def test_omits_content_type_when_none(self):
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post("some/endpoint", data={"key": "val"})
        headers = mock_post.call_args[1]["headers"]
        assert "Content-Type" not in headers

    def test_passes_data_and_files_to_requests(self):
        """_post sends data through verbatim; callers pre-encode the body."""
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post("ep", data={"k": "v"}, files={"f": ("x", b"")})
        assert mock_post.call_args[1]["data"] == {"k": "v"}
        assert "f" in mock_post.call_args[1]["files"]

    def test_post_json_encodes_body(self):
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_json("ep", data={"k": "v"})
        assert mock_post.call_args[1]["data"] == '{"k": "v"}'
        headers = mock_post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_post_json_with_none_data_sends_no_body(self):
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_json("ep", data=None)
        assert mock_post.call_args[1]["data"] is None

    def test_raises_on_non_200(self):
        m = MagicMock()
        m.status_code = 500
        m.text = "error"
        with patch("requests.Session.post", return_value=m):
            with pytest.raises(ValueError):
                self.b._post("ep", {})

    def test_fetch_data_post_sends_ids_in_data_form_field(self):
        """IDs go in a form-encoded 'data' field holding a JSON array."""
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.fetch_data(pid="10", dsids=["101"], ids=["ID1", "ID2"])
        form = mock_post.call_args[1]["data"]
        assert set(form) == {"data"}
        body = json.loads(form["data"])
        assert "ID1" in body
        assert "ID2" in body
        # No manual Content-Type: requests must set the urlencoded one itself.
        assert "Content-Type" not in mock_post.call_args[1]["headers"]

    def test_run_query_post_sends_params_in_data_form_field(self):
        """Query params go in a form-encoded 'data' field holding a JSON object."""
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.run_query(
                column="COL",
                operator="equals",
                value="X",
                pid="10",
                dsids=["101", "102"],
            )
        form = mock_post.call_args[1]["data"]
        assert set(form) == {"data"}
        body = json.loads(form["data"])
        assert "params" in body


# ---------------------------------------------------------------------------
# _post_files token injection (multipart)
# ---------------------------------------------------------------------------


class TestPostFilesTokenInjection:
    def setup_method(self):
        self.b = make_browser()

    def _ok(self):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = 42
        m.text = json.dumps(42)
        return m

    def test_file_is_in_multipart_body_not_url(self, tmp_path):
        """File must be sent as a multipart body part, not appended to the URL."""
        f = tmp_path / "mol.sdf"
        f.write_text("content")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_files(
                "register/sdf/upload", files={"uploadFile": ("mol.sdf", f.open("rb"))}
            )
        url = mock_post.call_args[0][0]
        assert "mol.sdf" not in url
        call_files = mock_post.call_args[1]["files"]
        assert "uploadFile" in call_files

    def test_extra_query_params_are_preserved(self, tmp_path):
        f = tmp_path / "mol.sdf"
        f.write_text("content")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_files(
                "register/sdf/upload",
                files={"uploadFile": ("mol.sdf", f.open("rb"))},
                query_params={"extra": "val"},
            )
        url = mock_post.call_args[0][0]
        assert "extra=val" in url

    def test_content_type_header_not_set_manually(self, tmp_path):
        """requests must set Content-Type with boundary for multipart."""
        f = tmp_path / "mol.sdf"
        f.write_text("content")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_files(
                "register/sdf/upload", files={"uploadFile": ("mol.sdf", f.open("rb"))}
            )
        headers = mock_post.call_args[1]["headers"]
        assert "Content-Type" not in headers


# ---------------------------------------------------------------------------
# put() Content-Type
# ---------------------------------------------------------------------------


class TestPutContentType:
    def setup_method(self):
        self.b = make_browser()

    def test_put_json_sends_json_content_type(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.put", return_value=mock_response) as mock_put:
            self.b._put_json("studies/experiment", data={"name": "test"})
        headers = mock_put.call_args[1]["headers"]
        assert headers.get("Content-Type") == "application/json"

    def test_put_omits_content_type_by_default(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.put", return_value=mock_response) as mock_put:
            self.b._put("studies/experiment", data={"name": "test"})
        headers = mock_put.call_args[1]["headers"]
        assert "Content-Type" not in headers

    def test_put_json_body_is_json_dict(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.put", return_value=mock_response) as mock_put:
            self.b._put_json("studies/experiment", data={"name": "test"})
        body = json.loads(mock_put.call_args[1]["data"])
        assert isinstance(body, dict)
        assert body["name"] == "test"

    def test_put_passes_data_through_verbatim(self):
        """_put sends data unmodified; callers pre-encode the body."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.put", return_value=mock_response) as mock_put:
            self.b._put("studies/experiment", data={"name": "test"})
        assert mock_put.call_args[1]["data"] == {"name": "test"}

    def test_put_raises_on_error_status(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "error", "message": "bad request"}'
        with patch("requests.Session.put", return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                self.b._put("studies/experiment")
        assert exc_info.value.args[0]["message"] == "bad request"


# ---------------------------------------------------------------------------
# create_experiment
# ---------------------------------------------------------------------------


class TestCreateExperiment:
    def setup_method(self):
        self.b = make_browser()

    def _ok_response(self):
        m = MagicMock()
        m.status_code = 200
        m.text = '{"status": "ok", "message": "created", "experimentID": 101}'
        return m

    def test_calls_put_with_correct_endpoint(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.create_experiment(protocol_id=1, owner_isid="jdoe", name="Test Exp")
        url = mock_put.call_args[0][0]
        assert "/browser/api/studies/experiment" in url

    def test_payload_contains_required_fields(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.create_experiment(
                protocol_id=5,
                owner_isid="jdoe",
                name="My Exp",
                description="desc",
                project_id=1000,
                automated="Y",
                properties=[{"propertyName": "p", "propertyValue": "v"}],
            )
        # create_experiment uses _put_json which sends a plain object (not a
        # token-wrapped list), matching what the Dotmatics API actually expects.
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert isinstance(sent_body, dict)
        assert sent_body["protocol"]["protocolID"] == 5
        assert sent_body["ownerISID"] == "jdoe"
        assert sent_body["name"] == "My Exp"
        assert sent_body["description"] == "desc"
        assert sent_body["projectId"] == 1000
        assert sent_body["automated"] == "Y"
        assert sent_body["properties"] == [{"propertyName": "p", "propertyValue": "v"}]

    def test_optional_project_id_omitted_when_none(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.create_experiment(protocol_id=1, owner_isid="u", name="N")
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert "projectId" not in sent_body

    def test_properties_default_to_empty_list(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.create_experiment(protocol_id=1, owner_isid="u", name="N")
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert sent_body["properties"] == []

    def test_returns_parsed_response(self):
        with patch("requests.Session.put", return_value=self._ok_response()):
            result = self.b.create_experiment(protocol_id=1, owner_isid="u", name="N")
        assert result["status"] == "ok"
        assert result["experimentID"] == 101


# ---------------------------------------------------------------------------
# update_experiment
# ---------------------------------------------------------------------------


class TestUpdateExperiment:
    def setup_method(self):
        self.b = make_browser()

    def _ok_response(self):
        m = MagicMock()
        m.status_code = 200
        m.text = '{"status": "ok", "message": "updated"}'
        return m

    def test_calls_correct_endpoint(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.update_experiment(experiment_id=42, name="New Name")
        url = mock_put.call_args[0][0]
        assert url.endswith("/browser/api/studies/experiment/42")

    def test_partial_update_only_sends_provided_fields(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.update_experiment(experiment_id=42, name="Only Name")
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert sent_body["name"] == "Only Name"
        assert set(sent_body.keys()) == {"name"}

    def test_full_update_sends_all_fields(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.update_experiment(
                experiment_id=42,
                name="N",
                description="D",
                book=2,
                automated="Y",
                project_id=999,
                properties=[{"propertyName": "k", "propertyValue": "v"}],
            )
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert sent_body["name"] == "N"
        assert sent_body["description"] == "D"
        assert sent_body["book"] == 2
        assert sent_body["automated"] == "Y"
        assert sent_body["projectId"] == 999
        assert len(sent_body["properties"]) == 1


# ---------------------------------------------------------------------------
# delete_experiment
# ---------------------------------------------------------------------------


class TestDeleteExperiment:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_delete_on_correct_url(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": ""}'
        with patch("requests.Session.delete", return_value=mock_response) as mock_del:
            self.b.delete_experiment(99)
        url = mock_del.call_args[0][0]
        assert url.endswith("/browser/api/studies/experiment/99")

    def test_returns_response(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "ok", "message": "deleted"}'
        with patch("requests.Session.delete", return_value=mock_response):
            result = self.b.delete_experiment(99)
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# complete_experiment
# ---------------------------------------------------------------------------


class TestCompleteExperiment:
    def setup_method(self):
        self.b = make_browser()

    def _ok_response(self):
        m = MagicMock()
        m.status_code = 200
        m.text = '{"status": "ok", "message": "completed"}'
        return m

    def test_calls_correct_endpoint(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.complete_experiment(experiment_id=7)
        url = mock_put.call_args[0][0]
        assert "completeExperiment/7" in url

    def test_payload_contains_countersigner_and_comment(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.complete_experiment(
                experiment_id=7, countersigner_isid="csigner", comment="Looks good"
            )
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert sent_body["countersignerIsid"] == "csigner"
        assert sent_body["comment"] == "Looks good"

    def test_defaults_to_empty_countersigner_and_comment(self):
        with patch(
            "requests.Session.put", return_value=self._ok_response()
        ) as mock_put:
            self.b.complete_experiment(experiment_id=7)
        sent_body = json.loads(mock_put.call_args[1]["data"])
        assert "countersignerIsid" not in sent_body
        assert "comment" not in sent_body


# ---------------------------------------------------------------------------
# list_protocols
# ---------------------------------------------------------------------------


class TestListProtocols:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.list_protocols()
        mock_get.assert_called_once_with("studies/protocol/allProtocols")

    def test_returns_list(self):
        protocols = [
            {
                "protocolID": 1,
                "name": "ChemELN",
                "description": "Chem ELN",
                "currentVersion": 1,
                "isAvailable": True,
                "protocolType": "SCREENING",
                "dilutionFactor": 0,
                "conc": 0,
                "concUnits": "nM",
                "plateFormatID": 0,
                "projectFormID": 0,
                "notebookTag": "CHM",
            }
        ]
        with patch.object(self.b, "_get", return_value=protocols):
            result = self.b.list_protocols()
        assert isinstance(result, list)
        assert result[0]["protocolID"] == 1
        assert result[0]["name"] == "ChemELN"


# ---------------------------------------------------------------------------
# list_processing_scripts
# ---------------------------------------------------------------------------


class TestListProcessingScripts:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.list_processing_scripts(42)
        mock_get.assert_called_once_with("studies/protocol/42/processingScripts")

    def test_accepts_string_protocol_id(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.list_processing_scripts("proto-1")
        mock_get.assert_called_once_with("studies/protocol/proto-1/processingScripts")

    def test_returns_list(self):
        scripts = [{"scriptID": 1, "name": "QC"}]
        with patch.object(self.b, "_get", return_value=scripts):
            result = self.b.list_processing_scripts(1)
        assert result == scripts


# ---------------------------------------------------------------------------
# _post_json helper
# ---------------------------------------------------------------------------


class TestPostJson:
    def setup_method(self):
        self.b = make_browser()

    def _ok(self, payload=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = {} if payload is None else payload
        m.text = json.dumps({}) if payload is None else json.dumps(payload)
        return m

    def test_success_returns_parsed_json(self):
        with patch("requests.Session.post", return_value=self._ok({"status": "ok"})):
            result = self.b._post_json("register/sdf/42/desalt")
        assert result == {"status": "ok"}

    def test_sends_json_content_type(self):
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b._post_json("register/sdf/42/desalt")
        headers = mock_post.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_raises_on_non_200(self):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        with patch("requests.Session.post", return_value=mock_response):
            with pytest.raises(ValueError) as exc_info:
                self.b._post_json("register/sdf/42/desalt")
        assert exc_info.value.args[0]["status_code"] == 500


# ---------------------------------------------------------------------------
# upload_sdf
# ---------------------------------------------------------------------------


class TestUploadSdf:
    def setup_method(self):
        self.b = make_browser()

    def test_returns_file_id_integer_from_list(self, tmp_path):
        sdf_file = tmp_path / "test.sdf"
        sdf_file.write_text("fake sdf content")

        with patch.object(self.b, "_post_files", return_value=1201):
            file_id = self.b.upload_sdf(str(sdf_file))

        assert file_id == 1201
        assert isinstance(file_id, int)

    def test_calls_correct_endpoint(self, tmp_path):
        sdf_file = tmp_path / "mol.sdf"
        sdf_file.write_text("fake sdf content")

        with patch.object(self.b, "_post_files", return_value=999) as mock_pf:
            self.b.upload_sdf(str(sdf_file))

        called_endpoint = mock_pf.call_args[0][0]
        assert called_endpoint == "register/sdf/upload"

    def test_multipart_field_name_is_uploadFile(self, tmp_path):
        sdf_file = tmp_path / "mol.sdf"
        sdf_file.write_text("fake sdf content")

        with patch.object(self.b, "_post_files", return_value=42) as mock_pf:
            self.b.upload_sdf(str(sdf_file))

        files_arg = mock_pf.call_args[1]["files"]
        assert "uploadFile" in files_arg

    def test_uses_basename_as_filename(self, tmp_path):
        sdf_file = tmp_path / "mycompound.sdf"
        sdf_file.write_text("fake sdf content")

        with patch.object(self.b, "_post_files", return_value=7) as mock_pf:
            self.b.upload_sdf(str(sdf_file))

        files_arg = mock_pf.call_args[1]["files"]
        filename_in_tuple = files_arg["uploadFile"][0]
        assert filename_in_tuple == "mycompound.sdf"


# ---------------------------------------------------------------------------
# validate_sdf
# ---------------------------------------------------------------------------

VALIDATE_RESPONSE = [
    {
        "moleError": 0,
        "itemInFile": 1,
        "idMatches": 0,
        "idProjectMatches": 0,
        "superMatches": 0,
        "superProjectMatches": 0,
        "scaffoldOverlap": 0,
        "exclusiveScaffoldOverlap": 0,
        "idMatchesFatal": False,
        "superMatchesFatal": False,
        "numberOfCompoundsToBeRegistered": 1,
        "lsAlias": [],
        "advErrDetails": [],
        "uploadId": -1,
    }
]


class TestValidateSdf:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(self.b, "_get", return_value=VALIDATE_RESPONSE) as mock_get:
            self.b.validate_sdf(1201)
        mock_get.assert_called_once_with("register/sdf/1201/validate")

    def test_returns_list_response(self):
        with patch.object(self.b, "_get", return_value=VALIDATE_RESPONSE):
            result = self.b.validate_sdf(1201)
        assert result == VALIDATE_RESPONSE
        assert result[0]["moleError"] == 0
        assert result[0]["itemInFile"] == 1

    def test_returns_raw_if_not_single_element_list(self):
        # If the server ever returns a multi-element list, pass it through unchanged.
        multi = [{"a": 1}, {"b": 2}]
        with patch.object(self.b, "_get", return_value=multi):
            result = self.b.validate_sdf(5)
        assert result == multi


# ---------------------------------------------------------------------------
# desalt_sdf
# ---------------------------------------------------------------------------

DESALT_RESPONSE = [
    {"new_molecules": 1, "merge_salts": False, "in_registry": 0, "items": []}
]


class TestDesaltSdf:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(
            self.b, "_post_json", return_value=DESALT_RESPONSE
        ) as mock_pj:
            self.b.desalt_sdf(1201)
        mock_pj.assert_called_once_with("register/sdf/1201/desalt", data=None)

    def test_returns_list_response(self):
        with patch.object(self.b, "_post_json", return_value=DESALT_RESPONSE):
            result = self.b.desalt_sdf(1201)
        assert result == DESALT_RESPONSE
        assert result[0]["new_molecules"] == 1
        assert result[0]["merge_salts"] is False

    def test_returns_raw_if_not_single_element_list(self):
        multi = [{"a": 1}, {"b": 2}]
        with patch.object(self.b, "_post_json", return_value=multi):
            result = self.b.desalt_sdf(5)
        assert result == multi


# ---------------------------------------------------------------------------
# register_sdf_salts
# ---------------------------------------------------------------------------

REGISTER_RESPONSE = [{"status": "success", "message": "salts have been registered"}]


class TestRegisterSdfSalts:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(
            self.b, "_post_json", return_value=REGISTER_RESPONSE
        ) as mock_pj:
            self.b.register_sdf_salts(1201)
        mock_pj.assert_called_once_with("register/sdf/1201/register_salts", data=None)

    def test_returns_list_response(self):
        with patch.object(self.b, "_post_json", return_value=REGISTER_RESPONSE):
            result = self.b.register_sdf_salts(1201)
        assert result == REGISTER_RESPONSE
        assert result[0]["status"] == "success"
        assert result[0]["message"] == "salts have been registered"

    def test_returns_raw_if_not_single_element_list(self):
        multi = [{"a": 1}, {"b": 2}]
        with patch.object(self.b, "_post_json", return_value=multi):
            result = self.b.register_sdf_salts(5)
        assert result == multi


# ---------------------------------------------------------------------------
# register_sdf_structures
# ---------------------------------------------------------------------------

MAP_FILE = "test_map.txt"
REGISTER_STRUCTURES_RESPONSE = [
    {"status": "success", "message": "structures have been registered"}
]


class TestRegisterSdfStructures:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint_with_map_file(self, input_dir):
        with patch.object(
            self.b, "_post_files", return_value=REGISTER_STRUCTURES_RESPONSE
        ) as mock_pj:
            self.b.register_sdf_structures(1201, input_dir + "/" + MAP_FILE)
        called_endpoint = mock_pj.call_args[0][0]
        assert called_endpoint == "register/sdf/1201/register_structures"
        called_files = mock_pj.call_args[1]["files"]
        assert "params" in called_files
        assert called_files["params"][0] == "test_map.txt"

    def test_returns_list_response(self, input_dir):
        with patch.object(
            self.b, "_post_files", return_value=REGISTER_STRUCTURES_RESPONSE
        ):
            result = self.b.register_sdf_structures(1201, input_dir + "/" + MAP_FILE)
        assert result == REGISTER_STRUCTURES_RESPONSE
        assert result[0]["status"] == "success"
        assert result[0]["message"] == "structures have been registered"

    def test_accepts_file_path(self, tmp_path, input_dir):
        params_file = tmp_path / "params.json"
        params_file.write_text(json.dumps(input_dir + "/" + MAP_FILE))

        with patch.object(
            self.b, "_post_files", return_value=REGISTER_STRUCTURES_RESPONSE
        ) as mock_pj:
            self.b.register_sdf_structures(1201, str(params_file))

        sent_files = mock_pj.call_args[1]["files"]
        assert sent_files["params"][0] == "params.json"
        # Checking a file was sent
        assert sent_files["params"][1].closed

    def test_returns_raw_if_not_single_element_list(self):
        multi = [{"a": 1}, {"b": 2}]
        with patch.object(self.b, "_post_files", return_value=multi):
            result = self.b.register_sdf_structures(5, [])
        assert result == multi


# ---------------------------------------------------------------------------
# register_sdf  (full pipeline)
# ---------------------------------------------------------------------------

REGISTER_FULL_RESPONSE = {
    "structures": '{"status":"success","message":"structures have been registered"}',
    "desalt": {"new_molecules": 1, "merge_salts": False, "in_registry": 0, "items": []},
    "salts": '{"status":"success","message":"salts have been registered"}',
}


class TestRegisterSdf:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(
            self.b, "_post_files", return_value=REGISTER_FULL_RESPONSE
        ) as mock_pj:
            self.b.register_sdf(1201)
        mock_pj.assert_called_once_with("register/sdf/1201/register")

    def test_unwraps_single_element_list(self):
        with patch.object(self.b, "_post_files", return_value=REGISTER_FULL_RESPONSE):
            result = self.b.register_sdf(1201)
        assert isinstance(result, dict)
        assert "structures" in result
        assert "desalt" in result
        assert "salts" in result

    def test_desalt_field_is_dict(self):
        with patch.object(self.b, "_post_files", return_value=REGISTER_FULL_RESPONSE):
            result = self.b.register_sdf(1201)
        assert result["desalt"]["new_molecules"] == 1

    def test_returns_raw_if_not_single_element_list(self):
        multi = [{"a": 1}, {"b": 2}]
        with patch.object(self.b, "_post_files", return_value=multi):
            result = self.b.register_sdf(5)
        assert result == multi


# ---------------------------------------------------------------------------
# get_sdf_report
# ---------------------------------------------------------------------------

SDF_REPORT = {
    "valid": 1,
    "salts_registered": 0,
    "structures_registered": 1,
    "desalted": 1,
}


class TestGetSdfReport:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(self.b, "_get", return_value=SDF_REPORT) as mock_get:
            self.b.get_sdf_report(1201)
        mock_get.assert_called_once_with("register/sdf/1201/report")

    def test_returns_report_dict(self):
        with patch.object(self.b, "_get", return_value=SDF_REPORT):
            result = self.b.get_sdf_report(1201)
        assert result["valid"] == 1
        assert result["structures_registered"] == 1
        assert result["desalted"] == 1


class TestDeleteBodyAndEmptyResponse:
    def setup_method(self):
        self.b = make_browser()

    def _ok_empty(self):
        m = MagicMock()
        m.status_code = 200
        m.text = ""
        return m

    def _ok_json(self, payload):
        m = MagicMock()
        m.status_code = 200
        m.text = json.dumps(payload)
        return m

    def _err(self, status=400, body='{"status":"error","message":"bad"}'):
        m = MagicMock()
        m.status_code = status
        m.text = body
        return m

    def test_empty_200_returns_empty_dict(self):
        with patch("requests.Session.delete", return_value=self._ok_empty()):
            result = self.b._delete("some/endpoint")
        assert result == {}

    def test_json_body_is_serialised_and_sent(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_json({"status": "ok"})
        ) as mock_del:
            self.b._delete("some/endpoint", data=["DOC1", "DOC2"])
        call_data = mock_del.call_args[1]["data"]
        assert json.loads(call_data) == ["DOC1", "DOC2"]

    def test_json_body_sets_content_type_header(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_json({"status": "ok"})
        ) as mock_del:
            self.b._delete("some/endpoint", data=["DOC1"])
        headers = mock_del.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_no_body_does_not_set_content_type(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_json({"status": "ok"})
        ) as mock_del:
            self.b._delete("some/endpoint")
        headers = mock_del.call_args[1]["headers"]
        assert "Content-Type" not in headers

    def test_no_body_sends_none_data(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_json({"status": "ok"})
        ) as mock_del:
            self.b._delete("some/endpoint")
        assert mock_del.call_args[1]["data"] is None

    def test_non_200_with_non_json_body_raises_value_error(self):
        with (
            patch(
                "requests.Session.delete",
                return_value=self._err(500, "plain error text"),
            ),
            pytest.raises(ValueError),
        ):
            self.b._delete("some/endpoint")


# ---------------------------------------------------------------------------
# get_experiment_files
# ---------------------------------------------------------------------------

EXPERIMENT_FILES_RESPONSE = [
    {
        "documentId": "DOC001",
        "fileName": "assay_data.xlsx",
        "fileSize": 4096,
        "uploadDate": "2026-01-15",
    },
    {
        "documentId": "DOC002",
        "fileName": "notes.pdf",
        "fileSize": 1024,
        "uploadDate": "2026-01-16",
    },
]


class TestGetExperimentFiles:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(
            self.b, "_get", return_value=EXPERIMENT_FILES_RESPONSE
        ) as mock_get:
            self.b.get_experiment_files(42)
        mock_get.assert_called_once_with("studies/elnAdhoc/getFiles/42")

    def test_returns_list_of_document_dicts(self):
        with patch.object(self.b, "_get", return_value=EXPERIMENT_FILES_RESPONSE):
            result = self.b.get_experiment_files(42)
        assert isinstance(result, list)
        assert result[0]["documentId"] == "DOC001"
        assert result[1]["fileName"] == "notes.pdf"

    def test_returns_empty_list_when_no_files(self):
        with patch.object(self.b, "_get", return_value=[]):
            result = self.b.get_experiment_files(99)
        assert result == []


# ---------------------------------------------------------------------------
# check_files
# ---------------------------------------------------------------------------


class TestCheckFiles:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(self.b, "_put", return_value=[]) as mock_put:
            self.b.check_files(42, ["assay_data.xlsx"])
        mock_put.assert_called_once_with(
            "studies/elnAdhoc/checkFiles",
            None,
            data=json.dumps({"experimentId": 42, "fileNames": ["assay_data.xlsx"]}),
            content_type="application/json",
        )

    def test_payload_contains_experiment_id_and_file_names(self):
        with patch.object(self.b, "_put", return_value=[]) as mock_put:
            self.b.check_files(7, ["a.xlsx", "b.pdf"])
        payload = json.loads(mock_put.call_args[1]["data"])
        assert payload["experimentId"] == 7
        assert payload["fileNames"] == ["a.xlsx", "b.pdf"]

    def test_returns_document_list(self):
        with patch.object(self.b, "_put", return_value=EXPERIMENT_FILES_RESPONSE):
            result = self.b.check_files(42, ["assay_data.xlsx"])
        assert isinstance(result, list)
        assert result[0]["documentId"] == "DOC001"

    def test_empty_file_names_list_is_valid(self):
        with patch.object(self.b, "_put", return_value=[]):
            result = self.b.check_files(42, [])
        assert result == []


# ---------------------------------------------------------------------------
# upload_files
# ---------------------------------------------------------------------------


class TestUploadFilesToServer:
    def setup_method(self):
        self.b = make_browser()

    def _ok(self, payload=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = (
            payload
            if payload is not None
            else {"Uploaded files": ["tempfiles/mol.sdf"]}
        )
        m.text = (
            json.dumps(payload)
            if payload is not None
            else json.dumps({"Uploaded files": ["tempfiles/mol.sdf"]})
        )
        return m

    def test_single_path_accepted_as_string(self, tmp_path):
        f = tmp_path / "mol.sdf"
        f.write_text("$$$$")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            result = self.b.upload_files(str(f))
        assert result == {"Uploaded files": ["tempfiles/mol.sdf"]}
        call_files = mock_post.call_args[1]["files"]
        field_names = [t[0] for t in call_files]
        assert "uploadfile" in field_names

    def test_multiple_paths_as_list(self, tmp_path):
        f1 = tmp_path / "mol1.sdf"
        f2 = tmp_path / "mol2.sdf"
        f1.write_text("$$$$")
        f2.write_text("$$$$")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.upload_files([str(f1), str(f2)])
        call_files = mock_post.call_args[1]["files"]
        field_names = [t[0] for t in call_files]
        assert field_names.count("uploadfile") == 2

    def test_calls_correct_endpoint(self, tmp_path):
        f = tmp_path / "mol.sdf"
        f.write_text("$$$$")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.upload_files(str(f))
        url = mock_post.call_args[0][0]
        assert "studies/elnAdhoc/uploadFilesToServer" in url

    def test_content_type_not_set_manually(self, tmp_path):
        """requests must set Content-Type with boundary for multipart."""
        f = tmp_path / "mol.sdf"
        f.write_text("$$$$")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.upload_files(str(f))
        headers = mock_post.call_args[1]["headers"]
        assert "Content-Type" not in headers

    def test_uses_basename_as_filename(self, tmp_path):
        f = tmp_path / "my_compounds.sdf"
        f.write_text("$$$$")
        with patch("requests.Session.post", return_value=self._ok()) as mock_post:
            self.b.upload_files(str(f))
        call_files = mock_post.call_args[1]["files"]
        upload_entry = next(t for t in call_files if t[0] == "uploadfile")
        assert upload_entry[1][0] == "my_compounds.sdf"


# ---------------------------------------------------------------------------
# add_files_to_experiment
# ---------------------------------------------------------------------------

FILE_UPLOAD_RESPONSES = [
    {"fileName": "assay_data.xlsx", "status": "success", "documentId": "DOC003"},
]


class TestAddFilesToExperiment:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint(self):
        with patch.object(
            self.b, "_put", return_value=FILE_UPLOAD_RESPONSES
        ) as mock_put:
            self.b.add_files_to_experiment(42, ["tempfiles/assay_data.xlsx"])
        mock_put.assert_called_once_with(
            "studies/elnAdhoc/addFiles",
            None,
            data=json.dumps(
                {
                    "experimentId": 42,
                    "newFiles": [{"path": "tempfiles/assay_data.xlsx"}],
                }
            ),
            content_type="application/json",
        )

    def test_payload_contains_experiment_id_and_new_files(self):
        with patch.object(self.b, "_put", return_value=[]) as mock_put:
            self.b.add_files_to_experiment(7, ["tempfiles/a.xlsx", "tempfiles/b.pdf"])
        payload = json.loads(mock_put.call_args[1]["data"])
        assert payload["experimentId"] == 7
        assert payload["newFiles"] == [
            {"path": "tempfiles/a.xlsx"},
            {"path": "tempfiles/b.pdf"},
        ]

    def test_returns_file_upload_responses(self):
        with patch.object(self.b, "_put", return_value=FILE_UPLOAD_RESPONSES):
            result = self.b.add_files_to_experiment(42, ["tempfiles/assay_data.xlsx"])
        assert isinstance(result, list)
        assert result[0]["documentId"] == "DOC003"
        assert result[0]["status"] == "success"


# ---------------------------------------------------------------------------
# delete_experiment_files
# ---------------------------------------------------------------------------


class TestDeleteExperimentFiles:
    def setup_method(self):
        self.b = make_browser()

    def _ok_empty(self):
        m = MagicMock()
        m.status_code = 200
        m.text = ""
        return m

    def test_calls_correct_endpoint(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_empty()
        ) as mock_del:
            self.b.delete_experiment_files(42, ["DOC001", "DOC002"])
        url = mock_del.call_args[0][0]
        assert "studies/elnAdhoc/deleteFiles/42" in url

    def test_document_ids_sent_as_json_body(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_empty()
        ) as mock_del:
            self.b.delete_experiment_files(42, ["DOC001", "DOC002"])
        data = mock_del.call_args[1]["data"]
        assert json.loads(data) == ["DOC001", "DOC002"]

    def test_content_type_is_json(self):
        with patch(
            "requests.Session.delete", return_value=self._ok_empty()
        ) as mock_del:
            self.b.delete_experiment_files(42, ["DOC001"])
        headers = mock_del.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_returns_empty_dict_on_success(self):
        with patch("requests.Session.delete", return_value=self._ok_empty()):
            result = self.b.delete_experiment_files(42, ["DOC001"])
        assert result == {}

    def test_raises_on_error_status(self):
        m = MagicMock()
        m.status_code = 400
        m.text = '{"status":"error","message":"document not found"}'
        with patch("requests.Session.delete", return_value=m):
            with pytest.raises(ValueError):
                self.b.delete_experiment_files(42, ["INVALID"])


# ---------------------------------------------------------------------------
# _get helper (direct tests)
# ---------------------------------------------------------------------------


class TestGetDispatcher:
    def setup_method(self):
        self.b = make_browser()

    def _ok(self, payload=None):
        m = MagicMock()
        m.status_code = 200
        m.json.return_value = payload if payload is not None else {"ok": True}
        m.text = (
            json.dumps(payload) if payload is not None else json.dumps({"ok": True})
        )
        return m

    def test_sends_bearer_token_header(self):
        with patch("requests.Session.get", return_value=self._ok()) as mock_get:
            self.b._get("projects/")
        headers = mock_get.call_args[1]["headers"]
        assert headers["Authorization"].startswith("Bearer ")

    def test_returns_parsed_json_on_200(self):
        with patch("requests.Session.get", return_value=self._ok({"foo": "bar"})):
            result = self.b._get("projects/")
        assert result == {"foo": "bar"}

    def test_raises_on_non_200(self):
        m = MagicMock()
        m.status_code = 500
        m.text = "server error"
        with patch("requests.Session.get", return_value=m):
            with pytest.raises(ValueError) as exc_info:
                self.b._get("projects/")
        assert exc_info.value.args[0]["status_code"] == 500

    def test_raw_mode_returns_response_object(self):
        resp = self._ok()
        with patch("requests.Session.get", return_value=resp):
            result = self.b._get("projects/", raw=True)
        assert result is resp

    def test_query_params_are_url_encoded(self):
        with patch("requests.Session.get", return_value=self._ok()) as mock_get:
            self.b._get("some/endpoint", query_params={"a": "1", "b": "two"})
        url = mock_get.call_args[0][0]
        assert "a=1" in url
        assert "b=two" in url


# ---------------------------------------------------------------------------
# _put_json helper
# ---------------------------------------------------------------------------


class TestPutJson:
    def setup_method(self):
        self.b = make_browser()

    def _ok(self, payload='{"status": "ok"}'):
        m = MagicMock()
        m.status_code = 200
        m.text = payload
        return m

    def test_sets_json_content_type(self):
        with patch("requests.Session.put", return_value=self._ok()) as mock_put:
            self.b._put_json("studies/experiment", {}, {"a": 1})
        headers = mock_put.call_args[1]["headers"]
        assert headers["Content-Type"] == "application/json"

    def test_sends_body_as_json(self):
        with patch("requests.Session.put", return_value=self._ok()) as mock_put:
            self.b._put_json("studies/experiment", {}, {"key": "value"})
        data = mock_put.call_args[1]["data"]
        # Accept either raw dict or list-wrapped dict (existing implementations differ).
        body = json.loads(data)
        if isinstance(body, list):
            assert body[0]["key"] == "value"
        else:
            assert body["key"] == "value"


# ---------------------------------------------------------------------------
# _parallel_get
# ---------------------------------------------------------------------------


class TestParallelGet:
    def setup_method(self):
        self.b = make_browser()

    def test_returns_results_in_order(self):
        with patch.object(self.b, "_get", side_effect=lambda ep: ep):
            results = self.b._parallel_get(["projects/1", "projects/2", "projects/3"])
        assert results == ["projects/1", "projects/2", "projects/3"]

    def test_raises_not_implemented_with_query_params(self):
        with pytest.raises(NotImplementedError):
            self.b._parallel_get(["projects/1"], query_params={"a": "1"})


# ---------------------------------------------------------------------------
# _populate_projects / _populate_datasources
# ---------------------------------------------------------------------------


class TestPopulateProjects:
    def setup_method(self):
        self.b = make_browser()

    def test_populate_projects_indexes_by_name_and_id(self):
        project_ids_response = ["10", "6001"]
        project_descs = [
            {"projectID": 10, "projectName": "Assays", "dataSources": {}},
            {"projectID": "6001", "projectName": "Chemistry", "dataSources": {}},
        ]

        def fake_get(endpoint, *a, **kw):
            if endpoint == "projects/":
                return project_ids_response
            raise AssertionError(f"unexpected endpoint {endpoint}")

        with patch.object(self.b, "_get", side_effect=fake_get):
            with patch.object(self.b, "_parallel_get", return_value=project_descs):
                self.b._populate_projects()

        assert self.b.projects_by_id["10"]["projectName"] == "Assays"
        assert self.b.projects_by_id["6001"]["projectName"] == "Chemistry"
        assert self.b.projects_by_name["Assays"]["projectID"] == "10"
        # projectID was coerced to string for the previously-int project ID
        assert self.b.projects_by_id["6001"]["projectID"] == "6001"

    def test_populate_projects_short_circuits_if_already_loaded(self):
        self.b.projects_by_id = {"10": {"projectName": "X", "projectID": "10"}}
        self.b.projects_by_name = {"X": self.b.projects_by_id["10"]}
        with patch.object(self.b, "_get") as mock_get:
            self.b._populate_projects()
        mock_get.assert_not_called()

    def test_populate_projects_reloads_when_requested(self):
        self.b.projects_by_id = {"10": {"projectName": "Old", "projectID": "10"}}
        with (
            patch.object(self.b, "_get", return_value=["7000"]),
            patch.object(
                self.b,
                "_parallel_get",
                return_value=[
                    {"projectID": "7000", "projectName": "New", "dataSources": {}}
                ],
            ),
        ):
            self.b._populate_projects(reload=True)
        assert "7000" in self.b.projects_by_id


class TestPopulateDatasources:
    def setup_method(self):
        self.b = make_browser()

    def test_populate_datasources_builds_nested_indices(self):
        self.b.projects_by_id = {
            "10": {
                "projectID": "10",
                "projectName": "Assays",
                "dataSources": {
                    "101": {"dsID": 101, "name": "DEMO_PLATE_RESULTS_VW"},
                    "102": {"dsID": "102", "name": "DEMO_COMPOUND_VW"},
                },
            }
        }
        self.b.projects_by_name = {"Assays": self.b.projects_by_id["10"]}
        self.b._populate_datasources()
        assert self.b.datasources_by_id["10"]["101"]["name"] == "DEMO_PLATE_RESULTS_VW"
        assert self.b.datasources_by_name["Assays"]["DEMO_COMPOUND_VW"]["dsID"] == "102"
        # dsIDs are coerced to strings
        assert self.b.datasources_by_id["10"]["101"]["dsID"] == "101"

    def test_short_circuits_if_already_loaded(self):
        self.b.datasources_by_id = {"10": {}}
        self.b.datasources_by_name = {"Assays": {}}
        with patch.object(self.b, "_populate_projects") as mock_pop_projects:
            self.b._populate_datasources()
        mock_pop_projects.assert_not_called()


# ---------------------------------------------------------------------------
# list_schedules
# ---------------------------------------------------------------------------


class TestListSchedules:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_correct_endpoint_default_state(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.list_schedules()
        mock_get.assert_called_once_with("schedules", {"state": "enabled"})

    def test_calls_correct_endpoint_disabled(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.list_schedules(state="disabled")
        mock_get.assert_called_once_with("schedules", {"state": "disabled"})

    def test_returns_parsed_list(self):
        schedules = [{"id": 1, "name": "nightly", "state": "enabled"}]
        with patch.object(self.b, "_get", return_value=schedules):
            result = self.b.list_schedules()
        assert result == schedules


# ---------------------------------------------------------------------------
# change_owner_of_experiment
# ---------------------------------------------------------------------------


class TestChangeOwnerOfExperiment:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_put_on_correct_endpoint(self):
        with patch.object(self.b, "_put", return_value={"status": "ok"}) as mock_put:
            self.b.change_owner_of_experiment(experiment_id=42, isid="newowner")
        # _put is called with endpoint, query_params, data
        endpoint = mock_put.call_args[0][0]
        assert endpoint == "studies/experiment/alternateIsid/42/newowner"

    def test_returns_response(self):
        with patch.object(self.b, "_put", return_value={"status": "ok"}):
            result = self.b.change_owner_of_experiment(1, "u")
        assert result == {"status": "ok"}


# ---------------------------------------------------------------------------
# upload_files (actual public method on Browser)
# ---------------------------------------------------------------------------


class TestUploadFiles:
    def setup_method(self):
        self.b = make_browser()

    def test_single_path_accepted_as_string(self, tmp_path):
        f = tmp_path / "mol.sdf"
        f.write_text("$$$$")
        expected = {"Uploaded files": ["tempfiles/mol.sdf"]}
        with patch.object(self.b, "_post_files", return_value=expected) as mock_pf:
            result = self.b.upload_files(str(f))
        assert result == expected
        endpoint = mock_pf.call_args[0][0]
        assert endpoint == "studies/elnAdhoc/uploadFilesToServer"

    def test_multiple_paths_as_list(self, tmp_path):
        f1 = tmp_path / "mol1.sdf"
        f2 = tmp_path / "mol2.sdf"
        f1.write_text("$$$$")
        f2.write_text("$$$$")
        with patch.object(
            self.b, "_post_files", return_value={"Uploaded files": []}
        ) as mock_pf:
            self.b.upload_files([str(f1), str(f2)])
        files_arg = mock_pf.call_args[1]["files"]
        # each file is a ('uploadfile', (filename, fh)) tuple
        assert len(files_arg) == 2
        field_names = [t[0] for t in files_arg]
        assert field_names == ["uploadfile", "uploadfile"]

    def test_uses_basename_as_filename(self, tmp_path):
        nested = tmp_path / "subdir"
        nested.mkdir()
        f = nested / "results.csv"
        f.write_text("a,b,c\n1,2,3")
        with patch.object(
            self.b, "_post_files", return_value={"Uploaded files": []}
        ) as mock_pf:
            self.b.upload_files(str(f))
        files_arg = mock_pf.call_args[1]["files"]
        filename_in_tuple = files_arg[0][1][0]
        assert filename_in_tuple == "results.csv"


# ---------------------------------------------------------------------------
# parse_data_from_file / add_data_from_file_to_experiment
# ---------------------------------------------------------------------------


class TestParseDataFromFile:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_post_json_with_correct_endpoint_and_payload(self):
        with patch.object(
            self.b, "_post_json", return_value={"status": "parsed"}
        ) as mock_pj:
            self.b.parse_data_from_file(script_id=5, file_name="results.csv")
        mock_pj.assert_called_once_with(
            "studies/data/parse", data={"scriptID": 5, "fileName": "results.csv"}
        )


class TestAddDataFromFileToExperiment:
    def setup_method(self):
        self.b = make_browser()

    def test_calls_post_json_with_correct_endpoint_and_payload(self):
        with patch.object(
            self.b, "_post_json", return_value={"status": "uploaded"}
        ) as mock_pj:
            self.b.add_data_from_file_to_experiment(
                script_id=5,
                file_name="results.csv",
                experiment_id=42,
                doc_id="abc",
                skip_rows_with_warnings=False,
            )
        mock_pj.assert_called_once_with(
            "studies/data/upload",
            data={
                "scriptId": 5,
                "fileName": "results.csv",
                "experimentId": 42,
                "docId": "abc",
                "skipRowsWithWarnings": False,
            },
        )

    def test_defaults_doc_id_and_skip_rows(self):
        with patch.object(self.b, "_post_json", return_value={}) as mock_pj:
            self.b.add_data_from_file_to_experiment(
                script_id=0, file_name="f.xlsx", experiment_id=1
            )
        mock_pj.assert_called_once_with(
            "studies/data/upload",
            data={
                "scriptId": 0,
                "fileName": "f.xlsx",
                "experimentId": 1,
                "docId": "",
                "skipRowsWithWarnings": True,
            },
        )


# ---------------------------------------------------------------------------
# Notebook endpoints
# ---------------------------------------------------------------------------


class TestNotebooks:
    def setup_method(self):
        self.b = make_browser()

    def test_get_notebook_by_name(self):
        with patch.object(self.b, "_get", return_value={"id": 1}) as mock_get:
            self.b.get_notebook_by_name("CHM")
        mock_get.assert_called_once_with("studies/notebooks/CHM")

    def test_get_notebook_by_id(self):
        with patch.object(self.b, "_get", return_value={"id": 1}) as mock_get:
            self.b.get_notebook_by_id(42)
        mock_get.assert_called_once_with("studies/notebooks/42")

    def test_get_notebooks_by_name_passes_list_as_query_param(self):
        with patch.object(self.b, "_get", return_value=[]) as mock_get:
            self.b.get_notebooks_by_name(["CHM", "BIO"])
        mock_get.assert_called_once_with(
            "studies/notebooks", query_params={"bookNames": ["CHM", "BIO"]}
        )


# ---------------------------------------------------------------------------
# Connect-retry configuration
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_default_retry_policy(self):
        b = make_browser()
        retry = b._session.get_adapter("https://demo.example.org").max_retries
        assert retry.connect == 5
        assert retry.read == 2
        assert retry.total is None
        assert set(retry.allowed_methods) == {"GET"}
        idem = b._idempotent_session.get_adapter("https://demo.example.org").max_retries
        assert idem.connect == 5
        assert idem.read == 2
        assert set(idem.allowed_methods) == {"GET", "POST"}

    def test_post_routes_by_idempotent_flag(self):
        b = make_browser()
        ok = MagicMock(status_code=200, text='{"status": "ok"}')
        with patch.object(b._idempotent_session, "post", return_value=ok) as idem_post:
            with patch.object(b._session, "post", return_value=ok) as plain_post:
                b._post("some/endpoint", {}, data={"data": "[1, 2]"}, idempotent=True)
                assert idem_post.called and not plain_post.called
                idem_post.reset_mock()
                b._post("some/endpoint", {}, data={"data": "[1, 2]"})
                assert plain_post.called and not idem_post.called

    def test_retries_configurable(self):
        with patch.object(Browser, "_authenticate", return_value={}):
            b = Browser(
                user="u",
                password="p",
                dotmatics_instance="https://demo.example.org",
                lazy=True,
                connect_retries=2,
                read_retries=0,
            )
        retry = b._session.get_adapter("https://demo.example.org").max_retries
        assert retry.connect == 2
        assert retry.read == 0
