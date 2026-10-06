import base64
from urllib.parse import ParseResult as URLParseResult
from urllib.parse import urlencode, urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class AuthenticationError(Exception):
    pass


class DotmaticsClient:
    """Shared transport layer for the Dotmatics REST API clients.

    This owns the parts that are genuinely identical across the Browser and
    Inventory APIs: constructor validation, network configuration (proxy,
    timeouts), authentication, request-path construction, and authenticated
    GET. The write helpers (``_post``/``_put``/``_delete``/``post_files``) are
    deliberately *not* here: their wire formats, accepted status codes, and
    signatures differ between the two APIs, so each subclass owns its own.

    Subclasses target a specific API family by setting:
        ``_API_PREFIX``: path prefix under which the client's endpoints live,
            e.g. ``/browser/api`` or ``/inventory/api``.
        ``_AUTH_ENDPOINT``: the endpoint used to exchange credentials for a
            bearer token. Authentication always lives under ``/browser/api/``
            regardless of ``_API_PREFIX``.
    and by implementing ``_parse_auth_response`` to extract the token from that
    endpoint's reply (the two auth endpoints return different shapes).
    """

    #: Path prefix under which this client's endpoints live, e.g. '/browser/api'.
    _API_PREFIX: str = ""
    #: Authentication endpoint, resolved under '/browser/api/' for all clients.
    _AUTH_ENDPOINT: str = ""

    def __init__(
        self,
        user: str,
        password: str | None = None,
        token: object | None = None,
        *,
        dotmatics_instance: str,
        socks5_proxy: str | None = None,
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
            connection_timeout: Socket connection timeout in seconds.
            read_timeout: Socket read timeout in seconds.
            connect_retries: Number of times to retry a request whose connection
                could not be established (DNS failure, refused/timed-out connect,
                SOCKS negotiation failure). Retries back off exponentially
                (first retry immediately, then 2s, 4s, 8s, 16s at the default of 5).
                Connection-phase failures are retried for all methods — the
                request was never sent, so re-sending is always safe.
            read_retries: Number of times to re-send a request whose connection
                dropped or timed out after the request was sent (e.g. a read
                timeout on a severed connection). Each retry discards the dead
                connection and re-issues the full request on a fresh one, so
                ``read_timeout`` bounds socket inactivity, not total request
                duration (a streaming response can take longer). Applies to
                GETs, plus POSTs a subclass explicitly routes through
                ``_idempotent_session`` because they are read-only queries.
                Other requests may have been executed server-side before the
                response was lost, so they re-raise immediately as before.
                Note that when read retries are exhausted, requests raises
                ``ConnectionError`` (wrapping ``MaxRetryError``) rather than
                ``ReadTimeout``. HTTP error statuses are never retried.
        """
        if user is None or (token is None and password is None):
            raise ValueError("Must provide 'user' and either 'password' or 'token'.")

        parsed_instance = urlparse(dotmatics_instance)
        if parsed_instance.scheme not in ("http", "https"):
            raise ValueError("dotmatics_instance must use http or https.")
        if (
            not parsed_instance.hostname
            or parsed_instance.username is not None
            or parsed_instance.password is not None
        ):
            raise ValueError(
                "dotmatics_instance must have a hostname and no embedded credentials."
            )
        if any(c.isspace() for c in dotmatics_instance):
            raise ValueError("dotmatics_instance must not contain whitespace.")
        _ = parsed_instance.port  # Validate malformed or out-of-range ports.
        if any(
            [
                parsed_instance.path not in ("", "/"),
                parsed_instance.params,
                parsed_instance.query,
                parsed_instance.fragment,
            ]
        ):
            raise ValueError(
                "dotmatics_instance must not include a path, query, or fragment."
            )

        for name, value in (
            ("connection_timeout", connection_timeout),
            ("read_timeout", read_timeout),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive.")
        for name, value in (
            ("connect_retries", connect_retries),
            ("read_retries", read_retries),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer.")
        self.dotmatics_instance = parsed_instance._replace(path="")
        self.connection_timeout = connection_timeout
        self.read_timeout = read_timeout
        self.proxies = (
            {"http": socks5_proxy, "https": socks5_proxy} if socks5_proxy else None
        )
        self._session = self._build_retry_session(
            connect_retries, read_retries, allowed_methods=["GET"]
        )
        # For requests that are read-only queries despite their method (e.g.
        # POSTing an ID list to dodge URL-length limits): safe to re-send.
        self._idempotent_session = self._build_retry_session(
            connect_retries, read_retries, allowed_methods=["GET", "POST"]
        )
        self.user = user
        try:
            self.token = (
                token
                if token is not None
                else self._authenticate(user, password, expiration=24 * 60 * 60)
            )
        except Exception:
            self.close()
            raise

    def close(self):
        """Release pooled connections; do not use the client after closing."""
        self._session.close()
        self._idempotent_session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @staticmethod
    def _build_retry_session(
        connect_retries: int, read_retries: int, allowed_methods: list[str]
    ) -> requests.Session:
        """Session whose adapter retries connect failures for all methods and
        read failures for ``allowed_methods`` only, with exponential backoff."""
        session = requests.Session()
        retry_adapter = HTTPAdapter(
            max_retries=Retry(
                total=None,
                connect=connect_retries,
                read=read_retries,
                # Gates read/status retries only; connect retries apply to all
                # methods regardless.
                allowed_methods=allowed_methods,
                status=0,
                respect_retry_after_header=False,
                other=0,
                backoff_factor=1.0,
            )
        )
        session.mount("http://", retry_adapter)
        session.mount("https://", retry_adapter)
        return session

    # ------------------------------------------------------------------
    # URL construction
    # ------------------------------------------------------------------

    def _build_url(self, path: str, query_params: dict | None = None) -> str:
        """Assemble a full URL on the configured instance for an absolute path."""
        return urlunparse(
            URLParseResult(
                scheme=self.dotmatics_instance.scheme,
                netloc=self.dotmatics_instance.netloc,
                path=path,
                params="",
                query=urlencode(query_params, doseq=True) if query_params else "",
                fragment="",
            )
        )

    def _make_request_path(
        self, endpoint: str, query_params: dict | None = None
    ) -> str:
        """Build the URL for an API endpoint relative to this client's ``_API_PREFIX``.

        ``endpoint`` is the method only (e.g. ``projects/``); do NOT include the
        server or API prefix here, or a leading slash / query string.
        """
        if endpoint.startswith("/") or "?" in endpoint or "&" in endpoint:
            raise ValueError(f"Invalid endpoint: {endpoint!r}")
        return self._build_url(f"{self._API_PREFIX}/{endpoint}", query_params)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _authenticate(self, username: str, password: str | None, expiration: int = 600):
        """Exchange credentials for a token via the Browser-API auth endpoint.

        expiration: token lifetime in seconds.

        Returns whatever ``_parse_auth_response`` extracts from a 200 reply;
        raises ``AuthenticationError`` on any non-200 response.
        """
        encoded_credentials = base64.b64encode(
            f"{username}:{password}".encode()
        ).decode()
        url = self._build_url(
            f"/browser/api/{self._AUTH_ENDPOINT}", {"expiration": expiration}
        )
        response = self._session.get(
            url,
            headers={"Authorization": f"Basic {encoded_credentials}"},
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return self._parse_auth_response(response)
        raise AuthenticationError(
            {"status": response.status_code, "response": response.text}
        )

    def _parse_auth_response(self, response: requests.Response):
        """Extract the token to store as ``self.token`` from a 200 auth response.

        Subclasses must implement this: the Browser and Inventory auth
        endpoints return different payload shapes.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Authenticated requests
    # ------------------------------------------------------------------

    def _bearer_headers(self) -> dict:
        """Authorization header carrying the bearer token for API requests."""
        return {"Authorization": f"Bearer {self.token}"}

    def _get(self, endpoint: str, query_params: dict | None = None, raw: bool = False):
        """Makes a GET request to the Dotmatics API and returns the parsed result.

        endpoint: string. Only the method desired; DO NOT include the full
              server and API path here.
        query_params: dict or None. if dict, key,value pairs to include in the query.
        raw: bool. If true, return the requests.Response object instead of the
             parsed JSON reply. Primarily for debug usage.
        """
        url = self._make_request_path(endpoint, query_params)
        response = self._session.get(
            url,
            headers=self._bearer_headers(),
            proxies=self.proxies,
            timeout=(self.connection_timeout, self.read_timeout),
        )
        if response.status_code == 200:
            return response if raw else response.json()
        raise ValueError(
            {
                "status": response.status_code,
                "path": endpoint,
                "response": response.text,
            }
        )
