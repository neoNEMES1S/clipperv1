"""Offline account, review and provider-protocol checks; never use real credentials."""
import copy
import json
from pathlib import Path
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

import pytest

import publish_accounts as accounts
import publish_uploads as uploads
from publishing import Publisher, posting_details


class MemoryVault:
    def __init__(self):
        self.values = {}

    def get(self, name):
        return copy.deepcopy(self.values.get(name))

    def put(self, name, value):
        self.values[name] = copy.deepcopy(value)

    def delete(self, name):
        self.values.pop(name, None)


@pytest.fixture
def publisher(tmp_path):
    output = tmp_path / 'shorts'
    (output / 'test_run').mkdir(parents=True)
    (output / 'test_run' / 'short_01.mp4').write_bytes(b'reviewed video')
    publisher = Publisher(tmp_path / 'state', output, MemoryVault())
    publisher.store.connection('youtube', {'id': 'channel', 'handle': accounts.YOUTUBE_HANDLE})
    publisher.store.connection('instagram', {'id': '1234', 'handle': accounts.INSTAGRAM_HANDLE})
    publisher.store.connection('storage', {'id': 'bucket-id', 'bucket': 'private-clips'})
    return publisher


def review(publisher, **changes):
    data = dict(youtube=True, instagram=False, title='A fight #Shorts', description='Test',
                caption='A fight', privacy='private', made_for_kids=False)
    data.update(changes)
    with patch('media.validate_short'):
        return publisher.review('test_run', {'name': 'short_01.mp4', 'start': 1, 'end': 37,
                                            'url': '/media/test_run/short_01.mp4'},
                                publisher.output / 'test_run' / 'short_01.mp4', data)


def saved_job(publisher, **changes):
    plan = review(publisher, **changes)
    ids, _ = publisher.commit(plan['review_id'])
    return publisher.store.get(ids[0])


def test_review_freezes_bytes_and_retry_keeps_details(publisher):
    record = saved_job(publisher)
    source = publisher.output / 'test_run' / 'short_01.mp4'
    source.write_bytes(b'a later headline edit')
    assert Path(record['asset']).read_bytes() == b'reviewed video'
    retry = publisher.review_retry(record['id'])
    assert retry['meta'] == record['meta']
    assert retry['preview'] == '/publish-media/' + record['id']
    assert publisher.commit(retry['review_id'])[0] == [record['id']]


@pytest.mark.parametrize('change', ['file', 'account', 'expiry', 'storage'])
def test_changed_review_cannot_upload(publisher, change):
    plan = review(publisher, instagram=True)
    if change == 'file':
        (publisher.output / 'test_run' / 'short_01.mp4').write_bytes(b'changed')
    elif change == 'account':
        publisher.store.connection('youtube', {'id': 'another'})
    elif change == 'storage':
        publisher.store.connection('storage', {'id': 'another'})
    else:
        publisher.reviews[plan['review_id']]['created'] = time.time() - 601
    with pytest.raises(ValueError):
        publisher.commit(plan['review_id'])
    assert publisher.store.history() == []


def test_review_is_single_use_and_completed_upload_is_not_duplicated(publisher):
    plan = review(publisher)
    ids, _ = publisher.commit(plan['review_id'])
    with pytest.raises(ValueError, match='expired'):
        publisher.commit(plan['review_id'])
    record = publisher.store.get(ids[0])
    record['status'] = 'uploaded'
    record['data']['url'] = 'https://youtu.be/Abc123_-xyz'
    publisher.store.save(record)
    second = review(publisher, title='Another title')
    assert second['destinations'][0]['status'] == 'uploaded'
    with pytest.raises(ValueError, match='already have'):
        publisher.commit(second['review_id'])
    with patch('publish_uploads.youtube_upload') as upload:
        assert publisher.run(ids)
        upload.assert_not_called()
    assert len(publisher.store.history()) == 1


def test_unfinished_upload_rejects_changed_metadata(publisher):
    saved_job(publisher)
    with pytest.raises(ValueError, match='unfinished'):
        review(publisher, title='Changed')


@pytest.mark.parametrize('changes', [
    {'youtube': False}, {'made_for_kids': None}, {'made_for_kids': 0},
    {'privacy': 'default'}, {'title': '<test>'}, {'title': 'a' * 101},
    {'description': '🎮' * 1251}, {'caption': 'a' * 2201}, {'caption': '\x00'},
])
def test_posting_validation(publisher, changes):
    with pytest.raises(ValueError):
        review(publisher, **changes)


def test_partial_failure_keeps_success_and_history_has_no_secrets(publisher):
    plan = review(publisher, instagram=True)
    ids, _ = publisher.commit(plan['review_id'])

    def youtube(_publisher, record, save):
        record['status'] = 'uploaded'
        record['data'].update(remote_id='Abc123_-xyz', uri='secret-session', progress=100)
        save('complete')

    with patch('publish_uploads.youtube_upload', side_effect=youtube), patch(
            'publish_uploads.instagram_upload', side_effect=accounts.PublishError('Instagram rejected request')):
        assert not publisher.run(ids)
    history = publisher.store.history()
    assert {item['status'] for item in history} == {'uploaded', 'failed'}
    assert 'secret-session' not in json.dumps(publisher.snapshot())
    assert publisher.review_retry(ids[1])['destinations'][0]['target'] == 'instagram'


def test_google_config_uses_trusted_endpoints_and_pkce(publisher):
    account = publisher.accounts
    account.configure_google({'installed': {'client_id': 'test.apps.googleusercontent.com',
                                          'client_secret': 'fake-secret', 'token_uri': 'https://evil.example'}})
    assert publisher.vault.get('youtube_client')['installed']['token_uri'] == 'https://oauth2.googleapis.com/token'
    url = account.google_begin('http://127.0.0.1:8765/oauth/youtube/callback')
    query = parse_qs(urlsplit(url).query)
    assert query['code_challenge_method'] == ['S256']
    assert query['access_type'] == ['offline']
    assert set(query['scope'][0].split()) == set(accounts.GOOGLE_SCOPES)
    pending = account.pending
    with pytest.raises(ValueError):
        account.google_finish('untrusted', 'code')
    assert account.pending is pending


@pytest.mark.parametrize('correct,granted', [(True, True), (False, True), (True, False)])
def test_google_verifies_grants_and_target_channel(publisher, correct, granted):
    credentials = Mock(granted_scopes=accounts.GOOGLE_SCOPES if granted else [])
    credentials.has_scopes.return_value = True
    credentials.to_json.return_value = '{"token":"fake"}'
    flow = Mock(credentials=credentials)
    publisher.accounts.pending = (time.time(), 'state', flow)
    responses = [{'items': [{'id': 'channel', 'snippet': {'title': 'Target'}}]},
                 {'items': [{'id': 'channel' if correct else 'wrong'}]}]
    with patch('publish_accounts.api_json', side_effect=responses), patch('google.auth.transport.requests.AuthorizedSession'):
        if correct and granted:
            publisher.accounts.google_finish('state', 'code')
            assert publisher.vault.get('youtube')['id'] == 'channel'
        else:
            with pytest.raises(accounts.PublishError):
                publisher.accounts.google_finish('state', 'code')
            assert publisher.vault.get('youtube') is None


def test_instagram_checks_identity_and_never_exposes_token(publisher):
    with patch('publish_accounts.api_json', return_value={'user_id': '1234', 'username': 'wrong'}):
        with pytest.raises(accounts.PublishError):
            publisher.accounts.instagram_connect('test-token')
    assert publisher.vault.get('instagram') is None
    with patch('publish_accounts.api_json', return_value={'user_id': '1234', 'username': accounts.INSTAGRAM_HANDLE}):
        publisher.accounts.instagram_connect('test-token')
    assert publisher.vault.get('instagram')['access_token'] == 'test-token'
    assert 'test-token' not in json.dumps(publisher.snapshot())


@pytest.mark.parametrize('endpoint', ['http://example.com', 'https://localhost', 'https://127.0.0.1',
                                    'https://s3.example.com/bucket', 'https://key@s3.example.com'])
def test_storage_rejects_unsafe_endpoints(publisher, endpoint):
    with pytest.raises(ValueError):
        publisher.accounts.storage_connect({'endpoint': endpoint})


def test_storage_credentials_are_only_in_vault(publisher):
    publisher.accounts.storage_connect(dict(endpoint='https://s3.example.com', bucket='private-clips',
                                           region='auto', access_key='fake-key', secret_key='fake-secret'))
    assert publisher.vault.get('storage')['secret_key'] == 'fake-secret'
    assert 'fake-secret' not in publisher.store.path.read_bytes().decode(errors='replace')
    assert 'fake-key' not in json.dumps(publisher.snapshot())


def test_vault_rejects_plaintext_and_redacts_provider_errors(tmp_path):
    with patch('keyring.get_keyring', return_value=Mock()), pytest.raises(accounts.PublishError, match='Plaintext'):
        accounts.Vault(tmp_path).put('test', {'token': 'fake'})
    response = Mock(status_code=400)
    response.json.return_value = {'error': 'secret-token'}
    session = Mock()
    session.request.return_value = response
    with pytest.raises(accounts.PublishError) as error:
        accounts.api_json(session, 'GET', 'https://example.com?token=secret-token', 'Provider')
    assert 'secret-token' not in str(error.value)


def response(status, data=None, **headers):
    result = Mock(status_code=status, headers=headers)
    result.json.return_value = data or {}
    return result


def google_context(publisher, replies):
    session = Mock()
    session.request.side_effect = replies
    session.credentials.to_json.return_value = '{"token":"fake-refreshed"}'
    return session, patch('publish_uploads.google_session', return_value=(session, {'id': 'channel'}))


def test_youtube_resumes_acknowledged_bytes_and_sets_explicit_privacy(publisher):
    record = saved_job(publisher)
    size = Path(record['asset']).stat().st_size
    session, context = google_context(publisher, [
        response(200, Location='https://www.googleapis.com/upload/session?private-receipt'),
        response(308, Range='bytes=0-3'),
        OSError('connection lost with token'),
        response(308, Range='bytes=0-7'),
        response(201, {'id': 'Abc123_-xyz', 'status': {'privacyStatus': 'private'}})])
    with context:
        uploads.youtube_upload(publisher, record, Mock())
    calls = session.request.call_args_list
    assert calls[0].kwargs['json']['status'] == {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}
    assert calls[2].kwargs['data'] == b'reviewed video'[4:]
    assert calls[4].kwargs['data'] == b'reviewed video'[8:]
    assert calls[4].kwargs['headers']['Content-Range'] == f'bytes 8-{size-1}/{size}'
    assert record['status'] == 'uploaded'
    assert publisher.vault.get('upload:' + record['id'])


def test_youtube_saved_session_does_not_start_another_upload(publisher):
    record = saved_job(publisher)
    publisher.vault.put('upload:' + record['id'], {'uri': 'https://www.googleapis.com/upload/receipt'})
    session, context = google_context(publisher, [response(410)])
    with context, pytest.raises(accounts.PublishError, match='expired'):
        uploads.youtube_upload(publisher, record, Mock())
    assert [call.args[0] for call in session.request.call_args_list] == ['PUT']


def test_youtube_rejects_external_session_and_stalled_acknowledgements(publisher):
    record = saved_job(publisher)
    session, context = google_context(publisher, [response(200, Location='https://evil.example/session')])
    with context, pytest.raises(accounts.PublishError, match='unexpected'):
        uploads.youtube_upload(publisher, record, Mock())
    assert session.request.call_count == 1
    publisher.vault.put('upload:' + record['id'], {'uri': 'https://www.googleapis.com/upload/session'})
    session, context = google_context(publisher, [response(308)] * 7)
    with context, pytest.raises(accounts.PublishError, match='not acknowledging'):
        uploads.youtube_upload(publisher, record, Mock())
    assert session.request.call_count <= 6


def instagram_context(publisher, record, replies, client=None):
    client = client or Mock()
    client.generate_presigned_url.return_value = 'https://s3.example.com/bucket/signed-clip'
    config = {'id': 'bucket-id', 'bucket': 'private-clips', 'endpoint': 'https://s3.example.com'}
    return (patch('publish_uploads.instagram_session', return_value=(Mock(), {'id': '1234'})),
            patch('publish_uploads.storage_for', return_value=(client, config)),
            patch('publish_uploads.instagram_asset', return_value=Path(record['asset'])),
            patch('publish_uploads.api_json', side_effect=replies))


def test_instagram_stages_selected_asset_publishes_and_cleans(publisher):
    record = saved_job(publisher, youtube=False, instagram=True)
    client = Mock()
    contexts = instagram_context(publisher, record, [
        {'id': '456'}, {'status_code': 'FINISHED'}, {'id': '789'},
        {'permalink': 'https://www.instagram.com/reel/test/'}], client)
    with contexts[0], contexts[1], contexts[2], contexts[3] as api:
        uploads.instagram_upload(publisher, record, Mock())
    assert record['status'] == 'published'
    assert record['data']['url'] == 'https://www.instagram.com/reel/test/'
    assert 'object_key' not in record['data']
    assert api.call_args_list[2].kwargs['json'] == {'creation_id': '456'}
    assert client.upload_file.call_args.args[0] == record['asset']
    assert 'ACL' not in client.upload_file.call_args.kwargs['ExtraArgs']
    client.delete_object.assert_called_once()


def test_instagram_ambiguous_publish_reconciles_without_second_post(publisher):
    record = saved_job(publisher, youtube=False, instagram=True)
    record['data'] = {'container': '456', 'publish_requested': True}
    contexts = instagram_context(publisher, record, [{'status_code': 'PUBLISHED'}])
    with contexts[0], contexts[1] as storage, contexts[2] as asset, contexts[3] as api:
        uploads.instagram_upload(publisher, record, Mock())
        storage.assert_not_called()
        asset.assert_not_called()
    assert record['status'] == 'published'
    assert api.call_count == 1
    assert record['data']['account_link']


def test_instagram_timeout_after_publish_checks_same_container(publisher):
    record = saved_job(publisher, youtube=False, instagram=True)
    record['data'] = {'container': '456'}
    contexts = instagram_context(publisher, record, [
        {'status_code': 'FINISHED'}, {'status_code': 'FINISHED'},
        accounts.PublishError('network interrupted'), {'status_code': 'PUBLISHED'}])
    with contexts[0], contexts[1], contexts[2], contexts[3] as api:
        uploads.instagram_upload(publisher, record, Mock())
    assert record['status'] == 'published'
    assert [call.args[1] for call in api.call_args_list].count('POST') == 1


def test_instagram_failed_cleanup_preserves_published_receipt(publisher):
    record = saved_job(publisher, youtube=False, instagram=True)
    client = Mock()
    client.delete_object.side_effect = OSError('secret-url')
    contexts = instagram_context(publisher, record, [
        {'id': '456'}, {'status_code': 'FINISHED'}, {'id': '789'}, {}], client)
    with contexts[0], contexts[1], contexts[2], contexts[3], pytest.raises(accounts.PublishError, match='cleanup failed'):
        uploads.instagram_upload(publisher, record, Mock())
    publisher.store.save(record)
    assert record['status'] == 'published'
    retry = publisher.review_retry(record['id'])
    ids, _ = publisher.commit(retry['review_id'])
    client.delete_object.side_effect = None
    with patch('publish_uploads.storage_for', return_value=(client, {'bucket': 'private-clips'})), patch('publish_uploads.instagram_upload') as post:
        assert publisher.run(ids)
        post.assert_not_called()
    assert not publisher.store.history()[0]['cleanup_pending']


def test_cleanup_cannot_delete_unowned_objects(publisher):
    record = saved_job(publisher, youtube=False, instagram=True)
    record['data']['object_key'] = 'someone-elses-video.mp4'
    with patch('publish_uploads.storage_for') as storage, pytest.raises(accounts.PublishError, match='Unexpected'):
        uploads.cleanup_staging(publisher, record, Mock())
    storage.assert_not_called()


@pytest.mark.parametrize('status', ['ERROR', 'EXPIRED'])
def test_instagram_uncertain_publish_never_creates_another_container(publisher, status):
    record = saved_job(publisher, youtube=False, instagram=True)
    record['data'] = {'container': '456', 'publish_requested': True}
    contexts = instagram_context(publisher, record, [{'status_code': status}])
    with contexts[0], contexts[1], contexts[2] as asset, contexts[3], pytest.raises(accounts.PublishError, match='earlier publish'):
        uploads.instagram_upload(publisher, record, Mock())
    asset.assert_not_called()
