import base64
import hashlib
import os
import secrets
import string

import httpx
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = str(os.getenv("ALLEGRO_CLIENT_ID"))
CLIENT_SECRET = str(os.getenv("ALLEGRO_CLIENT_SECRET"))
REDIRECT_URI = str(os.getenv("ALLEGRO_REDIRECT_URI"))
AUTH_URL = "https://allegro.pl/auth/oauth/authorize"
TOKEN_URL = "https://allegro.pl/auth/oauth/token"


def generate_code_verifier() -> str:
    code_verifier = "".join((secrets.choice(string.ascii_letters) for i in range(40)))
    return code_verifier


def generate_code_challenge(code_verifier: str) -> str:
    hashed = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    base64_encoded = base64.urlsafe_b64encode(hashed).decode("utf-8")
    code_challenge = base64_encoded.replace("=", "")
    return code_challenge


def get_authorization_code(code_verifier: str) -> str:
    code_challenge = generate_code_challenge(code_verifier)
    authorization_redirect_url = (
        f"{AUTH_URL}?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&code_challenge_method=S256&code_challenge={code_challenge}"
    )
    print(
        "Zaloguj do Allegro - skorzystaj z url w swojej przeglądarce oraz wprowadź "
        "authorization code ze zwróconego url: "
    )
    print(f"--- {authorization_redirect_url} ---")
    authorization_code = input("code: ")
    return authorization_code


def get_access_token(authorization_code: str, code_verifier: str) -> dict:
    try:
        data = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
            "client_id": CLIENT_ID,
        }
        access_token_response = httpx.post(TOKEN_URL, data=data)
        access_token_response.raise_for_status()
        response_body = access_token_response.json()
        return response_body
    except httpx.HTTPStatusError as err:
        raise SystemExit(err) from err


def main() -> None:
    code_verifier = generate_code_verifier()
    authorization_code = get_authorization_code(code_verifier)
    response = get_access_token(authorization_code, code_verifier)
    print(f"Full response: {response}")
    access_token = response["access_token"]
    print(f"access token = {access_token}")


if __name__ == "__main__":
    main()
