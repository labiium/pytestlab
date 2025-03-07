# Changelog

## [0.1.3] - 2024

### Added
- New DCActiveLoad instrument support
  - Added DCActiveLoadConfig for configuration
  - Added driver for Keysight EL33133A DC Active Load
  - Added support in AutoInstrument class
  - Added schema and profile for DC Active Load instruments

- New configuration and environment files
  - Added `.env` file with AWS and GCP project configurations
  - Added `lm.yaml` for model configuration

- Enhanced testing
  - Added comprehensive test scripts for AWG and Multimeter instruments
  - Improved oscilloscope test script with detailed functionality testing

### Changed
- Improved Multimeter functionality
  - Added MultimeterConfigResult data class
  - Enhanced configuration retrieval and display
  - Added structured configuration support

- Enhanced WaveformGenerator capabilities
  - Added WaveformConfigResult data class
  - Added support for impedance and voltage limits
  - Improved phase and symmetry control
  - Enhanced error handling and validation

- Updated Experiment and Database handling
  - Improved error handling and validation in Database class
  - Enhanced Experiment class with better data handling
  - Added support for structured configuration results
  - Improved documentation and type hints

### Modified
- Updated curly.yaml configuration
  - Refined documentation ignore paths
  - Added new instruments section
  - Modified experiment configuration

- Updated example Jupyter notebook
  - Simplified instrument configuration examples
  - Removed unused instrument instances

### Added Examples
- Added new example scripts:
  - example_database.py: Comprehensive database usage example
  - example_experiment.py: Detailed experiment configuration example

### Updated Dependencies
- Added support for Python 3.12 in setup.py
