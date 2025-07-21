#!/usr/bin/env python3
"""Test script to verify the sim backend migration was successful."""

import sys
import tempfile
import yaml
import asyncio
sys.path.insert(0, '.')

from pytestlab.instruments import AutoInstrument

async def test_sim_backend_migration():
    """Test that the new SimBackend works correctly."""
    
    try:
        # Test creating the backend directly
        print("🧪 Creating SimBackend directly...")
        from pytestlab.instruments.backends.sim_backend import SimBackend
        
        # Create a minimal test profile 
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            test_profile = {
                "simulation": {
                    "scpi": {
                        "*IDN?": "PyTestLab,SimBackend,TEST001,1.0",
                        "TEST:QUERY?": "42"
                    }
                }
            }
            yaml.dump(test_profile, f)
            profile_path = f.name
        
        # Test backend creation
        backend = SimBackend(profile_path=profile_path, model="TestModel", timeout_ms=5000)
        print("✅ SimBackend created successfully")
        
        # Test basic functionality
        await backend.connect()
        print("✅ Backend connected")
        
        idn = await backend.query("*IDN?")
        print(f"📋 IDN Response: {idn}")
        assert idn == "PyTestLab,SimBackend,TEST001,1.0", f"Unexpected response: {idn}"
        
        test_response = await backend.query("TEST:QUERY?")
        print(f"📊 Test Query Response: {test_response}")
        assert test_response == "42", f"Unexpected response: {test_response}"
        
        await backend.close()
        print("✅ Backend cleanup successful")
        
        print("🎉 SimBackend migration verification successful!")
        return True
        
    except Exception as e:
        print(f"❌ Migration verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_sim_backend_migration())
    sys.exit(0 if success else 1)
