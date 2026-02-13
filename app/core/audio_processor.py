# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-13 22:00:00
@Author: Liu Hengjiang
@File: app/core/audio_processor.py
@Software: vscode
@Description:
        音频处理核心模块
        支持噪声指标计算、剂量计算、频谱分析等
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
import warnings

from app.core.dose_calculator import DoseCalculator, DoseStandard

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
        # Load audio file with specific parameters to avoid warnings
        try:
            # Suppress the warning as we know audioread will be used as fallback
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                y, sr = librosa.load(file_path, sr=None)
        except Exception as e:
            # If librosa fails completely, raise the error
            raise RuntimeError(f"Failed to load audio file {file_path}: {str(e)}")
        
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
        
        # Calculate noise dose for different standards
        duration_s = s.duration
        dose_results = DoseCalculator.calculate_multi_standard(LAeq, duration_s)
        
        # Extract dose percentages
        dose_niosh = dose_results["NIOSH"]["dose_pct"]
        dose_osha_pel = dose_results["OSHA_PEL"]["dose_pct"]
        dose_osha_hca = dose_results["OSHA_HCA"]["dose_pct"]
        dose_eu_iso = dose_results["EU_ISO"]["dose_pct"]
        
        # Calculate TWA for each standard
        profile_niosh = DoseCalculator.get_profile("NIOSH")
        profile_osha_pel = DoseCalculator.get_profile("OSHA_PEL")
        profile_osha_hca = DoseCalculator.get_profile("OSHA_HCA")
        profile_eu_iso = DoseCalculator.get_profile("EU_ISO")
        
        twa_niosh = DoseCalculator.calculate_twa(dose_niosh, profile_niosh)
        twa_osha_pel = DoseCalculator.calculate_twa(dose_osha_pel, profile_osha_pel)
        twa_osha_hca = DoseCalculator.calculate_twa(dose_osha_hca, profile_osha_hca)
        twa_eu_iso = DoseCalculator.calculate_twa(dose_eu_iso, profile_eu_iso)
        
        # Calculate LEX,8h
        lex_niosh = DoseCalculator.calculate_lex(dose_niosh, profile_niosh)
        lex_osha_pel = DoseCalculator.calculate_lex(dose_osha_pel, profile_osha_pel)
        lex_osha_hca = DoseCalculator.calculate_lex(dose_osha_hca, profile_osha_hca)
        lex_eu_iso = DoseCalculator.calculate_lex(dose_eu_iso, profile_eu_iso)
        
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
            "channels": s.channels,
            # Dose metrics
            "dose_niosh": dose_niosh,
            "dose_osha_pel": dose_osha_pel,
            "dose_osha_hca": dose_osha_hca,
            "dose_eu_iso": dose_eu_iso,
            # TWA metrics
            "twa_niosh": twa_niosh,
            "twa_osha_pel": twa_osha_pel,
            "twa_osha_hca": twa_osha_hca,
            "twa_eu_iso": twa_eu_iso,
            # LEX metrics
            "lex_niosh": lex_niosh,
            "lex_osha_pel": lex_osha_pel,
            "lex_osha_hca": lex_osha_hca,
            "lex_eu_iso": lex_eu_iso,
        }