"""Standalone synthetic ECG utilities; not connected to runtime monitoring."""
import numpy as np
import neurokit2 as nk


def generate_realistic_ecg(duration_sec: int = 10, heart_rate: int = 70) -> np.ndarray:
    """Generate a synthetic ECG signal for the prototype using NeuroKit2."""
    ecg = nk.ecg_simulate(duration=duration_sec, sampling_rate=1000, heart_rate=heart_rate)
    return ecg


def process_ecg(ecg_signal: np.ndarray, sampling_rate: int = 1000) -> dict:
    """Filter an ECG signal, detect R-peaks, and extract metrics."""
    signals, info = nk.ecg_process(ecg_signal, sampling_rate=sampling_rate)
    
    hr = signals["ECG_Rate"].mean()
    
    hrv_time = nk.hrv_time(signals, sampling_rate=sampling_rate)
    rmssd = hrv_time["HRV_RMSSD"].values[0] if not hrv_time.empty else 0.0
    
    # This prototype SQI estimates quality from the proportion of detected peaks.
    peaks = info["ECG_R_Peaks"]
    expected_peaks = (len(ecg_signal) / sampling_rate) * (hr / 60)
    sqi = min(1.0, len(peaks) / max(1, expected_peaks))
    
    return {
        "hr": round(float(hr), 1),
        "rmssd": round(float(rmssd), 1),
        "sqi": round(float(sqi), 2)
    }