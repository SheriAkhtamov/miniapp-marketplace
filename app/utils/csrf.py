from fastapi import Request, HTTPException, Form, Header
import secrets

CSRF_SESSION_KEY = "csrf_token"

def generate_csrf_token(request: Request) -> str:
    """
    Generates a CSRF token and stores it in the user's session.
    If a token already exists, returns the existing one.
    """
    if CSRF_SESSION_KEY not in request.session:
        request.session[CSRF_SESSION_KEY] = secrets.token_hex(32)
    return request.session[CSRF_SESSION_KEY]

def validate_csrf(request: Request, csrf_token: str = Form(...)):
    """
    Validates the CSRF token from the form data against the one in the session.
    """
    session_token = request.session.get(CSRF_SESSION_KEY)
    if not session_token or not secrets.compare_digest(session_token, csrf_token):
        raise HTTPException(status_code=403, detail="CSRF Token mismatch. Please refresh the page.")

def validate_csrf_header(
    request: Request,
    x_csrf_token: str = Header(None, alias="X-CSRF-Token"),
    x_csrf_token_legacy: str = Header(None, alias="X-CSRFToken"),
):
    """
    Validates CSRF token from X-CSRF-Token header.
    """
    provided_token = x_csrf_token or x_csrf_token_legacy
    session_token = request.session.get(CSRF_SESSION_KEY)
    if not session_token or not provided_token or not secrets.compare_digest(session_token, provided_token):
        raise HTTPException(status_code=403, detail="CSRF Token mismatch")
