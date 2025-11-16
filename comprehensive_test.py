"""
Comprehensive test script for the noise info toolkit
"""
import sys
import os
import time
import json
from pathlib import Path

# Add the project root to the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.database import DatabaseManager
from app.core.tdms_converter import TDMSConverter
from app.core.audio_processor import AudioProcessor
from app.core.background_tasks import AudioProcessingTaskManager

def test_database():
    """Test database functionality"""
    print("Testing database functionality...")
    
    # Create database manager
    db_manager = DatabaseManager()
    
    # Test data
    test_file_path = "test_audio.wav"
    test_metrics = {
        "leq": 65.2,
        "laeq": 63.8,
        "lceq": 67.1,
        "peak_spl": 78.5,
        "kurtosis": 2.8,
        "frequency_spl": {
            "63": 55.2,
            "125": 58.7,
            "250": 62.1,
            "500": 65.3,
            "1000": 63.8,
            "2000": 59.2,
            "4000": 52.7,
            "8000": 48.3,
            "16000": 42.1
        }
    }
    
    # Save test data
    print("Saving test data...")
    result_id = db_manager.save_processing_result(test_file_path, test_metrics)
    print(f"Saved test data with ID: {result_id}")
    
    # Retrieve latest result
    print("Retrieving latest result...")
    latest_result = db_manager.get_latest_result()
    print(f"Latest result: {json.dumps(latest_result, indent=2, ensure_ascii=False)}")
    
    # Retrieve history results
    print("Retrieving history results...")
    history_results = db_manager.get_history_results(limit=5)
    print(f"History results count: {len(history_results)}")
    
    print("Database test completed successfully!")
    return True

def test_tdms_converter():
    """Test TDMS converter functionality"""
    print("Testing TDMS converter functionality...")
    
    # Create converter
    converter = TDMSConverter()
    
    # Test creating a temporary file name
    temp_file_path = converter.convert_tdms_to_wav.__defaults__[0] if converter.convert_tdms_to_wav.__defaults__ else None
    print(f"Default WAV file path pattern: {temp_file_path}")
    
    print("TDMS converter test completed!")
    return True

def test_task_manager():
    """Test task manager functionality"""
    print("Testing task manager functionality...")
    
    # Create database manager
    db_manager = DatabaseManager()
    
    # Create task manager
    task_manager = AudioProcessingTaskManager("./test_audio_files", db_manager)
    
    print(f"Task manager created with watch directory: {task_manager.watch_directory}")
    print(f"Audio monitor extensions: {task_manager.audio_monitor.file_extensions}")
    
    print("Task manager test completed!")
    return True

def main():
    """Main test function"""
    print("Starting comprehensive test of noise info toolkit...")
    
    try:
        # Run all tests
        test_database()
        print()
        
        test_tdms_converter()
        print()
        
        test_task_manager()
        print()
        
        print("All tests completed successfully!")
        return True
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)