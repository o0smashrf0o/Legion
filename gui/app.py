#!/usr/bin/env python3
"""Legion HUD — local kiosk GUI for Raspberry Pi. http://0.0.0.0:8088"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
MAPS_DIR = ROOT / "maps"
MAPS_JSON = MAPS_DIR / "maps.json"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from legionctl.context import AppContext  # noqa: E402
from legionctl.errors import LegionError, ValidationFailed  # noqa: E402
from legionctl.services.actions import (  # noqa: E402
    execute_reboots,
    execute_scans,
    execute_test_alerts,
)
from legionctl.services.audit import (  # noqa: E402
    build_audit_record,
    read_recent_audit,
    write_audit_record,
)
from legionctl.services.credentials import CredentialStore  # noqa: E402
from legionctl.services.deploy import (  # noqa: E402
    collect_push_plan,
    execute_push,
    reject_downgrades,
)
from legionctl.services.fleet import collect_events, collect_status  # noqa: E402
from legionctl.services.inventory import get_node, list_groups, list_nodes  # noqa: E402
from legionctl.services.org import (  # noqa: E402
    add_sentinel_to_cohort,
    archive_zone,
    assign_cohort_zone,
    assignment_for,
    create_cohort,
    create_zone,
    deactivate_cohort,
    fleet_overview,
    remove_sentinel_from_cohort,
    set_primus,
    update_cohort,
    update_zone,
)
from legionctl.services.profiles import (  # noqa: E402
    list_installed_profiles,
    load_installed_profile,
    save_watchlist,
    watchlist_from_profile,
)
from legionctl.settings import load_settings  # noqa: E402

app = Flask(__name__)
CTX = AppContext()


def _err(exc: BaseException, status: int = 400):
    return jsonify({"ok": False, "error": str(exc)}), status


def _audit(operation: str, targets: list[str], details: dict | None = None) -> None:
    write_audit_record(
        build_audit_record(operation, targets=targets, result="success", details=details or {})
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/ui/window")
def api_ui_window():
    action = str((request.get_json(silent=True) or {}).get("action") or "").lower()
    if action in {"close", "minimize", "desktop"}:
        for pat in (
            "chromium.*127.0.0.1:8088",
            "chromium-browser.*127.0.0.1:8088",
            "chromium.*192.168.50.2:8088",
            "chromium-browser.*192.168.50.2:8088",
        ):
            subprocess.run(
                ["pkill", "-f", pat],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        return jsonify({"ok": True, "action": action})
    if action in {"maximize", "fullscreen"}:
        return jsonify({"ok": True, "action": action})
    return jsonify({"ok": False, "error": "unknown action"}), 400


@app.get("/api/inventory")
def api_inventory():
    nodes = [node.model_dump(mode="json") for node in list_nodes()]
    groups = [group.model_dump(mode="json") for group in list_groups()]
    return jsonify({"ok": True, "nodes": nodes, "groups": groups})


@app.get("/api/status")
def api_status():
    nodes = list_nodes()
    if not nodes:
        return jsonify({"ok": True, "results": []})
    rows = asyncio.run(
        collect_status(nodes, CredentialStore(), app_ctx=CTX, settings=load_settings())
    )
    return jsonify({"ok": True, "results": [row.model_dump(mode="json") for row in rows]})


@app.get("/api/profiles")
def api_profiles():
    profiles = list_installed_profiles()
    return jsonify(
        {
            "ok": True,
            "profiles": [watchlist_from_profile(profile) for profile in profiles],
        }
    )


@app.get("/api/profiles/<profile_id>")
def api_profile_get(profile_id: str):
    try:
        profile = load_installed_profile(profile_id)
    except LegionError as exc:
        return _err(exc, 404)
    return jsonify({"ok": True, "profile": watchlist_from_profile(profile)})


@app.put("/api/profiles")
def api_profile_save():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _err("invalid profile payload")
    try:
        profile = save_watchlist(body)
    except ValidationFailed as exc:
        return jsonify({"ok": False, "error": "; ".join(exc.errors)}), 400
    except LegionError as exc:
        return _err(exc)
    return jsonify({"ok": True, "profile": watchlist_from_profile(profile)})


@app.post("/api/profiles/<profile_id>/push")
def api_profile_push(profile_id: str):
    body = request.get_json(silent=True) or {}
    if not body.get("confirm"):
        return _err("confirmation required")
    try:
        profile = load_installed_profile(profile_id)
        nodes = list_nodes()
        if not nodes:
            return _err("no Sentinel nodes in inventory")
        credentials = CredentialStore()
        settings = load_settings()
        plan = asyncio.run(
            collect_push_plan(
                profile, nodes, credentials, app_ctx=CTX, settings=settings
            )
        )
        reject_downgrades(plan, allow_downgrade=bool(body.get("allow_downgrade")))
        results = asyncio.run(
            execute_push(
                profile,
                plan,
                nodes,
                credentials,
                allow_downgrade=bool(body.get("allow_downgrade")),
                dry_run=False,
                app_ctx=CTX,
                settings=settings,
            )
        )
    except LegionError as exc:
        return _err(exc, getattr(exc, "exit_code", 400) or 400)
    return jsonify(
        {
            "ok": True,
            "results": [row.model_dump(mode="json") for row in results],
        }
    )


@app.get("/api/fleet")
def api_fleet():
    live = request.args.get("live") == "1"
    health_rows = None
    if live:
        nodes = list_nodes()
        if nodes:
            health_rows = asyncio.run(
                collect_status(nodes, CredentialStore(), app_ctx=CTX, settings=load_settings())
            )
    overview = fleet_overview(health_rows)
    overview["audit"] = read_recent_audit(15)
    return jsonify({"ok": True, **overview})


def _confirmed():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return None, _err("invalid payload")
    if not body.get("confirm"):
        return None, _err("confirmation required")
    return body, None


@app.post("/api/zones")
def api_zone_create():
    body, error = _confirmed()
    if error:
        return error
    try:
        zone = create_zone(
            name=str(body.get("name") or ""),
            zone_id=body.get("zone_id") or None,
            description=str(body.get("description") or ""),
            zone_type=str(body.get("zone_type") or "physical"),
        )
    except LegionError as exc:
        return _err(exc)
    _audit("zone_create", [zone.zone_id], {"name": zone.name})
    return jsonify({"ok": True, "zone": zone.model_dump(mode="json")})


@app.post("/api/zones/<zone_id>/archive")
def api_zone_archive(zone_id: str):
    _body, error = _confirmed()
    if error:
        return error
    try:
        zone = archive_zone(zone_id)
    except LegionError as exc:
        return _err(exc)
    _audit("zone_archive", [zone.zone_id], {"after": "inactive"})
    return jsonify({"ok": True, "zone": zone.model_dump(mode="json")})


@app.post("/api/zones/<zone_id>")
def api_zone_update(zone_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        zone = update_zone(
            zone_id,
            name=body.get("name"),
            description=body.get("description"),
            zone_type=body.get("zone_type"),
        )
    except LegionError as exc:
        return _err(exc)
    return jsonify({"ok": True, "zone": zone.model_dump(mode="json")})


@app.post("/api/cohorts")
def api_cohort_create():
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = create_cohort(
            display_name=str(body.get("display_name") or body.get("name") or ""),
            cohort_id=body.get("cohort_id") or None,
            description=str(body.get("description") or ""),
            zone_id=body.get("zone_id") or None,
        )
    except LegionError as exc:
        return _err(exc)
    _audit("cohort_create", [cohort.cohort_id], {"name": cohort.display_name})
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>")
def api_cohort_update(cohort_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = update_cohort(
            cohort_id,
            display_name=body.get("display_name"),
            description=body.get("description"),
        )
    except LegionError as exc:
        return _err(exc)
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>/assign-zone")
def api_cohort_assign_zone(cohort_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = assign_cohort_zone(cohort_id, body.get("zone_id") or None)
    except LegionError as exc:
        return _err(exc)
    _audit("cohort_assign_zone", [cohort_id], {"after": cohort.zone_id})
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>/add-sentinel")
def api_cohort_add_sentinel(cohort_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = add_sentinel_to_cohort(cohort_id, str(body.get("sentinel_id") or ""))
    except LegionError as exc:
        return _err(exc)
    _audit("cohort_add_sentinel", [cohort_id, str(body.get("sentinel_id") or "")])
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>/remove-sentinel")
def api_cohort_remove_sentinel(cohort_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = remove_sentinel_from_cohort(
            cohort_id,
            str(body.get("sentinel_id") or ""),
            new_primus=body.get("new_primus"),
        )
    except LegionError as exc:
        return _err(exc)
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>/set-primus")
def api_cohort_set_primus(cohort_id: str):
    body, error = _confirmed()
    if error:
        return error
    try:
        cohort = set_primus(cohort_id, body.get("primus_sentinel_id"))
    except LegionError as exc:
        return _err(exc)
    _audit("cohort_set_primus", [cohort_id], {"after": cohort.primus_sentinel_id})
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.post("/api/cohorts/<cohort_id>/deactivate")
def api_cohort_deactivate(cohort_id: str):
    _body, error = _confirmed()
    if error:
        return error
    try:
        cohort = deactivate_cohort(cohort_id)
    except LegionError as exc:
        return _err(exc)
    _audit("cohort_deactivate", [cohort_id], {"after": "inactive"})
    return jsonify({"ok": True, "cohort": cohort.model_dump(mode="json")})


@app.get("/api/sentinels/<sentinel_id>/assignment")
def api_sentinel_assignment(sentinel_id: str):
    try:
        payload = assignment_for(sentinel_id)
    except LegionError as exc:
        return _err(exc, 404)
    return jsonify({"ok": True, **payload})


@app.get("/api/events")
def api_events():
    sentinel_id = (request.args.get("node") or "").strip()
    if not sentinel_id:
        return _err("node is required")
    try:
        node = get_node(sentinel_id)
    except LegionError as exc:
        return _err(exc, 404)
    rows = asyncio.run(
        collect_events(
            [node],
            CredentialStore(),
            limit=20,
            app_ctx=CTX,
            settings=load_settings(),
        )
    )
    return jsonify({"ok": True, "results": [row.model_dump(mode="json") for row in rows]})


@app.get("/api/maps")
def api_maps_list():
    if MAPS_JSON.exists():
        try:
            maps = json.loads(MAPS_JSON.read_text(encoding="utf-8"))
            return jsonify({"ok": True, "maps": maps})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True, "maps": []})


@app.post("/api/maps")
def api_map_import():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    file_b64 = body.get("fileBase64")
    mime = body.get("mimeType", "image/png")
    if not name:
        return jsonify({"ok": False, "error": "name is required"}), 400
    # ensure dir exists
    MAPS_DIR.mkdir(parents=True, exist_ok=True)
    # determine extension
    ext = mime.split("/")[-1] if "/" in mime else "png"
    map_id = str(uuid4())
    # decode and save file
    try:
        data = base64.b64decode(file_b64)
    except Exception:
        return jsonify({"ok": False, "error": "invalid base64"}), 400
    filename = f"{map_id}.{ext}"
    filepath = MAPS_DIR / filename
    try:
        filepath.write_bytes(data)
    except Exception as e:
        return jsonify({"ok": False, "error": f"cannot write file: {e}"}), 500
    # read dimensions if possible via Pillow; if not, set None
    width_px = None
    height_px = None
    # read metadata
    new_entry = {
        "map_id": map_id,
        "name": name,
        "description": description,
        "source_filename": filename,
        "width_px": width_px,
        "height_px": height_px,
        "status": "active",
    }
    # load existing maps and append
    maps = []
    if MAPS_JSON.exists():
        try:
            maps = json.loads(MAPS_JSON.read_text(encoding="utf-8"))
        except Exception:
            maps = []
    maps.append(new_entry)
    try:
        MAPS_JSON.write_text(json.dumps(maps, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        return jsonify({"ok": False, "error": f"cannot save metadata: {e}"}), 500
    return jsonify({"ok": True, "map_id": map_id, "maps": maps})


@app.post("/api/actions/test-alert")
def api_test_alert():
    return _run_action("test-alert")


@app.post("/api/actions/scan")
def api_scan():
    return _run_action("scan")


@app.post("/api/actions/reboot")
def api_reboot():
    return _run_action("reboot")


def _run_action(kind: str):
    body = request.get_json(silent=True) or {}
    sentinel_id = str(body.get("node") or "").strip()
    if not sentinel_id:
        return _err("node is required")
    if not body.get("confirm"):
        return _err("confirmation required")
    try:
        node = get_node(sentinel_id)
    except LegionError as exc:
        return _err(exc, 404)
    credentials = CredentialStore()
    settings = load_settings()
    try:
        if kind == "test-alert":
            rows = asyncio.run(
                execute_test_alerts(
                    [node],
                    credentials,
                    message="Legion HUD test alert",
                    include_health_summary=True,
                    dry_run=False,
                    app_ctx=CTX,
                    settings=settings,
                )
            )
        elif kind == "scan":
            rows = asyncio.run(
                execute_scans(
                    [node],
                    credentials,
                    technology=str(body.get("technology") or "ble"),
                    duration_seconds=int(body.get("duration") or 30),
                    dry_run=False,
                    app_ctx=CTX,
                    settings=settings,
                )
            )
        else:
            rows = asyncio.run(
                execute_reboots(
                    [node],
                    credentials,
                    reason="operator_requested",
                    dry_run=False,
                    app_ctx=CTX,
                    settings=settings,
                )
            )
    except LegionError as exc:
        return _err(exc, getattr(exc, "exit_code", 400) or 400)
    return jsonify({"ok": True, "results": [row.model_dump(mode="json") for row in rows]})


def main() -> None:
    app.run(host="0.0.0.0", port=8088, debug=False)


if __name__ == "__main__":
    main()
