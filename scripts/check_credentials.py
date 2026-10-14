#!/usr/bin/env python3
"""Check that the credentials in .env are accepted by each provider.

Makes read-only requests only. Secrets are never printed.
Usage:
  python3 scripts/check_credentials.py [--env path/to/.env]
  python3 scripts/check_credentials.py --profile football
  python3 scripts/check_credentials.py --youtube-auth   # one-time YouTube OAuth consent
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import select
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 20
YOUTUBE_REDIRECT_URI = "http://localhost:8000/auth/youtube/callback"
YOUTUBE_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
PROFILE_PREFIX: str | None = None


class Skip(Exception):
    pass


def load_env(path: Path) -> None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise Skip(f"{name} not set")
    return value


def env_path(name: str) -> Path:
    path = Path(env(name)).expanduser()
    return path if path.is_absolute() else ROOT / path


def profile_prefix(value: str) -> str:
    prefix = value.strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", prefix):
        raise argparse.ArgumentTypeError("profile must start with a letter and contain only letters, digits or underscores")
    return prefix


def account_env(name: str) -> str:
    key = f"{PROFILE_PREFIX}_{name}" if PROFILE_PREFIX else name
    value = os.environ.get(key, "").strip()
    if not value:
        raise Skip(f"{key} not set")
    return value


def account_optional_env(name: str) -> str:
    key = f"{PROFILE_PREFIX}_{name}" if PROFILE_PREFIX else name
    return os.environ.get(key, "").strip()


def request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> dict:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": "ClipFactory-credential-check", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"unreachable: {exc.reason}") from None


def check_llm() -> str:
    base = env("LLM_BASE_URL").rstrip("/")
    auth = {"Authorization": f"Bearer {env('LLM_API_KEY')}"}
    if "openrouter.ai" in base:
        info = request(f"{base}/key", headers=auth).get("data", {})
        return f"key '{info.get('label', '?')}', limit_remaining={info.get('limit_remaining')}, free_tier={info.get('is_free_tier')}"
    models = request(f"{base}/models", headers=auth).get("data", [])
    return f"{len(models)} models listed"


def check_google_tts() -> str:
    path = env_path("GOOGLE_APPLICATION_CREDENTIALS")
    if not path.is_file():
        raise RuntimeError(f"file not found: {path}")
    info = json.loads(path.read_text(encoding="utf-8"))
    if info.get("type") != "service_account":
        raise RuntimeError("not a service account key file")
    try:
        import google.auth.transport.requests
        from google.oauth2 import service_account
    except ImportError:
        return f"file OK ({info.get('client_email')}); install google-auth to test the API call"
    creds = service_account.Credentials.from_service_account_file(
        str(path), scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    voices = request(
        "https://texttospeech.googleapis.com/v1/voices?languageCode=en-US",
        headers={"Authorization": f"Bearer {creds.token}"},
    ).get("voices", [])
    return f"{len(voices)} en-US voices available"


def check_pexels() -> str:
    data = request("https://api.pexels.com/v1/search?query=news&per_page=1", headers={"Authorization": env("PEXELS_API_KEY")})
    return f"{data.get('total_results', 0)} results"


def check_pixabay() -> str:
    query = urllib.parse.urlencode({"key": env("PIXABAY_API_KEY"), "q": "news", "per_page": 3})
    return f"{request(f'https://pixabay.com/api/?{query}').get('totalHits', 0)} hits"


def check_unsplash() -> str:
    data = request(
        "https://api.unsplash.com/search/photos?query=news&per_page=1",
        headers={"Authorization": f"Client-ID {env('UNSPLASH_ACCESS_KEY')}", "Accept-Version": "v1"},
    )
    return f"{data.get('total', 0)} results"


def check_wikimedia() -> str:
    data = request(
        "https://commons.wikimedia.org/w/api.php?action=query&meta=siteinfo&format=json",
        headers={"User-Agent": env("WIKIMEDIA_USER_AGENT")},
    )
    return f"reachable ({data['query']['general']['sitename']})"


def check_comfyui() -> str:
    data = request(f"{env('COMFYUI_URL').rstrip('/')}/system_stats")
    return f"ComfyUI {data.get('system', {}).get('comfyui_version', '?')}"


def check_higgsfield() -> str:
    env("HIGGSFIELD_API_KEY")
    raise Skip("key set; no read-only check implemented")


def youtube_client() -> tuple[dict, Path]:
    if PROFILE_PREFIX:
        secrets_dir = ROOT / "secrets"
        client_path = account_optional_env("YOUTUBE_CLIENT_SECRETS_FILE")
        token_file = account_optional_env("YOUTUBE_TOKEN_FILE")
        path = Path(client_path).expanduser() if client_path else secrets_dir / "youtube_oauth.json"
        token_path = Path(token_file).expanduser() if token_file else secrets_dir / f"{PROFILE_PREFIX.lower()}_youtube_token.json"
        if client_path and not path.is_absolute():
            path = ROOT / path
        if token_file and not token_path.is_absolute():
            token_path = ROOT / token_path
    else:
        path = env_path("YOUTUBE_CLIENT_SECRETS_FILE")
        token_path = path.with_name("youtube_token.json")
    if not path.is_file():
        raise RuntimeError(f"file not found: {path}")
    info = json.loads(path.read_text(encoding="utf-8"))
    client = info.get("installed") or info.get("web")
    if not client or not client.get("client_id") or not client.get("client_secret"):
        raise RuntimeError("missing 'installed'/'web' client_id or client_secret")
    return client, token_path


def check_youtube() -> str:
    client, token_path = youtube_client()
    if not token_path.is_file():
        if PROFILE_PREFIX:
            raise Skip(f"scoped OAuth token file not found: {token_path}")
        return "client secrets file OK; run with --youtube-auth to authorise the channel"
    refresh_token = json.loads(token_path.read_text(encoding="utf-8"))["refresh_token"]
    token = request(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    channels = request(
        "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true",
        headers={"Authorization": f"Bearer {token['access_token']}"},
    ).get("items", [])
    if not channels:
        raise RuntimeError("token valid but the Google account has no YouTube channel")
    return f"channel '{channels[0]['snippet']['title']}' ({channels[0]['id']})"


def open_browser(url: str) -> None:
    # Under WSL, webbrowser.open silently fails; hand the URL to Windows instead.
    proc_version = Path("/proc/version")
    if proc_version.exists() and "microsoft" in proc_version.read_text(errors="ignore").lower():
        for cmd in (["wslview", url], ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"]):
            if shutil.which(cmd[0]):
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
    webbrowser.open(url)


def youtube_save_refresh_token() -> int:
    _, token_path = youtube_client()
    refresh_token = getpass.getpass("Paste the YouTube refresh token (input hidden): ").strip()
    if not refresh_token:
        print("No token entered.", file=sys.stderr)
        return 1
    token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_path.write_text(json.dumps({"refresh_token": refresh_token}, indent=2), encoding="utf-8")
    token_path.chmod(0o600)
    try:
        print(f"[ OK ] YouTube: {check_youtube()}")
    except Exception as exc:  # noqa: BLE001
        token_path.unlink()
        print(f"[FAIL] YouTube: {exc}", file=sys.stderr)
        return 1
    print(f"Saved YouTube token to {token_path}")
    return 0


def youtube_auth() -> int:
    client, token_path = youtube_client()
    if YOUTUBE_REDIRECT_URI not in client.get("redirect_uris", []):
        print(f"Add {YOUTUBE_REDIRECT_URI} as an authorised redirect URI of the OAuth client first.", file=sys.stderr)
        return 2

    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    auth_url = client.get("auth_uri", "https://accounts.google.com/o/oauth2/auth") + "?" + urllib.parse.urlencode(
        {
            "client_id": client["client_id"],
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "response_type": "code",
            "scope": YOUTUBE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    result: dict[str, str] = {}
    callback = urllib.parse.urlparse(YOUTUBE_REDIRECT_URI)

    class Handler(BaseHTTPRequestHandler):
        # Browsers open idle speculative connections; don't let them block the real request.
        timeout = 5

        def do_GET(self) -> None:
            url = urllib.parse.urlparse(self.path)
            if url.path != callback.path:
                self.send_error(404)
                return
            params = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            if params.get("state") != state:
                self.send_error(400, "state mismatch")
                return
            ok = "code" in params
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            message = "YouTube authorised. You can close this tab." if ok else f"Authorisation failed: {params.get('error')}"
            self.wfile.write(f"<p>{message}</p>".encode())
            result.update(params)

        def log_message(self, *args: object) -> None:
            pass

    class IPv6Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    # Windows resolves localhost to ::1 first; WSL only forwards it if something listens there.
    servers: list[ThreadingHTTPServer] = []
    for server_cls, host in ((ThreadingHTTPServer, "127.0.0.1"), (IPv6Server, "::1")):
        try:
            server = server_cls((host, callback.port or 80), Handler)
        except OSError as exc:
            print(f"Callback server on {host} not started ({exc}).")
            continue
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
    if not servers:
        print("No callback server running; use the paste option below.")

    print(f"1. Open this URL in any browser and allow access:\n\n{auth_url}\n")
    print("2. Google then redirects to http://localhost:8000/auth/youtube/callback?...")
    print("   If that page does not load, copy the full URL from the address bar and paste it here.\n")
    open_browser(auth_url)
    print("Redirect URL: ", end="", flush=True)
    while not result:
        ready, _, _ = select.select([sys.stdin], [], [], 0.5)
        if sys.stdin in ready:
            raw = sys.stdin.readline()
            if not raw:
                print("\nInput closed before authorisation completed.", file=sys.stderr)
                return 1
            line = raw.strip()
            params = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(line).query).items()}
            if "code" not in params and "error" not in params:
                print(
                    "That is not the redirect URL. Open the link above in the browser, allow access, then paste the\n"
                    "localhost:8000/auth/youtube/callback?...code=... address you end up on: ",
                    end="",
                    flush=True,
                )
                continue
            if params.get("state") != state:
                print("That URL is not from this sign-in (missing or wrong state). Paste the full redirect URL: ", end="", flush=True)
                continue
            result.update(params)
    print()
    for server in servers:
        server.shutdown()
        server.server_close()

    if "code" not in result:
        print(f"Authorisation failed: {result.get('error')}", file=sys.stderr)
        return 1
    token = request(
        client.get("token_uri", "https://oauth2.googleapis.com/token"),
        data={
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": YOUTUBE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )
    if "refresh_token" not in token:
        print("No refresh token returned; revoke the app at myaccount.google.com/permissions and retry.", file=sys.stderr)
        return 1
    token_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token_path.write_text(json.dumps(token, indent=2), encoding="utf-8")
    token_path.chmod(0o600)
    print(f"Saved YouTube token to {token_path}")
    print(f"[ OK ] YouTube: {check_youtube()}")
    return 0


def check_instagram() -> str:
    query = urllib.parse.urlencode({"fields": "user_id,username", "access_token": account_env("INSTAGRAM_ACCESS_TOKEN")})
    data = request(f"https://graph.instagram.com/me?{query}")
    expected = account_optional_env("INSTAGRAM_USER_ID")
    actual = str(data.get("user_id") or data.get("id"))
    if expected and expected != actual:
        raise RuntimeError(f"token belongs to user {actual}, INSTAGRAM_USER_ID is {expected}")
    return f"@{data.get('username')} (user {actual})"


def check_facebook() -> str:
    query = urllib.parse.urlencode({"fields": "id,name", "access_token": account_env("FACEBOOK_ACCESS_TOKEN")})
    data = request(f"https://graph.facebook.com/me?{query}")
    expected = account_optional_env("FACEBOOK_PAGE_ID")
    if expected and expected != data.get("id"):
        raise RuntimeError(f"token resolves to {data.get('name')} ({data.get('id')}), not FACEBOOK_PAGE_ID {expected}; use a Page access token")
    return f"Page '{data.get('name')}' ({data.get('id')})"


def check_tiktok() -> str:
    token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if token and token.strip():
        data = request(
            "https://open.tiktokapis.com/v2/user/info/?fields=open_id,union_id,avatar_url,display_name",
            headers={"Authorization": f"Bearer {token.strip()}"},
        )
        display = data.get("data", {}).get("user", {}).get("display_name")
        return f"access token valid: {display}" if display else "access token valid"
    data = request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": env("TIKTOK_CLIENT_KEY"),
            "client_secret": env("TIKTOK_CLIENT_SECRET"),
            "grant_type": "client_credentials",
        },
    )
    if "access_token" not in data:
        raise RuntimeError(data.get("error_description") or data.get("error") or "no access_token returned")
    return "client key/secret accepted; posting needs the one-time user authorisation"


def check_signing_key() -> str:
    if len(env("MEDIA_URL_SIGNING_KEY")) < 32:
        raise RuntimeError("shorter than 32 characters")
    return "length OK"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("LLM", check_llm),
    ("Google TTS", check_google_tts),
    ("Pexels", check_pexels),
    ("Pixabay", check_pixabay),
    ("Unsplash", check_unsplash),
    ("Wikimedia Commons", check_wikimedia),
    ("ComfyUI", check_comfyui),
    ("Higgsfield", check_higgsfield),
    ("YouTube", check_youtube),
    ("Instagram", check_instagram),
    ("Facebook", check_facebook),
    ("TikTok", check_tiktok),
    ("Media URL signing key", check_signing_key),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env", type=Path, default=ROOT / ".env", help="env file (default: .env)")
    parser.add_argument("--profile", type=profile_prefix, help="check YouTube, Instagram and Facebook credentials for this profile")
    parser.add_argument("--youtube-auth", action="store_true", help="run the one-time YouTube OAuth consent")
    parser.add_argument(
        "--youtube-refresh-token", action="store_true", help="store a refresh token obtained elsewhere (e.g. OAuth Playground)"
    )
    args = parser.parse_args()
    global PROFILE_PREFIX
    PROFILE_PREFIX = args.profile

    if not args.env.is_file():
        print(f"No env file at {args.env}", file=sys.stderr)
        return 2
    load_env(args.env)

    if args.youtube_auth:
        return youtube_auth()
    if args.youtube_refresh_token:
        return youtube_save_refresh_token()

    failed = 0
    checks = [("YouTube", check_youtube), ("Instagram", check_instagram), ("Facebook", check_facebook)] if args.profile else CHECKS
    for name, check in checks:
        try:
            print(f"[ OK ] {name}: {check()}")
        except Skip as exc:
            if args.profile:
                failed += 1
                print(f"[FAIL] {name}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 - report every provider, keep going
            failed += 1
            print(f"[FAIL] {name}: {exc}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
