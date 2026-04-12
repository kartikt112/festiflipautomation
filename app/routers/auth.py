"""Google OAuth2 Authentication Router (Server-Side Flow)."""

import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])
templates = Jinja2Templates(directory="app/templates")


class NotAuthenticatedException(Exception):
    """Raised when a user is not authenticated."""
    pass


# ─── Configure Authlib OAuth ───
oauth = OAuth()
oauth.register(
    name="google",
    client_id=settings.GOOGLE_CLIENT_ID,
    client_secret=settings.GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


@router.get("/signin", response_class=HTMLResponse)
async def signin_page(request: Request):
    """Show the sign-in page."""
    email = request.session.get("email")
    if email and email.lower() in settings.allowed_emails_set:
        return RedirectResponse(url="/admin/", status_code=302)

    error = request.query_params.get("error")
    return templates.TemplateResponse("signin.html", {
        "request": request,
        "error": error,
    })


@router.get("/google")
async def google_login(request: Request):
    """Redirect the user to Google's consent screen."""
    redirect_uri = str(request.url_for("google_callback"))
    # Force HTTPS in production
    if settings.APP_ENV == "production" or "railway" in redirect_uri:
        redirect_uri = redirect_uri.replace("http://", "https://")
    logger.info(f"OAuth redirect URI: {redirect_uri}")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def google_callback(request: Request):
    """Handle Google's OAuth callback."""
    try:
        token = await oauth.google.authorize_access_token(request)
        user_info = token.get("userinfo")

        if not user_info:
            logger.error("No user info returned from Google")
            return RedirectResponse(url="/auth/signin?error=no_user_info", status_code=302)

        email = user_info.get("email", "").lower()
        name = user_info.get("name", "")
        picture = user_info.get("picture", "")

        logger.info(f"Google login attempt: {email}")

        # Check whitelist
        if email not in settings.allowed_emails_set:
            logger.warning(f"Access denied for: {email}")
            return RedirectResponse(url=f"/auth/access_denied?email={email}", status_code=302)

        # Authorized — set session
        request.session["email"] = email
        request.session["name"] = name
        request.session["picture"] = picture

        logger.info(f"Login successful: {email}")
        return RedirectResponse(url="/admin", status_code=302)

    except Exception as e:
        logger.error(f"Google OAuth callback failed: {e}", exc_info=True)
        return RedirectResponse(url="/auth/signin?error=oauth_failed", status_code=302)


@router.get("/access_denied", response_class=HTMLResponse)
async def access_denied_page(request: Request, email: str = ""):
    """Show the access denied page."""
    return templates.TemplateResponse("access_denied.html", {
        "request": request,
        "email": email,
    })


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to sign-in."""
    email = request.session.get("email", "unknown")
    request.session.clear()
    logger.info(f"Logged out: {email}")
    return RedirectResponse(url="/auth/signin", status_code=302)
