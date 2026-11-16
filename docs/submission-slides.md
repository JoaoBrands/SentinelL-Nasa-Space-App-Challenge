# Sentinel — NASA Space Apps 2026 presentation

The editable seven-slide English demo is [`Sentinel_Space_Apps_2026_Pitch.pptx`](../Sentinel_Space_Apps_2026_Pitch.pptx). It stays within the challenge guide's seven-slide maximum, including the title slide.

## Story

1. **Sentinel** — Introduce the offline-first, explainable health-monitoring prototype and the `Create a Health Monitoring System` challenge.
2. **The problem** — Explain why onboard context and records matter when Earth communications are interrupted.
3. **Scientific basis** — Show how NASA references inform the design, while clearly stating that runtime readings are synthetic and no NASA data feed is connected.
4. **How it works** — Trace synthetic inputs through deterministic rules, evidence context, the crew workflow, and the blackout buffer.
5. **Live demo** — Show a real screenshot of the prototype with a live Ollama explanation for Ana's synthetic local CO₂ scenario, then walk through the manual airflow-path check and post-ramp reassessment. State that this is not clinical guidance.
6. **Resilience** — Demonstrate onboard processing and the bounded encrypted packet after communications are restored; clarify that the receiver is a same-process demo.
7. **Impact and limits** — Summarize what the prototype demonstrates, what real-world use would still require, and disclose SI-assisted work.

## Evidence and scope

- NASA OCHMO-TB-004 summarizes the 3 mmHg one-hour reference from NASA-STD-3001 Volume 2, requirement 6004; the rule operates on synthetic scenario values.
- NASA NTRS 20180000936 discusses local CO₂ pockets and limits on individual conclusions.
- NASA NTRS 20160012725 reports associations between ambient CO₂ and symptom reports; do not present association as causation.
- NASA NTRS 20230016189 provides EIMO context; it does not validate Sentinel.
- Do not describe the prototype as a medical device, NASA telemetry integration, clinical validation, or a real-habitat compliance system.
- Optional Ollama explanations may take several seconds and have a 60-second request timeout; deterministic rules assign status and risk, and the precomputed cache remains the fallback.

## SI disclosure

AI assistance was used for code implementation and review, tuning synthetic scenario values, generating optional live Ollama explanations, and drafting the slides. The demo image is a screenshot of the real prototype, not an AI-generated image; no AI-generated images, audio, or video are included. Each slide carries a visible SI-assisted-content notice.

## Submission checklist

- Keep the slide deck in English and within the seven-slide limit.
- Include the team name, all team members, the selected challenge, and a project image.
- List all external references in the project submission form.
- Declare SI use for code and data; do not select “I did not use SI.”
- Confirm team eligibility, required submission fields, and the deadline for the registered event.
