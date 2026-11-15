"""Signed, expiring per-file tokens for the job files API."""

import pytest

from galaxy.security.idencoding import IdEncodingHelper
from galaxy.security.job_files_tokens import (
    JOB_FILES_READ,
    job_files_token,
    JOB_FILES_WRITE,
    verify_job_files_token,
)

NOW = 1_763_200_000
EXPIRES = NOW + 3600
PATH = "/galaxy/jobs/000/7/outputs/dataset_2.dat"


@pytest.fixture
def security():
    return IdEncodingHelper(id_secret="a test secret, not a real one")


def _token(security, job_id=7, path=PATH, scope=JOB_FILES_WRITE, expires=EXPIRES):
    return job_files_token(security, job_id, path, scope, expires)


def test_token_round_trip(security):
    token = _token(security)
    assert verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, token, now=NOW)
    assert verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, token, now=EXPIRES)


def test_token_is_bound_to_the_path(security):
    token = _token(security)
    for other in (PATH + "x", PATH + "/x", "/galaxy/jobs/000/7/outputs/../outputs/dataset_2.dat", PATH.upper(), ""):
        assert not verify_job_files_token(security, 7, other, JOB_FILES_WRITE, token, now=NOW)


def test_token_is_bound_to_the_scope(security):
    write_token = _token(security, scope=JOB_FILES_WRITE)
    read_token = _token(security, scope=JOB_FILES_READ)
    assert not verify_job_files_token(security, 7, PATH, JOB_FILES_READ, write_token, now=NOW)
    assert not verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, read_token, now=NOW)
    assert verify_job_files_token(security, 7, PATH, JOB_FILES_READ, read_token, now=NOW)


def test_token_is_bound_to_the_job_and_the_secret(security):
    token = _token(security)
    assert not verify_job_files_token(security, 8, PATH, JOB_FILES_WRITE, token, now=NOW)
    other_galaxy = IdEncodingHelper(id_secret="another test secret")
    assert not verify_job_files_token(other_galaxy, 7, PATH, JOB_FILES_WRITE, token, now=NOW)


def test_token_expires(security):
    token = _token(security)
    assert not verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, token, now=EXPIRES + 1)


def test_tampered_expiry_is_rejected(security):
    token = _token(security)
    expires, rest = token.split(".", 1)
    assert expires == str(EXPIRES)
    extended = f"{EXPIRES + 86400}.{rest}"
    assert not verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, extended, now=EXPIRES + 10)


@pytest.mark.parametrize(
    "token",
    [
        "",
        "abc",
        f"{EXPIRES}",
        f"{EXPIRES}.",
        "soon.c2lnbmF0dXJl",
        f"{EXPIRES}.not base64!",
        f"-1.{'A' * 43}",
        f"{EXPIRES}.sïgnature",
        "²³.c2lnbmF0dXJl",
    ],
)
def test_malformed_tokens_are_rejected(security, token):
    assert not verify_job_files_token(security, 7, PATH, JOB_FILES_WRITE, token, now=NOW)


def test_token_reveals_neither_the_job_key_nor_the_secret(security):
    token = _token(security)
    assert security.encode_id(7, kind="jobs_files") not in token
    assert "secret" not in token
    # Short enough for a URL query: expiry, a dot and an unpadded base64url SHA-256 digest.
    assert len(token) == len(str(EXPIRES)) + 1 + 43


def test_scope_must_be_known(security):
    with pytest.raises(ValueError):
        job_files_token(security, 7, PATH, "rw", EXPIRES)
