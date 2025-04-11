# filepath: /home/remote/pytestlab/tests/instruments/test_psu.py
"""
Real Instrument Sanity Test for Keysight EDU36311A Power Supply

This script exercises key functionalities of the PowerSupply instrument class:
    - Query the instrument ID.
    - Get the current configuration of all channels.
    - Set voltage for different channels.
    - Set current for different channels.
    - Turn on/off the output for specific channels.
    - Turn on/off the display.
    - Test error handling.

Before running, ensure that your PowerSupplyConfig settings match your Keysight EDU36311A instrument.
"""

import time
from pytestlab.instruments import AutoInstrument

def main():
        # --- Instrument Instantiation ---
        print("Instantiating Power Supply from configuration...")
        psu = AutoInstrument.from_config("keysight/EDU36311A")
        
        # --- Instrument Identification ---
        idn = psu.id()
        print("Instrument ID:", idn)
        
        # --- Get Initial Configuration ---
        print("\n[1] Getting initial configuration...")
        initial_config = psu.get_configuration()
        print("Initial configuration:")
        for channel, config in initial_config.items():
                print(f"Channel {channel}: Voltage={config.voltage}V, Current={config.current}A, State={config.state}")
        
        # --- Set Voltage for Each Channel ---
        print("\n[2] Setting voltage for each channel...")
        psu.set_voltage(1, 1.5)  # Set channel 1 to 1.5V
        psu.set_voltage(2, 2.5)  # Set channel 2 to 2.5V
        psu.set_voltage(3, 3.3)  # Set channel 3 to 3.3V
        time.sleep(0.5)
        
        # --- Set Current for Each Channel ---
        print("\n[3] Setting current for each channel...")
        psu.set_current(1, 0.1)  # Set channel 1 to 0.1A
        psu.set_current(2, 0.2)  # Set channel 2 to 0.2A
        psu.set_current(3, 0.3)  # Set channel 3 to 0.3A
        time.sleep(0.5)
        
        # --- Enable Output for Each Channel ---
        print("\n[4] Enabling output for each channel individually...")
        psu.output(1, True)
        time.sleep(0.5)
        psu.output(2, True)
        time.sleep(0.5)
        psu.output(3, True)
        time.sleep(0.5)
        
        # --- Get Current Configuration ---
        print("\n[5] Getting updated configuration...")
        updated_config = psu.get_configuration()
        print("Updated configuration after enabling outputs:")
        for channel, config in updated_config.items():
                print(f"Channel {channel}: Voltage={config.voltage}V, Current={config.current}A, State={config.state}")
        
        # --- Enable Output for Multiple Channels at Once ---
        print("\n[6] Turning off all channels at once...")
        psu.output([1, 2, 3], False)
        time.sleep(0.5)
        
        # --- Display Control ---
        print("\n[7] Testing display control...")
        print("Turning display off...")
        psu.display(False)
        time.sleep(2)
        print("Turning display back on...")
        psu.display(True)
        time.sleep(0.5)
        
        # --- Final Configuration ---
        print("\n[8] Getting final configuration...")
        final_config = psu.get_configuration()
        print("Final configuration:")
        for channel, config in final_config.items():
                print(f"Channel {channel}: Voltage={config.voltage}V, Current={config.current}A, State={config.state}")
        
        print("\nPower Supply sanity test completed.")

if __name__ == "__main__":
        main()