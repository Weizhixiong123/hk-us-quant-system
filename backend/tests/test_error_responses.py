import asyncio
import json
from types import SimpleNamespace

from fastapi.exceptions import RequestValidationError

from app.main import _safe_validation_errors, create_app


def test_validation_errors_do_not_echo_input_values():
    exc = RequestValidationError(
        [
            {
                "type": "string_type",
                "loc": ("body", "private_key"),
                "msg": "Input should be a valid string",
                "input": "TOP-SECRET",
            }
        ]
    )

    errors = _safe_validation_errors(exc)

    assert errors[0]["loc"] == ("body", "private_key")
    assert "input" not in errors[0]
    assert "TOP-SECRET" not in json.dumps(errors)


def test_unhandled_exception_response_does_not_leak_details():
    app = create_app()
    handler = app.exception_handlers[Exception]
    request = SimpleNamespace(
        method="GET",
        url=SimpleNamespace(path="/api/test-error"),
    )

    response = asyncio.run(handler(request, RuntimeError("TOP-SECRET-TRACE")))

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": "服务器内部错误"}
    assert b"TOP-SECRET-TRACE" not in response.body
