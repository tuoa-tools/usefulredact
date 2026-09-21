"""Fixtures: one small generated document per redaction method, made once per session.

Everything is generated here from a fixed seed (Faker, en_AU); nothing is downloaded
and no real document is involved. The OCR and NER models load from the installed wheels.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from faker import Faker

from usefulredact import corpus
from usefulredact.pipeline import check_document

SEED = 1234


@pytest.fixture(scope="session")
def made(tmp_path_factory) -> dict[str, tuple[Path, corpus.Letter]]:
    """method -> (file, the letter it was made from), for every corpus method."""
    out = tmp_path_factory.mktemp("methods")
    rng = random.Random(SEED)
    fake = Faker("en_AU")
    fake.seed_instance(SEED)
    files = {}
    for index, method in enumerate(corpus.METHODS):
        style = corpus.STYLES[index % len(corpus.STYLES)]
        name, _, letter = corpus.make_document(method, style, rng, fake, out, f"fx_{method}")
        files[method] = (out / name, letter)
    return files


@pytest.fixture(scope="session")
def checked(made):
    """method -> DocResult, each file checked once."""
    return {method: check_document(path) for method, (path, _) in made.items()}
