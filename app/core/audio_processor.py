"""
Core audio processing module
"""
import librosa
import numpy as np
import pandas as pd
from functional import seq
from scipy.stats import kurtosis
from scipy.signal import get_window
from acoustics import Signal
from acoustics.standards.iso_tr_25417_2007 import (
    sound_pressure_level, 
    equivalent_sound_pressure_level, 
    peak_sound_pressure_level
)
from acoustics.standards.iec_61672_1_2013 import (
    time_averaged_sound_level, 
    average
)

class AudioProcessor:
    """Process audio files and calculate noise metrics"""
    
    def __init__(self, reference_pressure: float = 20e-6):
        self.reference_pressure = reference_pressure
    
    def process_wav_file(self, file_path: str):
        """Process WAV file and calculate noise metrics
        
        Args:
            file_path (str): Path to the WAV file
            
        Returns:
            dict: Dictionary containing all noise metrics
        """
        # Load audio file
        y, sr = librosa.load(file_path, sr=None)
        s = Signal(y, sr)
        
        # Calculate 1/3 octave band metrics
        center_freq, octaves = s.third_octaves()
        freq_kurtosises = []
        freq_SPLs = []
        
        # Process each 1/3 octave band
        for freq_index in np.arange(8, 35, 3):
            s_octave = octaves[freq_index]
            average_value = average(
                data=s_octave.values, 
                sample_frequency=s_octave.fs, 
                averaging_time=0.125
            )
            freq_kurtosis = kurtosis(average_value, fisher=False)
            freq_SPL = time_averaged_sound_level(
                pressure=s_octave.values,
                sample_frequency=s.fs,
                averaging_time=1,
                reference_pressure=self.reference_pressure
            )[1]
            
            freq_kurtosises.append(round(freq_kurtosis, 2))
            freq_SPLs.append(freq_SPL)
        
        # Calculate overall metrics
        kurtosis_total = kurtosis(s.values, fisher=False)
        A_kurtosis_total = kurtosis(s.weigh("A").values, fisher=False)
        C_kurtosis_total = kurtosis(s.weigh("C").values, fisher=False)
        
        Leq = equivalent_sound_pressure_level(
            s.values, reference_pressure=self.reference_pressure)
        LAeq = equivalent_sound_pressure_level(
            s.weigh("A").values, reference_pressure=self.reference_pressure)
        LCeq = equivalent_sound_pressure_level(
            s.weigh("C").values, reference_pressure=self.reference_pressure)
        
        Peak_SPL = peak_sound_pressure_level(
            s.values, reference_pressure=self.reference_pressure)
        Peak_ASPL = peak_sound_pressure_level(
            s.weigh("A").values, reference_pressure=self.reference_pressure)
        Peak_CSPL = peak_sound_pressure_level(
            s.weigh("C").values, reference_pressure=self.reference_pressure)
        
        # Create result dataframes
        freq_kurtosises_df = pd.DataFrame(
            dict(
                zip([
                    "63 Hz", "125 Hz", "250 Hz", "500 Hz", "1000 Hz", "2000 Hz",
                    "4000 Hz", "8000 Hz", "16000 Hz"
                ],
                    seq(freq_kurtosises).map(lambda x: [x]))))
                    
        freq_SPLs_df = pd.DataFrame(
            dict(
                zip([
                    "63 Hz", "125 Hz", "250 Hz", "500 Hz", "1000 Hz", "2000 Hz",
                    "4000 Hz", "8000 Hz", "16000 Hz"
                ], freq_SPLs)))
        
        # Return all metrics
        return {
            "signal": s,
            "frequency_kurtosis": freq_kurtosises_df,
            "frequency_spl": freq_SPLs_df,
            "total_kurtosis": kurtosis_total,
            "a_weighted_kurtosis": A_kurtosis_total,
            "c_weighted_kurtosis": C_kurtosis_total,
            "leq": Leq,
            "laeq": LAeq,
            "lceq": LCeq,
            "peak_spl": Peak_SPL,
            "peak_aspl": Peak_ASPL,
            "peak_cspl": Peak_CSPL,
            "sampling_rate": s.fs,
            "duration": s.duration,
            "channels": s.channels
        }
    
    def plot_time_average_spl(self, s: Signal):
        """Plot time-averaged sound pressure level
        
        Args:
            s (Signal): Signal object
            
        Returns:
            tuple: Times and levels arrays
        """
        times, levels = time_averaged_sound_level(
            pressure=s.values,
            sample_frequency=s.fs,
            averaging_time=0.125,
            reference_pressure=self.reference_pressure)
        return times, levels
    
    def plot_power_spectrum_spl(self, s: Signal, window: str = "hann", nperseg: int = 1024):
        """Plot power spectrum sound pressure level
        
        Args:
            s (Signal): Signal object
            window (str): Window function
            nperseg (int): Number of samples per segment
            
        Returns:
            tuple: Frequencies and SPL arrays
        """
        window_func = get_window(window, len(s.values))
        windowed_s = Signal(s.values * window_func, s.fs)
        freqs, psd = windowed_s.power_spectrum(N=nperseg)
        freq_SPLs = sound_pressure_level(np.sqrt(psd), reference_pressure=self.reference_pressure)
        return freqs, freq_SPLs