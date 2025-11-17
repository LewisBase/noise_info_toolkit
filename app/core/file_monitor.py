"""
File monitoring module for watching audio files
"""
import os
import time
from pathlib import Path
from typing import Callable, Optional, List
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


class AudioFileHandler(FileSystemEventHandler):
    """Handler for audio file events"""
    def __init__(self, callback: Callable[[str], None], file_extensions: List[str] = None):
        self.callback = callback
        self.file_extensions = file_extensions or [".wav"]
    
    def on_created(self, event):
        """Handle file creation events"""
        if not event.is_directory:
            # Check if file extension matches any of the watched extensions
            for ext in self.file_extensions:
                if event.src_path.endswith(ext):
                    # Add small delay to ensure file is completely written
                    time.sleep(0.1)
                    self.callback(event.src_path)
                    break
    
    def on_modified(self, event):
        """Handle file modification events"""
        pass
        # if not event.is_directory:
        #     # Check if file extension matches any of the watched extensions
        #     for ext in self.file_extensions:
        #         if event.src_path.endswith(ext):
        #             self.callback(event.src_path)
        #             break

class AudioFileMonitor:
    """Monitor audio files in a directory"""
    def __init__(self, watch_directory: str, file_extensions: List[str] = None):
        self.watch_directory = Path(watch_directory)
        self.file_extensions = file_extensions or [".wav"]
        self.observer = Observer()
        self.handler = None
        
    def start_monitoring(self, callback: Callable[[str], None]):
        """Start monitoring the directory for audio files"""
        if not self.watch_directory.exists():
            raise FileNotFoundError(f"Directory {self.watch_directory} does not exist")
        
        self.handler = AudioFileHandler(callback, self.file_extensions)
        self.observer.schedule(self.handler, str(self.watch_directory), recursive=False)
        self.observer.start()
        
    def stop_monitoring(self):
        """Stop monitoring the directory"""
        self.observer.stop()
        self.observer.join()