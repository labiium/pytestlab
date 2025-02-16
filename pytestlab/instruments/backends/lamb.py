import requests

class LambInstrument:
    def __init__(self, model_name, serial_number, url="http://lamb-server:8000"):
        self.url = url
        self.model_name = model_name
        self.serial_number = serial_number
        self.visa_string = None
        self.add()


    def add(self):
        data = {
            "model_name": self.model_name,
            "serial_number": self.serial_number
        }
        response = requests.post(
            f"{self.url}/add", 
            json=data,  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        else:
            self.visa_string = response.text
    
    def write(self, command):
        response = requests.post(
            f"{self.url}/instrument/write", 
            json={"visa_string": self.visa_string, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")

    def query(self, command):
        response = requests.post(
            f"{self.url}/instrument/query", 
            json={"visa_string": self.visa_string, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        content = response.content.decode('utf-8')
        if content.endswith("\n"):
            return content[:-1]
    
    def query_raw(self, command):
        response = requests.post(
            f"{self.url}/instrument/query_raw", 
            json={"visa_string": self.visa_string, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json"}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        return response.content
    
    def close(self):
        pass