import time

def delay(seconds):
    """A utility function to introduce a delay in seconds."""
    time.sleep(seconds)

def validate_visa_resource(visa_resource):
    """A utility function to validate the VISA resource string format."""
    # Add your custom validation logic here to ensure the correct VISA resource format
    # For example, check if the resource string starts with "TCPIP0::" for LAN communication
    if not visa_resource.startswith("TCPIP0::"):
        raise ValueError("Invalid VISA resource format. Please use TCPIP0::<IP_ADDRESS>::INSTR format for LAN instruments.")

    # Add more validation checks if needed

def check_connection(instrument):
    """A utility function to check if the instrument connection is active."""
    try:
        # Send a *IDN? command to verify the connection with the instrument
        response = instrument._query("*IDN?")
        if response:
            print("Connection to the instrument is active.")
    except Exception as e:
        print(f"Connection to the instrument is not active. Error: {str(e)}")

# Add more utility functions as needed based on your project requirements
