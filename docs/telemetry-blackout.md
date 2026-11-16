# Blackout Telemetry Demo

During a simulated blackout, the onboard simulator and deterministic rules keep running. Mission Control receives no regular `tick` messages; the combined demo browser receives `onboard_tick` messages only to keep its onboard panel live. The server buffers bounded status transitions, unique alerts, symptoms, selected metric ranges, and actions. A crew-protocol reassessment action also includes the synthetic local CO₂ value and symptom inputs reviewed at that point.

On restore, the backend serializes the summary, compresses it with zlib, encrypts it with AES-256-GCM, and immediately decrypts it in the simulated receiver to verify the authentication tag. The UI shows the encrypted payload size and the verified summary, including the latest rolling one-hour module CO2 mean, its coverage in simulated minutes, the latest sample, and whether the hourly rule was active. Packet size is measured; the demo does not promise a 1 KB limit.

## Demo key

If `SENTINEL_TELEMETRY_KEY` is unset, the server creates an ephemeral 32-byte key for the WebSocket session and labels the packet `ephemeral_demo`. This is convenient for local demonstrations but is not persistent key management.

For a configured demo key, set `SENTINEL_TELEMETRY_KEY` to exactly 64 hexadecimal characters in the server's environment before starting the application. Do not commit the key or put it in browser code.

The demo receiver runs in the same backend process as the simulated onboard sender. The roundtrip verifies compression, encryption, and tamper detection in the prototype; it is not end-to-end spacecraft-to-Earth security or a production key-exchange design.