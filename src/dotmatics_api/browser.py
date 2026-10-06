import json
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor

from .base import AuthenticationError, DotmaticsClient

__all__ = ["AuthenticationError", "Browser"]


class Browser(DotmaticsClient):
    """Class encapsulating interactions with the Dotmatics Browser REST API.

    At present, this implements the following APIs:
        - /authenticate (used internally)
        - /projects (used internally)
        - /datasources (used internally)
        - /data (read-only)
        - /query (read-only)
        - /studies/experiment (create, update, delete, complete)
        - /studies/elnAdhoc (list, check, upload, attach, and delete experiment files)
        - /studies/notebooks (list notebooks)
        - /studies/protocol (list protocols, processingScripts)
        - /register/sdf (upload, validate, desalt, register salts/structures, full register, report)

    To use this, first create a Browser object with appropriate authentication
    information. Authentication can be done with a username/password pair or
    a token previously obtained from /authenticate.

        >>> b = Browser(user=DOTMATICS_USER, password=DOTMATICS_PASSWORD,
        ...             dotmatics_instance="https://demo.example.org")

    To query available projects or datasources, examine the `projects_by_name`,
    `projects_by_id`, `datasources_by_id`, or `datasources_by_name` properties.
    Note that if `lazy` was set to true in Browser object initialization, these
    properties will not be automatically initialized on creation. Project and datasource
    objects are purely parsed from the JSON returned by the API. No further structure
    is built internally at present.

    Note that all keys used in dictionaries or ID lookups in this module are strings.

    >>> b.projects_by_id['10']['projectName']
        'Assays'
    >>> b.projects_by_name['Assays']['projectID']
        '10'
    >>> b.datasources_by_id['10']['101']['name']
        'DEMO_PLATE_RESULTS_VW'
    >>> b.datasources_by_name['Assays']['DEMO_PLATE_RESULTS_VW']['dsID']
        '101'
    >>> b.datasources_by_id['10']['101'] == b.projects_by_id['10']['dataSources']['101']
        True


    fetch_data() enables fetching all columns from all or selected IDs from a single datasource.
    Support for choosing only a subset of columns is currently not implemented.
    """

    _API_PREFIX = "/browser/api"
    _AUTH_ENDPOINT = "authenticate/requestToken"

    def __init__(
        self,
        user=None,
        password=None,
        token=None,
        *,
        dotmatics_instance: str,
        socks5_proxy=None,
        max_threads=4,
        lazy=False,
        connection_timeout=10,
        read_timeout=100,
        connect_retries=5,
        read_retries=2,
    ):
        """Object lightly encapsulating the Dotmatics Browser API

        Authentication: pass either a user/password pair for a user
        having API access to the Dotmatics server, or a user/token pair
        with a token previously obtained from the /authenticate API endpoint.
            user: string, username for Dotmatics
            password: string, password corresponding to `user`
            token: JSON-decoded response from 'authenticate/requestToken' for a valid user

        Network:
            dotmatics_instance: URL to the dotmatics instance to connect to
            socks5_proxy: if not None, use this SOCKS5 proxy to proxy all connections to
                          the Dotmatics instance.
                          Example: `socks5://localhost:1080`
            max_threads: maximum number of GET requests to issue in parallel
            connect_retries: retries for connection-phase failures (DNS, refused
                          or timed-out connect, SOCKS negotiation) with exponential
                          backoff; see DotmaticsClient for details
            read_retries: retries for GETs and read-only POSTs flagged idempotent
                          whose connection died after sending; see DotmaticsClient
                          for details

        Misc:
            lazy: if True, only load information about available projects and
                           datasources in Dotmatics on first request that requires it.
                  if False, load project/datasource information at object creation time
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
        self.api_path = "/browser/api"
        self.api_url = self._build_url("/browser/api")

        self.threadpool = ThreadPoolExecutor(max_workers=max_threads)

        self.projects_by_name = None
        self.projects_by_id = None
        self.datasources_by_name = None
        self.datasources_by_id = None

        if not lazy:
            try:
                self._populate_projects()
                self._populate_datasources()
            except Exception:
                self.close()
                raise

    def close(self):
        if hasattr(self, "threadpool"):
            self.threadpool.shutdown(wait=True)
        super().close()

    def _parse_auth_response(self, response):
        """Extract the token from a successful /authenticate/requestToken reply.

        The base class issues the request and raises AuthenticationError on a
        non-200; here we parse the 200 body (the JSON-decoded token) through the
        shared response parser.
        """
        return self._parse_response(response, self._AUTH_ENDPOINT, response.url)

    def _get(self, endpoint: str, query_params: dict | None = None, raw: bool = False):
        """Makes request to Dotmatic API and returns parsed result.

        endpoint: string. Only the method desired; DO NOT include the full
              server and Browser path here.
        query_params: dict or None. if dict, key,value pairs to include in the query.
        raw: bool. If true, return the requests.Response object instead of the parse
             of the JSON reply. Primarily for debug usage.
        """
        # Headers for the GET request
        headers = self._bearer_headers()
        url = self._make_request_path(endpoint, query_params)
        response = self._session.get(
            url,
            headers=headers,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )

        return self._parse_response(response, endpoint, url, raw=raw)

    def _bearer_headers_with_content_type(self, content_type: str | None) -> dict:
        headers = self._bearer_headers()
        # For multipart/form-data, do NOT set Content-Type manually — requests must
        # generate it (with the multipart boundary).  For all other types, set it
        # explicitly when provided.
        if content_type and content_type != "multipart/form-data":
            headers["Content-Type"] = content_type
        return headers

    def _post(
        self,
        endpoint: str,
        query_params: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        params: list | None = None,
        content_type: str | None = None,
        idempotent: bool = False,
    ):
        """Core POST dispatcher. Callers are responsible for preparing data/files.

        endpoint:     string. API method path; DO NOT include server or /browser/api prefix.
        query_params: dict. Query-string parameters (may be empty).
        data:         Pre-prepared body. A JSON string for application/json requests,
                      or a dict of form fields for form-encoded requests.
        files:        dict or None. Multipart file parts for multipart/form-data requests.
        content_type: str or None.
                      - Pass 'application/json' (or any non-multipart type) to have
                        Content-Type set explicitly in the request header.
                      - Pass 'multipart/form-data' (or None when files are present)
                        to let requests set the header automatically with the correct
                        multipart boundary.
                      - Pass None to omit the Content-Type header entirely (e.g. for
                        form-encoded payloads where requests sets it automatically).
        idempotent:   bool. Set True ONLY for POSTs that are read-only queries
                      (e.g. fetching/searching by an ID list): they get read
                      retries, meaning the full request is re-sent on a fresh
                      connection if the response is lost. Leave False for any
                      POST with server-side effects — re-sending those could
                      execute the mutation twice.
        """
        headers = self._bearer_headers_with_content_type(content_type)
        url = self._make_request_path(endpoint, query_params)
        session = self._idempotent_session if idempotent else self._session
        response = session.post(
            url,
            headers=headers,
            data=data,
            files=files if files else None,
            params=params if params else None,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )

        return self._parse_response(response, endpoint, url)

    def _post_json(
        self,
        endpoint: str,
        query_params: dict | None = None,
        data: dict | None = None,
    ) -> object:
        """Makes a POST request with an application/json body to the Dotmatics API.

        Prepares the request body, then delegates the HTTP call to _post().

        endpoint: string. The API method desired.
        data:     dict, list, or None.
        """
        return self._post(
            endpoint,
            query_params or {},
            data=json.dumps(data) if data is not None else None,
            content_type="application/json",
        )

    def _post_files(
        self,
        endpoint: str,
        query_params: dict | None = None,
        files: dict | None = None,
    ):
        """Makes a multipart POST request to the Dotmatics API.

        The session token is included as a multipart form part alongside the
        file data, matching the content type of the other file parts.

        endpoint:     string. The API method desired.
        files:        dict. A dictionary of {'field_name': file_object} or
                      {'field_name': (filename, file_object)} to be uploaded.
        query_params: dict or None. Optional query parameters.
        """
        return self._post(
            endpoint,
            query_params or {},
            files=files,
            content_type="multipart/form-data",
        )

    def _put(
        self,
        endpoint: str,
        query_params: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
        content_type: str | None = None,
    ) -> dict:
        """Core PUT dispatcher. Callers are responsible for preparing data/files.

        endpoint:     string. Only the method and params desired; DO NOT include the
                      full server and Browser path here.
        data:         Pre-prepared body. A JSON string for application/json requests,
                      or a dict of form fields for form-encoded requests.
        files:        dict or None. Multipart file parts for multipart/form-data requests.
        content_type: str or None. Same semantics as _post(): set explicitly for
                      non-multipart types, omitted for multipart/form-data or None.
        """
        headers = self._bearer_headers_with_content_type(content_type)
        url = self._make_request_path(endpoint, query_params)
        response = self._session.put(
            url,
            headers=headers,
            data=data,
            files=files,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        return self._parse_response(response, endpoint, url)

    def _put_json(
        self,
        endpoint: str,
        query_params: dict | None = None,
        data: dict | None = None,
    ) -> dict:
        """Makes a PUT request with a plain application/json body (no token wrapping).
        endpoint:     string. Only the method and params desired.
        query_params: dict.   URL query parameters.
        data:         dict.   Payload to JSON-serialize and send as the body.
        """
        return self._put(
            endpoint,
            query_params,
            data=json.dumps(data) if data is not None else None,
            content_type="application/json",
        )

    def _parse_response(
        self, response, endpoint: str, url: str, raw: bool = False
    ) -> dict:
        """Validate an HTTP response and return the parsed JSON body.

        Raises ValueError on a non-200 status or an API-level error payload.
        Returns an empty dict when the response body is empty (some endpoints
        return no body on success).
        """
        if raw:
            return response

        if response.status_code != 200:
            try:
                rsp = json.loads(response.text)
            except (ValueError, json.JSONDecodeError):
                rsp = {}
            raise ValueError(
                {
                    "status_code": response.status_code,
                    "status": rsp.get("status") if isinstance(rsp, dict) else None,
                    "message": rsp.get("message")
                    if isinstance(rsp, dict)
                    else response.text,
                    "endpoint": endpoint,
                    "url": url,
                }
            )
        if not response.text.strip():
            return {}
        rsp = json.loads(response.text)
        if isinstance(rsp, dict) and rsp.get("status") == "error":
            raise ValueError(
                {
                    "status_code": response.status_code,
                    "status": rsp["status"],
                    "message": rsp.get("message"),
                    "endpoint": endpoint,
                    "url": url,
                }
            )
        return rsp

    def _delete(self, endpoint: str, data=None) -> dict:
        """Makes DELETE request to Dotmatics API and returns parsed result.

        endpoint: string. Only the method and params desired; DO NOT include the full
                  server and Browser path here.
        data:     list, dict, or None. If provided, JSON-serialised and sent as the
                  request body with Content-Type: application/json.
        """
        headers = self._bearer_headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        url = self._make_request_path(endpoint)
        response = self._session.delete(
            url,
            headers=headers,
            data=json.dumps(data) if data is not None else None,
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        return self._parse_response(response, endpoint, url)

    def _parallel_get(self, endpoints: Iterable[str], query_params: dict | None = None):
        """Use threadpool to parallelize multiple GET requests"""
        if query_params is not None:
            raise NotImplementedError("Implement parallel GET with query params")
        return list(self.threadpool.map(self._get, endpoints))

    def _populate_projects(self, reload=False):
        """Populate internal index of projects available in Dotmatics."""
        if self.projects_by_id is not None and not reload:
            """Exit fast if this has already been loaded"""
            return

        # Stringify project IDs as the API uses int and string inconsistently.
        project_ids = list(map(str, self._get("projects/")))
        project_descs = self._parallel_get([f"projects/{p}" for p in project_ids])
        projects_by_id = dict(zip(project_ids, project_descs))
        projects_by_name = {desc["projectName"]: desc for desc in project_descs}

        for pid, proj in projects_by_id.items():
            proj["projectID"] = str(proj["projectID"])

        self.projects_by_name = projects_by_name
        self.projects_by_id = projects_by_id

    def _populate_datasources(self, reload=False):
        """Populate internal index of datasources available in Dotmatics"""
        if self.datasources_by_id is not None and not reload:
            """Exit fast if this has already been loaded"""
            return

        self._populate_projects(reload=reload)

        datasources_by_id = {}
        datasources_by_name = {}

        for pid, proj in self.projects_by_id.items():
            pname = proj["projectName"]
            datasources_by_id[pid] = {}
            datasources_by_name[pname] = {}
            for dsid, dsinfo in proj["dataSources"].items():
                dsname = dsinfo["name"]
                # Stringify datasource IDs as the API uses int and string inconsistently.
                dsid = str(dsid)
                dsinfo["dsID"] = str(dsinfo["dsID"])
                datasources_by_id[pid][dsid] = dsinfo
                datasources_by_name[pname][dsname] = dsinfo

        self.datasources_by_id = datasources_by_id
        self.datasources_by_name = datasources_by_name

    def _normalize_project_ds_ids(
        self,
        project=None,
        pid=None,
        datasources: Iterable[str] = None,
        dsids: Iterable[str] = None,
    ):
        """Converts project name OR id and DS name OR id into full four-tuple.

        Returns (project name, project ID, [list of datasources name], [list of datasources IDs])
        """

        if pid is None or dsids is None:
            # If the user specifies IDs, we don't need the internal indices to translate
            # names to IDs
            self._populate_datasources()

        if (pid is None and project is None) or (
            pid is not None and project is not None
        ):
            raise ValueError("Must specify exactly one of project name or ID")
        if (dsids is None and datasources is None) or (
            dsids is not None and datasources is not None
        ):
            raise ValueError("Must specify exactly one list of datasource names or IDs")

        if pid is None:
            pid = str(self.projects_by_name[project]["projectID"])
        pid = str(pid)
        project_name = self.projects_by_id[pid]["projectName"]

        if dsids is None:
            dsids = [
                str(self.datasources_by_name[project_name][datasource]["dsID"])
                for datasource in datasources
            ]
        else:
            dsids = [str(dsid) for dsid in dsids]
        dsnames = [self.datasources_by_id[pid][dsid]["name"] for dsid in dsids]

        return (project_name, pid, dsnames, dsids)

    def fetch_data(
        self,
        project: str | None = None,
        pid: str | None = None,
        datasources: Iterable[str] = None,
        dsids: Iterable[str] = None,
        ids: Iterable[str] | None = None,
        limit: int = -1,
        offset: int = -1,
        alias_column_names: bool = False,
    ):
        """Gets all columns from a list of datasources, for a selected set of IDs

        project: string, name of Dotmatics project containing datasources to query
        pid: string or integer, ID of Dotmatics project containing datasources to query
        datasources: List[string], names of datasources to query
        dsids: List[string or integer], IDs of datasources to query

        ids: None or iterable.
            if None, retrieve all IDs from selected datasources, given limit/offset
            if iterable, retrieve only the IDs specified in the iterable

        limit: integer. Maximum number of IDs to return. Default is -1 which means query parameter will not be included in the request.
        offset: integer. Starting offset of IDs to return, from whatever order the
                         API provides. Default is -1 which means query parameter will not be included in the request. Negative offsets are omitted; server behavior for them is unverified.


        Exactly one of project or pid must be specified.
        Exactly one of dsnames or dsids must be specified.

        Limit and offset provide pagination of results. I believe, though it's not
        clear if it's guaranteed, that order is preserved by the API across queries, so
        that results can be fetched in pages:
            limit=stepsize, offset=0
            limit=stepsize, offset=stepsize
            limit=stepsize, offset=2*stepsize
            ...

        NOTE: Dotmatics has internal limitations on the maximum number of rows and maximum
              size of result that can be returned from a single API call. The row limit
              is NOT the same as the limit here, as a single "row" in the units specified
              by `limit` can expand to many more rows in the returned response. Similarly,
              the limit induced by the maximum byte size of returned responses is very
              difficult to predict. If these internal limits are exceeded, no error code
              is provided from the API; you will simply get silently truncated data.

              If querying tables or views that can provide large amounts of data per
              primary/join key, be very careful with large `limit` values to avoid
              silently truncated data. See docs/api-behavior.md for observed truncation and its limits.

        alias_column_names: bool. if False, return results keyed by internal column names.
                                  if True, return results from column name aliases
                                  specified in Dotmatics datasources setup.

        """

        project_name, pid, dsnames, dsids = self._normalize_project_ds_ids(
            project, pid, datasources, dsids
        )

        if ids is None:
            ids = ["*"]
        query_params = {"aliased": 1 if alias_column_names else 0}
        if limit >= 0:
            query_params["limit"] = limit
        if offset >= 0:
            query_params["offset"] = offset

        if isinstance(ids, str):
            raise TypeError(
                "ids should be a non-string iterable containing >=1 ID, not a string"
            )
        elif len(ids) > 1:
            # POST
            # The special '*' ID can only be passed as a GET param for /data
            if "*" in ids:
                raise ValueError("The special '*' ID cannot be combined with other IDs")
            endpoint = f"data/{self.user}/{pid}/{','.join(dsids)}/"
            return self._post(
                endpoint,
                query_params,
                data={"data": json.dumps(list(ids))},
                idempotent=True,
            )
        else:
            # GET
            endpoint = f"data/{self.user}/{pid}/{','.join(dsids)}/{list(ids)[0]}"
            return self._get(endpoint, query_params)

    def run_query(
        self,
        column: str,
        operator: str,
        value: str,
        project: str | None = None,
        pid: str | None = None,
        datasources: Iterable[str] = None,
        dsids: Iterable[str] = None,
        limit: int = -1,
        offset: int = 0,
        alias_column_names: bool = False,
    ):
        """
        This endpoint can be used to get the primary ids or count of primary ids that match the
        condition set by column, operator, & value which essentially make up the where clause of an sql statement.

        column: str. The column of the table you want to query against.
        operator: str. Possible values:
            equals
            lessthan
            lessthanequals
            greaterthan
            greaterthanequals
            about10
            about20
            between
            like
            startslike
            endslike
            not
            days
        value: str. The value to compare the column to using the operator
        limit: integer. Maximum number of IDs to return. Default is -1 which means query parameter will not be included in the request.
        offset: integer. Starting offset of IDs to return, from whatever order the
                         API provides. Default is -1 which means query parameter will not be included in the request. Negative offsets are omitted; server behavior for them is unverified.
        Rest of the parameters are the same as fetch_data fn.

        Return: dict with fields 'sql' - sql statement used to get list of ids, 'ids' - list of primary ids returned by sql, 'count' - length of 'ids' or what ids would have been if limit wasn't set to 0, 'name' - name of query, 'limit' - limit passed by user, & 'offest' - offset passed by user when api was called.
        """
        project_name, pid, dsnames, dsids = self._normalize_project_ds_ids(
            project, pid, datasources, dsids
        )

        query_params = {"aliased": 1 if alias_column_names else 0}
        if limit >= 0:
            query_params["limit"] = limit
        if offset >= 0:
            query_params["offset"] = offset

        if len(dsids) > 1:
            # POST
            endpoint = f"query/{self.user}/{pid}/"
            data = {}
            data["params"] = []
            for dsid in dsids:
                data["params"].append(
                    {
                        "column": column,
                        "dsid": dsid,
                        "operator": operator,
                        "value": value,
                    }
                )
            for param in query_params:
                data[param] = query_params[param]
            return self._post(
                endpoint, {}, data={"data": json.dumps(data)}, idempotent=True
            )
        else:
            # GET
            endpoint = (
                f"query/{self.user}/{pid}/{','.join(dsids)}/{column}/{operator}/{value}"
            )
            return self._get(endpoint, query_params)

    def list_schedules(self, state="enabled"):
        """
        state: 'disabled' or 'enabled'
        """
        return self._get("schedules", {"state": state})

    # ------------------------------------------------------------------
    # Studies/Experiment endpoints
    # ------------------------------------------------------------------

    def create_experiment(
        self,
        protocol_id: int,
        owner_isid: str,
        name: str = "",
        description: str = "",
        book: int = -1,
        automated: str = "N",
        project_id: int | None = None,
        properties: list | None = None,
        labels: list | None = None,
        populate_exp_name: bool = True,
    ) -> dict:
        """Create a new experiment via PUT /browser/api/studies/experiment.

        protocol_id: int. ID of the protocol to use (see list_protocols()).
        owner_isid:  str. ISID (username) of the experiment owner.
        name:        str. Display name for the experiment.
        description: str. Optional free-text description.
        book:        int. Notebook book ID; -1 means no book.
        automated:   str. "Y" or "N" — whether the experiment is automated.
        project_id:  int or None. Dotmatics project ID to associate with.
        properties:  list or None. List of {"propertyName": ..., "propertyValue": ...} dicts.
        labels: list or None, List of {"text": "label name"}

        Returns the API response dict (with "status" and "message" fields, plus
        any newly-created experiment metadata the server includes).
        """
        payload: dict = {
            "protocol": {"protocolID": protocol_id},
            "ownerISID": owner_isid,
            "description": description,
            "book": book,
            "automated": automated,
            "properties": properties or [],
            "labels": labels or [],
        }
        if project_id is not None:
            payload["projectId"] = project_id
        if name:
            payload["name"] = name

        return self._put_json(
            "studies/experiment", {"isPopulateExpName": populate_exp_name}, payload
        )

    def update_experiment(
        self,
        experiment_id: int,
        name: str | None = None,
        description: str | None = None,
        book: int | None = None,
        automated: str | None = None,
        project_id: int | None = None,
        properties: list | None = None,
    ) -> dict:
        """Update an existing experiment via PUT /browser/api/studies/experiment/{experimentId}.

        experiment_id: int. ID of the experiment to update.

        All other parameters are optional; only non-None values are included in
        the request payload so the caller can do a partial update.

        Returns the API response dict.
        """
        payload: dict = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if book is not None:
            payload["book"] = book
        if automated is not None:
            payload["automated"] = automated
        if project_id is not None:
            payload["projectId"] = project_id
        if properties is not None:
            payload["properties"] = properties
        return self._put_json(f"studies/experiment/{experiment_id}", data=payload)

    def delete_experiment(self, experiment_id: int) -> dict:
        """Delete an experiment via DELETE /browser/api/studies/experiment/{experimentId}.

        experiment_id: int. ID of the experiment to delete.

        Returns the API response dict.
        """
        return self._delete(f"studies/experiment/{experiment_id}")

    def complete_experiment(
        self, experiment_id: int, countersigner_isid: str = "", comment: str = ""
    ) -> dict:
        """Mark an experiment as complete via
        PUT /browser/api/studies/experiment/completeExperiment/{experimentId}.

        experiment_id:      int. ID of the experiment to complete.
        countersigner_isid: str. ISID of the countersigner (may be empty).
        comment:            str. Optional completion comment.

        Returns the API response dict.
        """
        payload = {}
        if countersigner_isid:
            payload["countersignerIsid"] = countersigner_isid
        if comment:
            payload["comment"] = comment
        return self._put_json(
            f"studies/experiment/completeExperiment/{experiment_id}", data=payload
        )

    def change_owner_of_experiment(self, experiment_id: int, isid: str) -> dict:
        """Update the owner for an experiment via
        PUT /browser/api/studies/experiment/alternateIsid/{experimentId}/{isid}.

        experiment_id: int. ID of the experiment to update.
        isid:          str. ISID of the new alternate experiment owner.

        Returns the API response dict on success, or raises ValueError on failure.
        """
        return self._put_json(
            f"studies/experiment/alternateIsid/{experiment_id}/{isid}"
        )

    # ------------------------------------------------------------------
    # Studies/ELN Adhoc file endpoints
    # ------------------------------------------------------------------

    def get_experiment_files(self, experiment_id: int) -> list:
        """Retrieve file metadata for files uploaded to an experiment via
        GET /browser/api/studies/elnAdhoc/getFiles/{experimentId}.

        experiment_id: int. ID of the experiment to list files for.

        Returns a list of Document dicts, each containing file metadata
        (e.g. documentId, fileName, fileSize, uploadDate).
        """
        return self._get(f"studies/elnAdhoc/getFiles/{experiment_id}")

    def check_files(self, experiment_id: int, file_names: list) -> list:
        """Check which files from a given list are attached to an experiment via
        PUT /browser/api/studies/elnAdhoc/checkFiles.

        experiment_id: int.       ID of the experiment to check.
        file_names:    list[str]. File names to look up.

        Returns a list of Document dicts for the files that were found.
        """
        payload = {
            "experimentId": experiment_id,
            "fileNames": file_names,
        }
        return self._put_json("studies/elnAdhoc/checkFiles", data=payload)

    def upload_files(self, file_paths: list | str) -> dict:
        """Upload one or more files to the server temp folder via
        POST /browser/api/studies/elnAdhoc/uploadFilesToServer.

        Files land in a server-side temp folder that is purged on a
        configurable schedule. Confirm retention on your deployment.
        Call add_files_to_experiment() to
        attach the uploaded files to an experiment before they are purged.

        file_paths: str or list[str]. Local path(s) to the file(s) to upload.

        Returns a dict with key "Uploaded files" mapping to a list of
        server-side file path strings.
        """
        if isinstance(file_paths, str):
            file_paths = [file_paths]

        file_handles = []
        try:
            files_list = []
            for path in file_paths:
                fh = open(path, "rb")
                file_handles.append(fh)
                filename = path.split("/")[-1].split("\\")[-1]
                files_list.append(("uploadfile", (filename, fh)))
            return self._post_files(
                "studies/elnAdhoc/uploadFilesToServer", files=files_list
            )
        finally:
            for fh in file_handles:
                fh.close()

    def add_files_to_experiment(
        self,
        experiment_id: int,
        files: list,
        script_id: int | None = None,
        form_id: int | None = None,
        skipRowsWithWarnings: bool | None = None,
    ) -> list:
        """Attach previously uploaded files to an experiment via
        PUT /browser/api/studies/elnAdhoc/addFiles.

        experiment_id: int.       ID of the experiment to attach files to.
        files:     list[str]. Server-side file paths returned by
                                  upload_files().
                                  Note: any "+" characters in paths must be
                                  encoded as "%2B" and any "%" as "%25"
                                  before passing them here.
        script_id:  int. Id of script associated with file(s)
        form_id:    int. Id of form associated with file(s)
        skipRowsWithWarnings:   bool. Flag for skipping rows with warnings.
        Returns a list of FileUploadResponse dicts that look liks so:
        {'Failed Files': [], 'Added Files': ['successfully_added_file.csv']}
        """
        payload = {
            "experimentId": experiment_id,
            "newFiles": [{"path": file} for file in files],
        }
        if script_id is not None:
            payload["scriptId"] = script_id
        if form_id is not None:
            payload["formId"] = form_id
        if skipRowsWithWarnings is not None:
            payload["skipRowsWithWarnings"] = skipRowsWithWarnings
        return self._put_json("studies/elnAdhoc/addFiles", data=payload)

    def delete_experiment_files(self, experiment_id: int, document_ids: list) -> dict:
        """Delete files from an experiment by document ID via
        DELETE /browser/api/studies/elnAdhoc/deleteFiles/{experimentId}.

        experiment_id: int.        ID of the experiment to remove files from.
        document_ids:  list[str].  Document IDs to delete from the experiment.

        Returns an empty dict on success (the API returns no response body
        on a 200).
        """
        return self._delete(
            f"studies/elnAdhoc/deleteFiles/{experiment_id}", data=document_ids
        )

    # ------------------------------------------------------------------
    # Studies/data endpoints
    # ------------------------------------------------------------------

    def parse_data_from_file(self, script_id, file_name: str):
        """Parses data out of file that has already been added to an experiment

        Statuses:
            200	successfully parsed

            400	error adding sample storage plate
        """
        return self._post_json(
            "studies/data/parse", data={"scriptID": script_id, "fileName": file_name}
        )

    def add_data_from_file_to_experiment(
        self,
        script_id: int,
        file_name: str,
        experiment_id: int,
        doc_id: str = "",
        skip_rows_with_warnings: bool = True,
    ) -> list:
        """Uploads a file, adds it to an experiment, & Parses data out of file

        Statuses:
            200	successfully parsed

            400	error adding sample storage plate
        """
        return self._post_json(
            "studies/data/upload",
            data={
                "scriptId": script_id,
                "fileName": file_name,
                "experimentId": experiment_id,
                "docId": doc_id,
                "skipRowsWithWarnings": skip_rows_with_warnings,
            },
        )

    # ------------------------------------------------------------------
    # Studies/Notebooks endpoints
    # ------------------------------------------------------------------

    def get_notebook_by_name(self, notebook_name: str):
        return self._get(f"studies/notebooks/{notebook_name}")

    def get_notebook_by_id(self, notebook_id: int):
        return self._get(f"studies/notebooks/{notebook_id}")

    def get_notebooks_by_name(self, notebook_names: list):
        return self._get(
            "studies/notebooks", query_params={"bookNames": notebook_names}
        )

    # ------------------------------------------------------------------
    # Studies/Protocol endpoints
    # ------------------------------------------------------------------

    def list_protocols(self) -> list:
        """Retrieve all protocols via GET /browser/api/studies/protocol/allProtocols.

        Returns a list of protocol dicts, each containing fields such as:
            protocolID, name, description, currentVersion, isAvailable,
            protocolType, dilutionFactor, conc, concUnits, plateFormatID,
            projectFormID, notebookTag.
        """
        return self._get("studies/protocol/allProtocols")

    def list_processing_scripts(self, protocol_id: str | int) -> list:
        """Retrieve processing scripts for a protocol via
        GET /browser/api/studies/protocol/{protocolId}/processingScripts.

        protocol_id: str | int. Protocol ID (OpenAPI path parameter protocolId).

        Returns a list of processing script dicts on success. On error the
        server may return 400; _get raises ValueError with status and body.
        """
        return self._get(f"studies/protocol/{protocol_id}/processingScripts")

    # ------------------------------------------------------------------
    # Register/SDF endpoints
    # ------------------------------------------------------------------

    def upload_sdf(self, sdf_path: str) -> int:
        """Upload an SDF file for registration via
        POST /browser/api/register/sdf/upload.

        sdf_path: str. Local filesystem path to the .sdf file to upload.

        Returns the integer file_id assigned by the server, which is needed
        for validate_sdf(), desalt_sdf(), and register_sdf_salts().
        """
        with open(sdf_path, "rb") as fh:
            filename = sdf_path.split("/")[-1].split("\\")[-1]
            files = {"uploadFile": (filename, fh)}
            return self._post_files("register/sdf/upload", files=files)

    def validate_sdf(self, file_id: int) -> dict:
        """Validate a previously uploaded SDF file via
        GET /browser/api/register/sdf/{file_id}/validate.

        file_id: int. The file_id returned by upload_sdf().

        Returns a dict containing validation statistics and metadata such as
        moleError, itemInFile, idMatches, lsAlias, etc.
        """
        return self._get(f"register/sdf/{file_id}/validate")

    def desalt_sdf(self, file_id: int) -> dict:
        """Desalt a previously uploaded SDF file via
        POST /browser/api/register/sdf/{file_id}/desalt.

        file_id: int. The file_id returned by upload_sdf().

        Returns a dict with fields: new_molecules, merge_salts, in_registry,
        items.
        """
        return self._post_json(f"register/sdf/{file_id}/desalt", data=None)

    def register_sdf_salts(self, file_id: int) -> dict:
        """Register salts for a previously uploaded SDF file via
        POST /browser/api/register/sdf/{file_id}/register_salts.

        file_id: int. The file_id returned by upload_sdf().

        Returns a dict with fields: status, message.
        """
        return self._post_json(f"register/sdf/{file_id}/register_salts", data=None)

    def _register_sdf(
        self,
        endpoint: str,
        map_path: str | None = None,
        salt_stripping: str | None = None,
    ):
        if map_path:
            with open(map_path, "rb") as fh:
                filename = map_path.split("/")[-1].split("\\")[-1]
                files = {"params": (filename, fh)}
                return self._post_files(
                    endpoint,
                    query_params={"salt_stripping": salt_stripping}
                    if salt_stripping
                    else None,
                    files=files,
                )
        return self._post_files(endpoint)

    def register_sdf_structures(
        self,
        file_id: int,
        map_path: str | None = None,
        salt_stripping: str | None = None,
    ) -> dict:
        """Register structures for a previously uploaded SDF file via
        POST /browser/api/register/sdf/{file_id}/register_structures.

        file_id: int. The file_id returned by upload_sdf().

        map_file_path: path to a map file which is formatted like so
            list of dicts  OR  str (path to a x-www-form-urlencoded/params file).
            Each dict describes one column mapping and must contain:
                tableName  – e.g. "reg_data", "reg_batches", "reg_samples"
                columnName – e.g. "supplier", "supplier_ref", "barcode"
                def        – default value string, e.g. "--None--"
                tag        – SDF tag name that maps to this column

            If a file path string is provided, the file is read and parsed
            as JSON to obtain the list of dicts.

        Returns a dict with fields: status, message.
        """
        return self._register_sdf(
            f"register/sdf/{file_id}/register_structures", map_path, salt_stripping
        )

    def register_sdf(
        self,
        file_id: int,
        map_path: str | None = None,
        salt_stripping: str | None = None,
    ) -> dict:
        """Run the full registration pipeline for a previously uploaded SDF via
        POST /browser/api/register/sdf/{file_id}/register.

        This is a convenience endpoint that combines desalt, register_salts,
        and register_structures in a single server-side call.

        file_id: int. The file_id returned by upload_sdf().

        Returns a dict with keys:
            structures – JSON string of the structure-registration result
            desalt     – dict with new_molecules, merge_salts, in_registry, items
            salts      – JSON string of the salt-registration result
        """
        return self._register_sdf(
            f"register/sdf/{file_id}/register", map_path, salt_stripping
        )

    def get_sdf_report(self, file_id: int) -> dict:
        """Retrieve the registration report for a previously uploaded SDF file via
        GET /browser/api/register/sdf/{file_id}/report.

        file_id: int. The file_id returned by upload_sdf().

        Returns a dict with fields:
            valid                  – number of valid structures
            salts_registered       – number of salts registered
            structures_registered  – number of structures registered
            desalted               – number of structures desalted
        """
        return self._get(f"register/sdf/{file_id}/report")
