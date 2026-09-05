from __future__ import annotations

import typer

from legionctl.commands.common import audit_action, exit_cli
from legionctl.context import get_app_context
from legionctl.errors import LegionError
from legionctl.output.console import console
from legionctl.output.json import emit_json
from legionctl.services import org

app = typer.Typer(help="Manage Legion map assets and placements.")


@app.command("list")
def map_list(ctx: typer.Context) -> None:
    """List imported maps."""
    app_ctx = get_app_context(ctx)
    try:
        maps = org.load_maps()
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json({"maps": maps})
        return
    if not maps:
        console.print("No maps imported.")
        return
    for m in maps:
        console.print(f"{m['map_id']}  {m.get('name', 'unnamed')}  {m.get('status', 'active')}")


@app.command("show")
def map_show(ctx: typer.Context, map_id: str = typer.Argument()) -> None:
    """Show one map's metadata."""
    app_ctx = get_app_context(ctx)
    try:
        map_data = org.get_map(map_id)
    except LegionError as exc:
        exit_cli(exc)
    if app_ctx.json_output:
        emit_json(map_data)
        return
    console.print(
        f"MAP // {map_data.get('name', 'unnamed')}\n"
        f"ID {map_id}\n"
        f"Description: {map_data.get('description', '')}"
    )


@app.command("import")
def map_import(
    ctx: typer.Context,
    name: str = typer.Option("--name", help="Map name"),
    description: str = typer.Option("", help="Map description"),
    file: str | None = typer.Option(None, help="Path to image file (PNG/JPEG/WebP)"),
    yes: bool = typer.Option(False, help="Skip confirmation prompt."),
) -> None:
    """Import a map image into Legion's managed storage."""
    if not file:
        console.print("Error: --file is required.")
        raise typer.Exit(code=1)
    try:
        import json
        from pathlib import Path

        from werkzeug.utils import secure_filename

        from legionctl.settings import get_paths

        fname = Path(file).name
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "png"
        if ext not in ("png", "jpg", "jpeg", "webp", "pdf"):
            console.print(f"Error: unsupported image type '{ext}'")
            raise typer.Exit(code=1)
        safe_name = secure_filename(fname)
        paths = get_paths()
        dest = Path(paths.data_dir) / "maps" / safe_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(file).read_bytes())

        map_id = str(__import__("uuid").uuid4())
        width_px = None
        height_px = None
        try:
            from PIL import Image as PILImage  # type: ignore

            with PILImage.open(dest) as img:
                width_px = img.width
                height_px = img.height
        except Exception:
            pass

        new_entry = {
            "map_id": map_id,
            "name": name or safe_name,
            "description": description,
            "source_filename": safe_name,
            "width_px": width_px,
            "height_px": height_px,
            "status": "active",
        }

        maps_path = Path(paths.state_dir) / "maps.json"
        maps_path.parent.mkdir(parents=True, exist_ok=True)
        maps = []
        if maps_path.exists():
            try:
                content = maps_path.read_text(encoding="utf-8")
                maps = json.loads(content)
            except Exception:
                maps = []
        maps.append(new_entry)
        maps_path.write_text(json.dumps(maps, indent=2) + "\n", encoding="utf-8")

        console.print(f"Map imported: {map_id} — {new_entry['name']}")
        audit_action(
            "map_imported",
            targets=[map_id],
            result="success",
            dry_run=False,
            confirmed_with_yes=yes,
        )
    except Exception as e:
        console.print(f"Error importing map: {e}")
        raise typer.Exit(code=1) from e


@app.command("archive")
def map_archive(
    ctx: typer.Context,
    map_id: str = typer.Argument(),
    yes: bool = typer.Option(False, help="Skip confirmation prompt."),
) -> None:
    """Archive a map (marks it inactive; placements and zone geometry are preserved)."""
    try:
        org.archive_map(map_id)
    except LegionError as exc:
        exit_cli(exc)
    console.print(f"Map {map_id} archived.")
    audit_action(
        "map_archived",
        targets=[map_id],
        result="success",
        dry_run=False,
        confirmed_with_yes=yes,
    )
