#!/usr/bin/env python3
"""Convert an iTunes Library XML file into one M3U8 file per playlist."""

from __future__ import annotations

import argparse
import plistlib
import re
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


TrackDict = dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert iTunes Library XML into per-playlist .m3u8 files."
    )
    parser.add_argument("library_xml", type=Path, help="Path to iTunes Library XML file")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("itunes_m3u8"),
        help="Directory where generated .m3u8 files are written",
    )
    parser.add_argument(
        "--include-master",
        action="store_true",
        help="Also export iTunes auto-generated master playlist",
    )
    parser.add_argument(
        "--add-extinf",
        action="store_true",
        help="Add #EXTINF metadata rows before each track (duration, artist, title)",
    )
    parser.add_argument(
        "--relative-paths",
        action="store_true",
        help="Write track paths relative to each generated playlist file",
    )
    parser.add_argument(
        "--relative-to",
        type=Path,
        help="Base directory for relative paths; relative values are resolved from the current working directory",
    )
    return parser.parse_args()


def sanitize_filename(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|]", "_", name).strip()
    return name or "untitled_playlist"


def decode_track_location(location: str) -> str:
    parsed = urlparse(location)
    if parsed.scheme and parsed.scheme.lower() != "file":
        return location

    if parsed.scheme.lower() == "file":
        path = unquote(parsed.path)
        # Normalize Windows file URLs like file://localhost/C:/Music/foo.mp3
        if re.match(r"^/[A-Za-z]:/", path):
            return path[1:]
        return path

    return location


def unique_playlist_path(output_dir: Path, name: str) -> Path:
    base = sanitize_filename(name)
    candidate = output_dir / f"{base}.m3u8"
    counter = 2
    while candidate.exists():
        candidate = output_dir / f"{base} ({counter}).m3u8"
        counter += 1
    return candidate


def format_extinf(track: TrackDict) -> str:
    total_time_ms = track.get("Total Time")
    seconds = -1
    if isinstance(total_time_ms, int):
        seconds = max(0, round(total_time_ms / 1000))

    artist = (track.get("Artist") or "Unknown Artist").strip()
    title = (track.get("Name") or "Unknown Title").strip()
    
    artist = artist.replace("\r", " ").replace("\n", " ")
    title = title.replace("\r", " ").replace("\n", " ")

    return f"#EXTINF:{seconds},{artist} - {title}"

    
def convert_to_relative_path(track_path: str, playlist_file: Path, relative_to: Path | None) -> str:
    # Windows drive-letter absolute path, e.g. C:/... or C:\...
    if re.match(r"^[A-Za-z]:[/\\]", track_path):
        path_obj = Path(track_path)
    else:
        parsed = urlparse(track_path)
        if parsed.scheme:
            return track_path

        path_obj = Path(track_path)
        if not path_obj.is_absolute():
            return track_path

    base_dir = relative_to if relative_to is not None else playlist_file.parent

    try:
        rel_path = os.path.relpath(str(path_obj), str(base_dir))
    except ValueError:
        # Different drive on Windows (e.g. C: vs D:)
        return track_path

    return Path(rel_path).as_posix()



def path_to_m3u_entry(path_str: str) -> str:
    # Windows drive-letter absolute path, e.g. C:/... or C:\...
    if re.match(r"^[A-Za-z]:[/\\]", path_str):
        return Path(path_str).as_uri()

    parsed = urlparse(path_str)
    if parsed.scheme:
        return path_str

    p = Path(path_str)

    if p.is_absolute():
        return p.as_uri()

    return p.as_posix()


def export_playlists(
    library_xml: Path,
    output_dir: Path,
    include_master: bool,
    add_extinf: bool,
    relative_paths: bool,
    relative_to: Path | None,
) -> tuple[int, int]:
    with library_xml.open("rb") as fh:
        library: dict[str, Any] = plistlib.load(fh)

    tracks = library.get("Tracks", {})
    playlists = library.get("Playlists", [])

    output_dir.mkdir(parents=True, exist_ok=True)

    exported_count = 0
    skipped_without_tracks = 0

    for playlist in playlists:
        if not include_master and playlist.get("Master"):
            continue

        playlist_name = playlist.get("Name") or "untitled_playlist"
        items = playlist.get("Playlist Items") or []

        entries: list[tuple[TrackDict, str]] = []
        for item in items:
            track = tracks.get(str(item.get("Track ID")))
            if not track:
                continue
            location = track.get("Location")
            if not location:
                continue
            entries.append((track, decode_track_location(location)))

        if not entries:
            skipped_without_tracks += 1
            continue

        playlist_file = unique_playlist_path(output_dir, playlist_name)
        with playlist_file.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("#EXTM3U\n")
            for track, track_path in entries:
                output_path = (
                    convert_to_relative_path(track_path, playlist_file, relative_to)
                    if relative_paths
                    else track_path
                )
                if add_extinf:
                    fh.write(f"{format_extinf(track)}\n")
                fh.write(path_to_m3u_entry(output_path) + "\n")

        exported_count += 1

    return exported_count, skipped_without_tracks


def main() -> int:
    args = parse_args()
    
    if args.relative_to and not args.relative_paths:
        args.relative_paths = True

    if args.relative_to and not args.relative_to.is_absolute():
        args.relative_to = (args.library_xml.parent / args.relative_to).resolve(strict=False)
    elif args.relative_to:
        args.relative_to = args.relative_to.resolve(strict=False)

    exported_count, skipped_without_tracks = export_playlists(
        library_xml=args.library_xml,
        output_dir=args.output_dir,
        include_master=args.include_master,
        add_extinf=args.add_extinf,
        relative_paths=args.relative_paths,
        relative_to=args.relative_to,
    )

    print(f"Exported {exported_count} playlist(s) to {args.output_dir}")
    if skipped_without_tracks:
        print(f"Skipped {skipped_without_tracks} playlist(s) without track locations")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
