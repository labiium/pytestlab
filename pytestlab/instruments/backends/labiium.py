import requests

class VisaInstrument:
    def __init__(self, vid, pid, url="http://lamb-server:8000"):
        self.url = url
        self.vid = self.hex_to_str(vid)
        self.pid = self.hex_to_str(pid)
        self.add()


    def add(self):
        response = requests.post(
            f"{self.url}/add", 
            json={"vendor_id": self.vid, "product_id": self.pid},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
    
    def write(self, command):
        response = requests.post(
            f"{self.url}/instrument/write", 
            json={"vendor_id": self.vid, "product_id": self.pid, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")

    def query(self, command):
        response = requests.post(
            f"{self.url}/instrument/query", 
            json={"vendor_id": self.vid, "product_id": self.pid, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json", 'Accept-Charset': 'utf-8'}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        return response.content.decode('utf-8')
    
    def query_raw(self, command):
        response = requests.post(
            f"{self.url}/instrument/query_raw", 
            json={"vendor_id": self.vid, "product_id": self.pid, "command": command},  # Use the json parameter to ensure the payload is properly encoded as JSON
            headers={"Accept": "application/json"}
            )
        if response.status_code != 200:
            raise Exception(f"{response.text}")
        return response.content
    
    def close(self):
        pass

    def hex_to_str(self, hex_number):
        """
        Convert a hexadecimal number to a string representation without the '0x' prefix.

        Parameters:
        hex_number (int): The hexadecimal number to be converted.

        Returns:
        str: The string representation of the hexadecimal number without the '0x' prefix.
        """
        # Convert the hexadecimal number to a string without the '0x' prefix
        return format(hex_number, 'x')