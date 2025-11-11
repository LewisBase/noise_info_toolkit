"""
Create a test TDMS file for testing the noise info toolkit
"""
import numpy as np
from nptdms import TdmsWriter, ChannelObject
import os

def create_test_tdms_file(filename="test_signal.tdms", duration=10, sampling_rate=44100):
    """Create a test TDMS file with a synthetic noise signal"""
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else ".", exist_ok=True)
    
    # Generate synthetic noise signal
    t = np.linspace(0, duration, int(sampling_rate * duration))
    # Create a noise signal with some frequency components
    signal = (np.random.normal(0, 0.1, len(t)) + 
              0.5 * np.sin(2 * np.pi * 500 * t) +  # 500 Hz tone
              0.3 * np.sin(2 * np.pi * 1000 * t) + # 1000 Hz tone
              0.2 * np.sin(2 * np.pi * 2000 * t))  # 2000 Hz tone
    
    # Normalize to -1 to 1 range
    signal = signal / np.max(np.abs(signal))
    
    # Create TDMS file
    with TdmsWriter(filename) as tdms_writer:
        # Create a group
        group_name = "NoiseData"
        
        # Create a channel with the signal data
        channel = ChannelObject(
            group_name,
            "AudioSignal",
            signal,
            properties={
                "SampleRate": sampling_rate,
                "Units": "V",
                "Description": "Synthetic noise signal for testing"
            }
        )
        
        # Write the channel to the file
        tdms_writer.write_segment([channel])
    
    print(f"Created test TDMS file: {filename}")
    print(f"Duration: {duration} seconds")
    print(f"Sampling rate: {sampling_rate} Hz")
    print(f"File size: {os.path.getsize(filename)} bytes")

if __name__ == "__main__":
    create_test_tdms_file("../audio_files/test_signal.tdms")