"""Account connections and OS-backed secrets for the local publisher."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit

YOUTUBE_HANDLE = 'neonemesis8055'
INSTAGRAM_HANDLE = 'tyler1butsane'
GOOGLE_SCOPES = ['https://www.googleapis.com/auth/youtube.upload',
                 'https://www.googleapis.com/auth/youtube.readonly']
GRAPH = 'https://graph.instagram.com/v24.0'


class PublishError(RuntimeError):
    pass


def publishing_setup() -> str:
    missing = [name for name in ('google_auth_oauthlib', 'keyring', 'boto3', 'requests')
               if importlib.util.find_spec(name) is None]
    return ('Install requirements-publish.txt in this project, then restart Clipper.' if missing else '')


class Vault:
    def __init__(self, root: Path):
        self.service = 'clipperv1:' + hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:12]

    def backend(self):
        import keyring
        backend = keyring.get_keyring()
        native = ('keyring.backends.macOS', 'keyring.backends.Windows',
                  'keyring.backends.SecretService', 'keyring.backends.kwallet')
        if not type(backend).__module__.startswith(native):
            raise PublishError('Unlock or enable your OS credential store. Plaintext token storage is disabled.')
        return backend

    def get(self, name: str) -> dict | None:
        try:
            value = self.backend().get_password(self.service, name)
            return json.loads(value) if value else None
        except PublishError:
            raise
        except Exception:
            raise PublishError('Could not read the OS credential store. Unlock it and retry.') from None

    def put(self, name: str, data: dict) -> None:
        try:
            self.backend().set_password(self.service, name, json.dumps(data))
        except PublishError:
            raise
        except Exception:
            raise PublishError('Could not save to the OS credential store. Unlock it and retry.') from None

    def delete(self, name: str) -> None:
        if self.get(name) is not None:
            try:
                self.backend().delete_password(self.service, name)
            except Exception:
                raise PublishError('Could not remove the local saved credential.') from None


def plain_secret(value, label: str, maximum: int = 16384) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise ValueError(f'Enter a valid {label}.')
    return value.strip()


def api_json(session, method: str, url: str, service: str, **kwargs) -> dict:
    try:
        response = session.request(method, url, timeout=45, allow_redirects=False, **kwargs)
    except Exception:
        raise PublishError(f'Could not reach {service}. Check the connection and retry.') from None
    if not 200 <= response.status_code < 300:
        # Provider errors can echo tokens, signed URLs or complete request URLs.
        raise PublishError(f'{service} rejected the request (HTTP {response.status_code}). '
                           'Check the account, permissions and upload details.')
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise PublishError(f'{service} returned an unreadable response. Check before retrying an upload.') from None


def google_session(vault):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request, AuthorizedSession
    saved = vault.get('youtube')
    if not saved:
        raise PublishError('Connect YouTube before uploading.')
    credentials = Credentials.from_authorized_user_info(saved['credentials'], GOOGLE_SCOPES)
    if not credentials.valid:
        try:
            credentials.refresh(Request())
        except Exception:
            raise PublishError('YouTube authorization expired. Reconnect the channel.') from None
        saved['credentials'] = json.loads(credentials.to_json())
        vault.put('youtube', saved)
    return AuthorizedSession(credentials), saved


class Accounts:
    def __init__(self, vault, save_public):
        self.vault, self.save_public = vault, save_public
        self.pending = None
        self.lock = threading.Lock()

    def configure_google(self, config: dict) -> None:
        if not isinstance(config, dict) or not isinstance(config.get('installed'), dict):
            raise ValueError('Choose the Google OAuth client JSON for a Desktop app.')
        installed = config['installed']
        client_id = plain_secret(installed.get('client_id'), 'Google client ID', 2048)
        if not client_id.endswith('.apps.googleusercontent.com'):
            raise ValueError('Choose a Google Desktop OAuth client JSON.')
        clean = {'installed': {'client_id': client_id,
                              'client_secret': plain_secret(installed.get('client_secret'), 'Google client secret'),
                              'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                              'token_uri': 'https://oauth2.googleapis.com/token',
                              'redirect_uris': ['http://localhost']}}
        self.vault.put('youtube_client', clean)

    def google_begin(self, redirect: str) -> str:
        from google_auth_oauthlib.flow import InstalledAppFlow
        config = self.vault.get('youtube_client')
        if not config:
            raise ValueError('Import your Google Desktop OAuth JSON first.')
        flow = InstalledAppFlow.from_client_config(config, GOOGLE_SCOPES, autogenerate_code_verifier=True)
        flow.redirect_uri = redirect
        url, state = flow.authorization_url(access_type='offline', prompt='consent')
        with self.lock:
            self.pending = (time.time(), state, flow)
        return url

    def google_finish(self, state: str, code: str) -> None:
        from google.auth.transport.requests import AuthorizedSession
        with self.lock:
            pending = self.pending
            if (not pending or time.time() - pending[0] > 600 or not isinstance(state, str)
                    or not secrets.compare_digest(state, pending[1])):
                raise ValueError('Google connection expired or was not started here. Connect again.')
            self.pending = None
        plain_secret(code, 'authorization code')
        flow = pending[2]
        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
        except Exception:
            raise PublishError('Google sign-in did not complete. Connect again.') from None
        granted = credentials.granted_scopes
        if (not credentials.has_scopes(GOOGLE_SCOPES)
                or granted is not None and not set(GOOGLE_SCOPES).issubset(set(granted))):
            raise PublishError('Grant YouTube upload and channel-read permissions, then reconnect.')
        session = AuthorizedSession(credentials)
        mine = api_json(session, 'GET', 'https://www.googleapis.com/youtube/v3/channels', 'YouTube',
                        params={'part': 'snippet', 'mine': 'true'}).get('items', [])
        target = api_json(session, 'GET', 'https://www.googleapis.com/youtube/v3/channels', 'YouTube',
                          params={'part': 'id', 'forHandle': YOUTUBE_HANDLE}).get('items', [])
        if len(mine) != 1 or len(target) != 1 or mine[0]['id'] != target[0]['id']:
            raise PublishError(f'Connect the YouTube channel @{YOUTUBE_HANDLE}; this sign-in selected another channel.')
        public = {'id': mine[0]['id'], 'name': mine[0]['snippet']['title'], 'handle': YOUTUBE_HANDLE}
        self.vault.put('youtube', dict(public, credentials=json.loads(credentials.to_json())))
        self.save_public('youtube', public)

    def instagram_connect(self, token, app_secret='') -> None:
        import requests
        token = plain_secret(token, 'Instagram account access token')
        expires = None
        if app_secret:
            result = api_json(requests.Session(), 'GET', 'https://graph.instagram.com/access_token', 'Instagram',
                              params={'grant_type': 'ig_exchange_token', 'access_token': token,
                                      'client_secret': plain_secret(app_secret, 'Instagram app secret')})
            token = plain_secret(result.get('access_token'), 'Instagram access token')
            expires = time.time() + int(result['expires_in'])
        session = requests.Session()
        session.headers['Authorization'] = 'Bearer ' + token
        profile = api_json(session, 'GET', GRAPH + '/me', 'Instagram', params={'fields': 'user_id,username'})
        identity = str(profile.get('user_id') or profile.get('id') or '')
        if (str(profile.get('username', '')).lower() != INSTAGRAM_HANDLE
                or not re.fullmatch(r'\d{1,64}', identity)):
            raise PublishError(f'Connect Instagram @{INSTAGRAM_HANDLE}; this token belongs to another account.')
        public = {'id': identity, 'handle': INSTAGRAM_HANDLE, 'expires_at': expires}
        self.vault.put('instagram', dict(public, access_token=token, connected_at=time.time()))
        self.save_public('instagram', public)

    def storage_connect(self, data: dict) -> None:
        endpoint = str(data.get('endpoint', '')).strip().rstrip('/')
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path or parsed.port not in (None, 443)
                or parsed.hostname == 'localhost' or '.' not in parsed.hostname
                or re.fullmatch(r'[0-9.]+', parsed.hostname)):
            raise ValueError('Use the HTTPS endpoint from your S3-compatible provider, with no bucket path.')
        bucket, region = str(data.get('bucket', '')).strip(), str(data.get('region', 'auto')).strip()
        if (not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket)
                or not re.fullmatch(r'[a-z0-9-]{1,40}', region)):
            raise ValueError('Enter a valid bucket name and region (auto for R2).')
        public = {'endpoint': endpoint, 'bucket': bucket, 'region': region,
                  'id': hashlib.sha256(f'{endpoint}/{bucket}'.encode()).hexdigest()[:20]}
        self.vault.put('storage', dict(public,
                                      access_key=plain_secret(data.get('access_key'), 'storage access key'),
                                      secret_key=plain_secret(data.get('secret_key'), 'storage secret key')))
        self.save_public('storage', public)

    def disconnect(self, platform: str) -> None:
        if platform not in ('youtube', 'instagram', 'storage'):
            raise ValueError('Unknown connection.')
        self.vault.delete(platform)
        self.save_public(platform, None)


def instagram_session(vault, save_public):
    import requests
    saved = vault.get('instagram')
    if not saved:
        raise PublishError('Connect Instagram before uploading.')
    expires = saved.get('expires_at')
    if expires and expires <= time.time():
        raise PublishError('Instagram authorization expired. Reconnect the account.')
    if (expires and expires - time.time() < 7 * 86400
            and time.time() - saved['connected_at'] > 86400):
        result = api_json(requests.Session(), 'GET', 'https://graph.instagram.com/refresh_access_token', 'Instagram',
                          params={'grant_type': 'ig_refresh_token', 'access_token': saved['access_token']})
        saved.update(access_token=result['access_token'], expires_at=time.time() + int(result['expires_in']))
        vault.put('instagram', saved)
        save_public('instagram', {k: saved[k] for k in ('id', 'handle', 'expires_at')})
    session = requests.Session()
    session.headers['Authorization'] = 'Bearer ' + saved['access_token']
    return session, saved
