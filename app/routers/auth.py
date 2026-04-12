"""Firebase Authentication Router."""

import logging
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import firebase_admin
from firebase_admin import auth as firebase_auth

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])
templates = Jinja2Templates(directory="app/templates")

class NotAuthenticatedException(Exception):
    """Exception raised when a user is not authenticated."""
    pass

@router.get("/signin", response_class=HTMLResponse)
async def signin_page(request: Request):
    """Show the login page with Firebase JS."""
    email = request.session.get("email")
    if email and email.lower() in settings.allowed_emails_set:
        return RedirectResponse(url="/admin/", status_code=302)

    error = request.query_params.get("error")
    return templates.TemplateResponse("signin.html", {
        "request": request,
        "error": error,
    })

@router.post("/verify")
async def verify_firebase_token(request: Request):
    """Verify the Firebase ID token sent from the frontend."""
    data = await request.json()
    id_token = data.get("idToken")

    if not id_token:
        return JSONResponse({"status": "error", "message": "No token provided"}, status_code=400)

    try:
        # Verify the token against Firebase
        decoded_token = firebase_auth.verify_id_token(id_token)
        email = decoded_token.get("email", "").lower()
        name = decoded_token.get("name", "")
        picture = decoded_token.get("picture", "")

        logger.info(f"Firebase login attempt: {email}")

        # Check whitelist
        if email not in settings.allowed_emails_set:
            logger.warning(f"Access denied for: {email}")
            return JSONResponse({"status": "denied", "email": email, "redirect": f"/auth/access_denied?email={email}"}, status_code=403)

        # Authorized successfully - set session
        request.session["email"] = email
        request.session["name"] = name
        request.session["picture"] = picture

        logger.info(f"Login successful: {email}")
        return JSONResponse({"status": "success", "redirect": "/admin/"})

    except Exception as e:
        logger.error(f"Firebase token verification failed: {e}")
        return JSONResponse({"status": "error", "message": "Invalid token"}, status_code=401)

@router.get("/access_denied", response_class=HTMLResponse)
async def access_denied_page(request: Request, email: str = ""):
    """Show the access denied page."""
    return templates.TemplateResponse("access_denied.html", {
        "request": request,
        "email": email,
    })

@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    email = request.session.get("email", "unknown")
    request.session.clear()
    logger.info(f"Logged out: {email}")
    return RedirectResponse(url="/auth/signin", status_code=302)
