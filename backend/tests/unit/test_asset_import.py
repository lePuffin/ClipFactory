import io
import struct
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import create_engine

from clipfactory.assets.importing import AssetImportError, ImportProvenance, import_asset_file
from clipfactory.domain.models import AssetOrigin
from clipfactory.infrastructure.db.asset_repository import AssetRepository
from clipfactory.infrastructure.db.base import Base
from clipfactory.infrastructure.db.session import create_session_factory
from clipfactory.infrastructure.storage import LocalStorageProvider

NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
CC0 = ImportProvenance(license="CC0-1.0", author="Owner")


@pytest.fixture
def library(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'assets.db'}")
    Base.metadata.create_all(engine)
    yield AssetRepository(create_session_factory(engine)), LocalStorageProvider(tmp_path / "data")
    engine.dispose()


def _png(path: Path, size: tuple[int, int] = (800, 1200)) -> Path:
    buffer = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    return path


def _wav(path: Path) -> Path:
    data = b"\x00\x00" * 800
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, 1, 8000, 16000, 2, 16) + b"data" + struct.pack("<I", len(data))
    path.write_bytes(header + data)
    return path


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-REQ-202")
async def test_import_stores_content_addressed_imported_asset_with_provenance(library, tmp_path: Path) -> None:
    repository, storage = library
    source = _png(tmp_path / "Holiday Photo.PNG")

    result = await import_asset_file(
        source,
        category="photo",
        provenance=CC0,
        storage=storage,
        assets=repository,
        now=NOW,
        description=" Lisbon skyline ",
        tags=["Lisbon", " city ", "lisbon"],
        subjects=["Lisbon"],
    )

    asset = result.asset
    assert result.reused is False
    assert asset.storage_key == f"assets/{asset.sha256[:2]}/{asset.sha256}.png"
    assert storage.local_path(asset.storage_key).read_bytes() == source.read_bytes()
    assert (asset.media_type, asset.mime_type, asset.width, asset.height) == ("image", "image/png", 800, 1200)
    assert asset.provenance.origin == AssetOrigin.IMPORTED
    assert asset.provenance.provider == "manual_import"
    assert asset.provenance.license == "CC0-1.0"
    assert asset.provenance.author == "Owner"
    assert asset.description == "Lisbon skyline"
    assert asset.tags == ["city", "lisbon"]
    stored = repository.get(asset.id)
    assert stored is not None
    assert stored.sha256 == asset.sha256
    assert stored.provenance.origin == AssetOrigin.IMPORTED


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-REQ-202")
async def test_reimporting_identical_content_reuses_existing_asset(library, tmp_path: Path) -> None:
    repository, storage = library
    first = await import_asset_file(
        _wav(tmp_path / "a.wav"), category="other", provenance=CC0, storage=storage, assets=repository, now=NOW
    )
    second = await import_asset_file(
        _wav(tmp_path / "b.wav"), category="other", provenance=CC0, storage=storage, assets=repository, now=NOW
    )

    assert first.asset.media_type == "audio"
    assert first.asset.mime_type == "audio/wav"
    assert second.reused is True
    assert second.asset.id == first.asset.id
    assert len(repository.list()) == 1


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-REQ-201")
@pytest.mark.parametrize("license_value", ["", "   "])
async def test_import_without_licence_is_rejected_and_nothing_is_stored(
    library, tmp_path: Path, license_value: str
) -> None:
    repository, storage = library
    with pytest.raises(AssetImportError) as error:
        await import_asset_file(
            _png(tmp_path / "x.png"),
            category="photo",
            provenance=ImportProvenance(license=license_value),
            storage=storage,
            assets=repository,
            now=NOW,
        )
    assert error.value.code == "missing_license"
    assert repository.list() == []
    assert not (storage.root / "assets").exists()


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-REQ-203")
async def test_import_requiring_attribution_needs_attribution_text(library, tmp_path: Path) -> None:
    repository, storage = library
    with pytest.raises(AssetImportError) as error:
        await import_asset_file(
            _png(tmp_path / "x.png"),
            category="photo",
            provenance=ImportProvenance(license="CC-BY-4.0", attribution_required=True),
            storage=storage,
            assets=repository,
            now=NOW,
        )
    assert error.value.code == "invalid_provenance"
    assert repository.list() == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-NFR-105")
async def test_user_supplied_filename_is_never_used_as_storage_key(library, tmp_path: Path) -> None:
    repository, storage = library
    hostile = tmp_path / "nested" / "..%2F..%2Fx.mp3"
    hostile.parent.mkdir()
    _png(hostile)

    result = await import_asset_file(
        hostile, category="photo", provenance=CC0, storage=storage, assets=repository, now=NOW
    )

    assert result.asset.storage_key == f"assets/{result.asset.sha256[:2]}/{result.asset.sha256}.png"
    assert "x.mp3" not in result.asset.storage_key


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.parametrize(
    "payload",
    [b"<html>not media</html>", b"\x89PNG\r\n\x1a\nbroken-image-payload"],
    ids=["unknown_type", "undecodable_image"],
)
async def test_import_rejects_invalid_media(library, tmp_path: Path, payload: bytes) -> None:
    repository, storage = library
    source = tmp_path / "fake.png"
    source.write_bytes(payload)
    with pytest.raises(AssetImportError) as error:
        await import_asset_file(source, category="photo", provenance=CC0, storage=storage, assets=repository, now=NOW)
    assert error.value.code == "invalid_media"
    assert repository.list() == []


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.req("CF-NFR-104")
async def test_import_enforces_per_media_type_size_limit(library, tmp_path: Path) -> None:
    repository, storage = library
    source = _wav(tmp_path / "a.wav")
    size = source.stat().st_size

    accepted = await import_asset_file(
        source, category="other", provenance=CC0, storage=storage, assets=repository, now=NOW, max_audio_bytes=size
    )
    assert accepted.asset.size_bytes == size

    other = _png(tmp_path / "b.png")
    with pytest.raises(AssetImportError) as error:
        await import_asset_file(
            other,
            category="photo",
            provenance=CC0,
            storage=storage,
            assets=repository,
            now=NOW,
            max_image_bytes=other.stat().st_size - 1,
        )
    assert error.value.code == "file_too_large"


@pytest.mark.unit
@pytest.mark.req("CF-REQ-216")
@pytest.mark.parametrize("category", ["music", "narration", "title_card", "unknown"])
async def test_import_rejects_categories_without_supported_import_model(library, tmp_path: Path, category: str) -> None:
    repository, storage = library
    with pytest.raises(AssetImportError) as error:
        await import_asset_file(
            _wav(tmp_path / "a.wav"), category=category, provenance=CC0, storage=storage, assets=repository, now=NOW
        )
    assert error.value.code == "unsupported_category"
