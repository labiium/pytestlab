from __future__ import annotations

import requests
from typing import Optional, Dict, Any

class LambInstrument:
    def __init__(self, model_name: str, serial_number: str, url: str = "http://lamb-server:8000") -> None:
        self.url: str = url
        self.model_name: str = model_name
        self.serial_number: str = serial_number
        self.visa_string: Optional[str] = None
        self.add()


    def add(self) -> None:
        data: Dict[str, str] = {
            "model_name": self.model_name,
            "serial_number": self.serial_number
        }
        response = requests.post(
            f"{self.url}/add",
            json=data,
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        response.raise_for_status() # Will raise an HTTPError if the HTTP request returned an unsuccessful status code
        self.visa_string = response.text
    
    def write(self, command: str) -> None:
        response = requests.post(
            f"{self.url}/instrument/write",
            json={"visa_string": self.visa_string, "command": command},
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        response.raise_for_status()

    def query(self, command: str) -> Optional[str]:
        response = requests.post(
            f"{self.url}/instrument/query",
            json={"visa_string": self.visa_string, "command": command},
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        response.raise_for_status()
        content: str = response.content.decode('utf-8')
        if content.endswith("\n"):
            return content[:-1]
        return content # Return content even if no newline
    
    def query_raw(self, command: str) -> bytes:
        response = requests.post(
            f"{self.url}/instrument/query_raw",
            json={"visa_string": self.visa_string, "command": command},
            headers={"Accept": "application/json"} # No charset needed for raw bytes
            )
        response.raise_for_status()
        return response.content
    
    def close(self) -> None:
        # Placeholder for actual close logic if needed for Lamb backend
        # e.g., informing the lamb-server to release the instrument
        # For now, it does nothing as per original.
        pass