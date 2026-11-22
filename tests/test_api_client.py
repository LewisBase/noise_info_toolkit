# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from app.web.api_client import ApiClient


def test_list_dirs_does_not_collide_with_request_path() -> None:
    client = ApiClient("http://127.0.0.1:8000")
    response = Mock()
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.json.return_value = {"path": "/tmp", "dirs": []}
    with patch.object(client._session, "request", return_value=response) as request:
        result = client.list_dirs("/tmp")
    assert result["path"] == "/tmp"
    assert request.call_args.kwargs["params"] == {"path": "/tmp"}
