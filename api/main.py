"""FastAPI + WebSocket server."""
import asyncio
import json
import math
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.config import DATA_DIR, PROFILES_DIR, PROJECT_ROOT
from core.sim.engine import SimulatorEngine
from core.rules.engine import RulesEngine
from core.telemetry import BlackoutBuffer, create_telemetry_packet, load_telemetry_key

app = FastAPI(title="NASA Sentinel")
WEB_DIR = PROJECT_ROOT / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def load_profiles() -> dict:
    profiles = {}
    for path in sorted(PROFILES_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        profiles[data["id"]] = data
    return profiles


def load_provenance() -> dict:
    with open(DATA_DIR / "provenance.json", "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/")
async def index():
    return FileResponse(str(WEB_DIR / "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    profiles = load_profiles()
    provenance = load_provenance()
    rules = RulesEngine(profiles, provenance.get("rule_evidence", {}))
    telemetry_key, telemetry_key_mode = load_telemetry_key()
    sim = SimulatorEngine()
    sim_task: asyncio.Task | None = None
    comms_online = True
    blackout_buffer: BlackoutBuffer | None = None
    protocol_steps: set[str] = set()
    tick_processing = asyncio.Event()
    tick_processing.set()

    profiles_summary = {
        cid: {"name": p["name_display"], "conditions": p.get("conditions", [])}
        for cid, p in profiles.items()
    }
    provenance_sent = False

    async def send_tick(state: dict):
        nonlocal provenance_sent
        tick_was_online = comms_online
        tick_buffer = blackout_buffer if not tick_was_online else None
        tick_processing.clear()
        try:
            evaluation = await asyncio.to_thread(rules.evaluate, state)
            if tick_buffer is not None:
                tick_buffer.record(state, evaluation)
            message = {
                "type": "tick" if tick_was_online else "onboard_tick",
                "state": state,
                "evaluation": evaluation,
                "profiles_summary": profiles_summary,
            }
            if not provenance_sent:
                message["provenance"] = provenance
                provenance_sent = True
            await ws.send_text(json.dumps(message))
        except Exception as e:
            print(f"[send_tick error] {e}")
        finally:
            tick_processing.set()

    await send_tick({"t": 0.0, "metrics": {}, "symptoms": [], "finished": False})

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "start_scenario":
                if sim_task and not sim_task.done():
                    sim.stop()
                    try:
                        await sim_task
                    except asyncio.CancelledError:
                        pass
                rules.reset()
                sim.load(msg["id"])
                protocol_steps.clear()
                sim_task = asyncio.create_task(sim.run(send_tick))

            elif action == "stop":
                sim.stop()
                if sim_task and not sim_task.done():
                    try:
                        await sim_task
                    except asyncio.CancelledError:
                        pass
                rules.reset()
                protocol_steps.clear()
                await send_tick({"t": 0.0, "metrics": {}, "symptoms": [], "finished": False})

            elif action == "activate_fan":
                print(">>> ACTION: Activate Bed Fan")
                sim.activate_fan()
                if blackout_buffer is not None:
                    blackout_buffer.record_action("activate_bed_fan", sim.current_t)

            elif action == "activate_module_ventilation":
                print(">>> ACTION: Activate Module Ventilation (illustrative simulation)")
                sim.activate_module_ventilation()
                if blackout_buffer is not None:
                    blackout_buffer.record_action("activate_module_ventilation", sim.current_t)

            elif action == "protocol_step":
                step = msg.get("step")
                if not isinstance(step, str) or step not in {"airflow_check", "reassessment"}:
                    await ws.send_text(json.dumps({
                        "type": "protocol_error",
                        "step": step,
                        "message": "Unknown protocol step.",
                    }))
                    continue

                state = sim.get_state()
                fan = state.get("interventions", {}).get("bed_fan")
                error = None
                if not fan or not fan.get("active"):
                    error = "Activate the bedside fan before confirming this step."
                elif step == "reassessment" and "airflow_check" not in protocol_steps:
                    error = "Confirm the airflow-path check before reassessment."
                elif step == "reassessment" and fan.get("progress_percent", 0) < 100:
                    error = "Wait for the five-minute fan ramp before reassessment."

                local_co2 = state.get("metrics", {}).get("ana_local_co2")
                if (
                    step == "reassessment"
                    and error is None
                    and (
                        isinstance(local_co2, bool)
                        or not isinstance(local_co2, (int, float))
                        or not math.isfinite(local_co2)
                        or local_co2 < 0
                    )
                ):
                    error = "A valid synthetic local CO₂ value is unavailable for reassessment."

                if error is not None:
                    await ws.send_text(json.dumps({
                        "type": "protocol_error",
                        "step": step,
                        "message": error,
                    }))
                    continue

                if step not in protocol_steps:
                    protocol_steps.add(step)
                    if blackout_buffer is not None:
                        details = None
                        if step == "reassessment":
                            details = {
                                "local_co2_mmhg": round(local_co2, 2),
                                "symptoms": [
                                    {
                                        key: symptom[key]
                                        for key in ("crew", "symptom", "t")
                                        if key in symptom
                                    }
                                    for symptom in state.get("symptoms", [])
                                ],
                            }
                        blackout_buffer.record_action(
                            f"protocol_{step}", sim.current_t, details=details
                        )

                ack = {
                    "type": "protocol_ack",
                    "step": step,
                    "sim_t": round(sim.current_t, 2),
                }
                if step == "reassessment":
                    ack["local_co2_mmhg"] = round(local_co2, 2)
                    ack["symptoms"] = state.get("symptoms", [])
                await ws.send_text(json.dumps(ack))

            elif action == "cut_comms":
                if not comms_online:
                    continue
                comms_online = False
                blackout_buffer = BlackoutBuffer(sim.current_t)
                print(">>> COMMS CUT: Entering Blackout mode")
                await ws.send_text(json.dumps({
                    "type": "link_status",
                    "status": "blackout",
                    "sim_t": round(sim.current_t, 2),
                }))

            elif action == "restore_comms":
                if comms_online or blackout_buffer is None:
                    continue
                await tick_processing.wait()
                payload = blackout_buffer.finish(sim.current_t)
                try:
                    packet, receipt = create_telemetry_packet(payload, telemetry_key)
                except Exception as exc:
                    print(f"[telemetry packet error] {exc}")
                    await ws.send_text(json.dumps({
                        "type": "link_error",
                        "message": "Could not authenticate buffered telemetry. The blackout buffer was retained.",
                    }))
                    continue

                event_count = sum(
                    len(payload[key])
                    for key in ("crew_status_changes", "alerts", "symptoms", "actions")
                )
                await ws.send_text(json.dumps({
                    "type": "telemetry_packet",
                    "packet": packet,
                    "receipt": receipt,
                    "record_count": event_count,
                    "key_mode": telemetry_key_mode,
                    "receiver_verified": True,
                    "receiver_note": (
                        "Demo receiver runs in this same backend process; this validates "
                        "the packet roundtrip, not a deployed spacecraft-to-Earth link."
                    ),
                }))
                comms_online = True
                blackout_buffer = None
                print(">>> COMMS RESTORED: Buffered telemetry authenticated by demo receiver")
                
    except WebSocketDisconnect:
        sim.stop()
        if sim_task:
            sim_task.cancel()