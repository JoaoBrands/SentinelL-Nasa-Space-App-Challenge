# NASA Sentinel

An offline-first decision-support prototype for long-duration spaceflight, inspired by **Earth Independent Medical Operations (EIMO)**. It demonstrates simulated crew health monitoring, explainable deterministic rules, and onboard operation during a communications blackout.

> **Use limitation:** This is a demonstration prototype, not a medical device. Crew and scenario data are synthetic; the rules and interventions have not been clinically validated or approved by NASA.

## What works

- Timeline simulation of the `CO2 Failure - Ana` scenario, including module and synthetic local CO₂, ventilation, heart rate, SpO₂, and symptoms.
- A time-weighted rolling average of module CO₂ over a complete 60-minute window. The environmental alert uses the 3 mmHg reference limit. Incomplete windows, missing, negative, non-finite, or malformed readings, and sampling gaps greater than 1.5 simulated minutes reset coverage.
- Separate individual alerts for Ana and environmental alerts for the module, with evidence, sources, and limitations.
- A local bedside fan with an illustrative five-minute ramp. It changes only Ana's simulated local airflow and CO₂.
- An interactive crew workflow for fan activation, manual airflow-path confirmation, and a post-ramp reassessment that records the current synthetic local CO₂ and scenario symptom inputs.
- A separate module ventilation action with an illustrative ten-minute ramp. The rolling average continues to be calculated, and the environmental alert clears only when the average falls to or below the reference limit.
- Blackout simulation: onboard rules continue running, events are summarized locally, and a compressed, authenticated AES-256-GCM packet is sent after communications are restored.
- Optional local explanations through Ollama. Risk classification comes from the deterministic rules engine; if Ollama is unavailable, the application uses precomputed explanations from its cache.
- Ollama requests allow up to 60 seconds for local inference; the first response may take tens of seconds. If Ollama is unavailable or times out, the application uses the precomputed explanation cache.

## Not connected to runtime monitoring

The ECG processor and SQI-filtered baseline store are standalone prototype utilities; the running application does not call them. The current scenario's heart rate and SpO₂ values are synthetic inputs, not ECG-derived measurements. The app does not monitor ECG, HRV, blood pressure, or individualized baselines, and it does not assess arrhythmias or cardiovascular stress.

When no individual scenario inputs are available, Ana is shown as `NOT_MONITORED`. Missing heart-rate and SpO₂ values are not replaced with normal defaults; malformed or out-of-range values are marked invalid and do not trigger alerts.

The interactive body map separates synthetic scenario inputs from general measurement-location context. It does not imply that the prototype has sensors for the measurements shown as context.

## Requirements

- Python 3.12 recommended.
- Windows, macOS, or Linux.
- Ollama and the `qwen2.5:7b` model are optional; without them, the application uses cached explanations.
- The dashboard chart is drawn with the browser's native Canvas API; the interface has no third-party CDN dependency. The backend and scenarios do not query the NASA API at runtime.

## Installation and launch

In PowerShell, from the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:8000`. If port 8000 is already in use, choose an available port when launching Uvicorn, for example:

```powershell
python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

After changing backend code, stop the running server with **Ctrl+C** and launch it again; `run.py` does not enable automatic reload. Refresh the browser and start a new scenario after restarting.

To enable live explanations through Ollama, start the Ollama service and download the model:

```powershell
ollama pull qwen2.5:7b
```

## Demonstration walkthrough

The seven-slide project demo is available in [`Sentinel_Space_Apps_2026_Pitch.pptx`](Sentinel_Space_Apps_2026_Pitch.pptx).

1. Start `CO2 FAILURE` and observe the module's hourly-average coverage counter.
2. When Ana's individual alert appears, activate the bed fan. In **CREW PROTOCOL**, confirm the airflow-path check manually; after the illustrative five-minute ramp, review and record the synthetic local CO₂ and scenario symptom inputs. The check is not sensor-verified, and the record is not a medical assessment. The simulated local recovery does not reduce module CO₂.
3. At T+60 simulated minutes, the module's hourly window is complete. In this scenario, the environmental alert crosses 3 mmHg at T+70.
4. While the module alert is active, select **START MODULE VENTILATION**. The simulation gradually reduces module CO₂, but the alert remains active while the rolling average is above 3 mmHg. In this scenario, the ventilation response completes at T+80 and the hourly-average alert clears at T+95.
5. Select **CUT COMMS**, then **RESTORE**, to demonstrate onboard operation and receipt of the authenticated telemetry summary.

The two intervention ramps are demonstration parameters: the bedside fan reaches a local CO₂ target of 1.8 mmHg over five minutes, and module ventilation reaches 2.4 mmHg over ten minutes. These targets and durations are not NASA-published limits, response times, or operational recommendations.

## Sources and provenance

The interface's **DATA AND EVIDENCE** panel and [`data/provenance.json`](data/provenance.json) link each rule to its sources and state its scope and limitations.

The NASA connection is specific: Sentinel takes the 3 mmHg one-hour reference summarized by NASA OCHMO-TB-004 from NASA-STD-3001 and implements it in the module CO₂ rule. That rule is applied to synthetic readings from the local scenario file. The project does not ingest a NASA open dataset or live NASA telemetry; its alerts are not measurements of, or compliance determinations for, a real habitat.

- [NASA OCHMO-TB-004: Carbon Dioxide](https://www.nasa.gov/ochmo-tb-004-carbon-dioxide-2/) summarizes NASA-STD-3001 Volume 2, requirement 6004: the one-hour average partial pressure of CO₂ in the habitable volume must not exceed 3 mmHg.
- [NASA NTRS 20180000936: Evidence Report on SANS](https://ntrs.nasa.gov/citations/20180000936), pages 61–62, discusses the physical plausibility of local CO₂ pockets and notes the lack of sufficient local measurements for individual conclusions.
- [NASA NTRS 20160012725](https://ntrs.nasa.gov/citations/20160012725) reports associations between ambient CO₂ on the ISS and reports of congestion and headache. The reported doubling of odds per 1 mmHg applies to congestion, not headache.
- [NASA NTRS 20230016189: Earth Independent Medical Operations](https://ntrs.nasa.gov/citations/20230016189) provides operational context for progressively autonomous medical support; it does not validate this prototype's clinical rules.

Ana's and the module's values are not NASA telemetry. The hourly average is calculated from a synthetic scenario and is not a compliance measurement for a real habitat.

## Tests

```powershell
python -m unittest discover -s tests -v
```

Tests cover the hourly average, incomplete windows, reading quality, sampling gaps, scenario transitions, local recovery, module ventilation, the interactive protocol's prerequisites and blackout reassessment snapshot, and packet authentication.

## Blackout telemetry

The data flow and limitations of the demonstration are described in [`docs/telemetry-blackout.md`](docs/telemetry-blackout.md). During a blackout, a recorded protocol reassessment includes its synthetic local CO₂ and scenario symptom inputs in the buffered packet. If `SENTINEL_TELEMETRY_KEY` is unset, the application generates an ephemeral key for each connection. The test receiver runs in the same backend; this demonstrates packet compression and authentication, not end-to-end security or mission-grade key management.

## Super Intelligence use

AI assistance was used for code implementation and review, tuning synthetic scenario values, generating optional live Ollama explanations, and drafting the project slides. The slide deck uses a screenshot of the real prototype, not an AI-generated image; no AI-generated images, audio, or video are included. Scenario values remain synthetic and are not NASA telemetry.
