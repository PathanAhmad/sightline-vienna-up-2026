"""Expand a zip/tar upload into the (name, bytes) pairs of images inside.

Lets the operator drop a single archive instead of hand-picking 200 files.
Caps total members + per-member size to defeat the worst zip-bomb shapes,
skips macOS resource forks and Windows thumbnails, and filters down to the
image extensions the QC pipeline actually scores.

Pure stdlib (zipfile + tarfile). No Streamlit, no third-party deps.
"""
from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import PurePosixPath


IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
MAX_MEMBERS = 500
MAX_BYTES_PER_MEMBER = 25 * 1024 * 1024  # 25 MB

_TAR_SUFFIXES = (
    ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2",
    ".tar.xz", ".txz",
)


def is_archive(name: str) -> bool:
    """True if the filename's extension suggests an archive we can expand."""
    lower = name.lower()
    return lower.endswith(".zip") or lower.endswith(_TAR_SUFFIXES)


def _is_image(name: str) -> bool:
    return PurePosixPath(name).suffix.lower() in IMAGE_EXTS


def _is_metadata(name: str) -> bool:
    """macOS resource forks (._foo), .DS_Store, Windows Thumbs.db, and the
    __MACOSX/ sidecar tree zip emits when compressing on a Mac."""
    parts = PurePosixPath(name).parts
    if "__MACOSX" in parts:
        return True
    base = PurePosixPath(name).name
    return base.startswith("._") or base in {".DS_Store", "Thumbs.db"}


def expand(name: str, data: bytes) -> list[tuple[str, bytes]]:
    """Return [(member_display_name, member_bytes), ...].

    If `name` is not an archive extension, returns [(name, data)] unchanged
    -- callers can treat archive and non-archive uploads uniformly.

    Display name format for expanded members: "archive.zip/IMG-001.jpg" so
    the operator can see which archive a result row came from.

    Raises ValueError if the archive is corrupt.
    """
    lower = name.lower()
    if lower.endswith(".zip"):
        return _expand_zip(name, data)
    if lower.endswith(_TAR_SUFFIXES):
        return _expand_tar(name, data)
    return [(name, data)]


def _expand_zip(archive_name: str, data: bytes) -> list[tuple[str, bytes]]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"{archive_name} is not a valid .zip") from e
    out: list[tuple[str, bytes]] = []
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if _is_metadata(info.filename) or not _is_image(info.filename):
                continue
            if info.file_size > MAX_BYTES_PER_MEMBER:
                continue
            if len(out) >= MAX_MEMBERS:
                break
            with zf.open(info) as fh:
                payload = fh.read(MAX_BYTES_PER_MEMBER + 1)
            if len(payload) > MAX_BYTES_PER_MEMBER:
                # Bomb-shape guard: declared size lied; bail on this member.
                continue
            display = f"{archive_name}/{PurePosixPath(info.filename).name}"
            out.append((display, payload))
    return out


def _expand_tar(archive_name: str, data: bytes) -> list[tuple[str, bytes]]:
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as e:
        raise ValueError(f"{archive_name} is not a valid tar archive") from e
    out: list[tuple[str, bytes]] = []
    with tf:
        for member in tf:
            if not member.isfile():
                continue
            if _is_metadata(member.name) or not _is_image(member.name):
                continue
            if member.size > MAX_BYTES_PER_MEMBER:
                continue
            if len(out) >= MAX_MEMBERS:
                break
            fh = tf.extractfile(member)
            if fh is None:
                continue
            payload = fh.read(MAX_BYTES_PER_MEMBER + 1)
            if len(payload) > MAX_BYTES_PER_MEMBER:
                continue
            display = f"{archive_name}/{PurePosixPath(member.name).name}"
            out.append((display, payload))
    return out
