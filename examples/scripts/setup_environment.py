#!/usr/bin/env python3
"""
Setup environment script for bench automation.
This script is called as a pre-experiment hook.
"""

import os
import datetime

def main():
    print("🔧 Setting up experiment environment...")
    
    # Create directories if needed
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Log the experiment start
    timestamp = datetime.datetime.now().isoformat()
    with open("logs/experiment.log", "a") as f:
        f.write(f"{timestamp}: Experiment environment setup complete\n")
    
    print("✅ Environment setup complete")

if __name__ == "__main__":
    main()
