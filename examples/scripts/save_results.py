#!/usr/bin/env python3
"""
Save results script for bench automation.
This script is called as a post-experiment hook.
"""

import datetime
import json
import os

def main():
    print("💾 Saving experiment results...")
    
    # Create a simple results summary
    results = {
        "timestamp": datetime.datetime.now().isoformat(),
        "status": "completed",
        "data_files": [],
        "notes": "Experiment completed successfully"
    }
    
    # Find any data files that might have been created
    if os.path.exists("data"):
        results["data_files"] = [f for f in os.listdir("data") if f.endswith(('.csv', '.json', '.txt'))]
    
    # Save results summary
    os.makedirs("results", exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = f"results/experiment_{timestamp}.json"
    
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    
    # Log the experiment completion
    with open("logs/experiment.log", "a") as f:
        f.write(f"{results['timestamp']}: Experiment completed, results saved to {results_file}\n")
    
    print(f"✅ Results saved to {results_file}")

if __name__ == "__main__":
    main()
