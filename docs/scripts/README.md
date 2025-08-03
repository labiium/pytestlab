# PyTestLab Documentation Scripts

This directory contains utility scripts for managing and enhancing PyTestLab's Jupyter notebook documentation.

## 📁 Scripts Overview

### 🔧 `generate_notebook.py`
Professional Jupyter notebook generator that creates consistently styled notebooks with PyTestLab branding.

**Features:**
- Multiple notebook templates (tutorial, example, documentation, guide)
- Professional metadata and structure
- PyTestLab branding and styling
- Automated setup cells with common imports
- Consistent section headers and conclusions

**Usage:**
```bash
# Generate a tutorial notebook
python docs/scripts/generate_notebook.py \
  --type tutorial \
  --title "Getting Started with DMM" \
  --output en/tutorials/dmm_tutorial.ipynb

# Generate an example notebook with custom author
python docs/scripts/generate_notebook.py \
  --type example \
  --title "Oscilloscope Measurements" \
  --output en/tutorials/osc_example.ipynb \
  --author "Your Name"
```

### 🔍 `validate_styling.py`
Comprehensive validation script that ensures notebook styling implementation is correct and complete.

**Features:**
- CSS file structure validation
- JavaScript functionality testing
- MkDocs configuration verification
- Notebook structure compliance
- Accessibility and performance checks

**Usage:**
```bash
# Run basic validation
python docs/scripts/validate_styling.py

# Run comprehensive validation with verbose output
python docs/scripts/validate_styling.py --verbose --check-all

# Validate specific aspects
python docs/scripts/validate_styling.py --validate en/tutorials/
```

### 🛠 `normalize_notebooks.py`
Notebook normalization utility that ensures compliance with current nbformat standards.

**Features:**
- Adds missing cell IDs for nbformat compatibility
- Validates notebook structure
- Creates backup files before modification
- Batch processing of multiple notebooks
- Meaningful ID generation based on content

**Usage:**
```bash
# Normalize all tutorials
python docs/scripts/normalize_notebooks.py --directory en/tutorials/

# Normalize a single notebook
python docs/scripts/normalize_notebooks.py --notebook en/tutorials/example.ipynb

# Validate without modifying
python docs/scripts/normalize_notebooks.py --validate en/tutorials/
```

## 🚀 Quick Start

### Prerequisites
- Python 3.9 or higher
- Required packages: `nbformat`, `pathlib`, `json`
- Access to the PyTestLab docs directory

### Installation
No installation required - scripts are self-contained Python files.

### Common Workflows

**1. Create a new tutorial notebook:**
```bash
cd PyTestLab
python docs/scripts/generate_notebook.py \
  --type tutorial \
  --title "Your Tutorial Title" \
  --output en/tutorials/your_tutorial.ipynb
```

**2. Validate styling implementation:**
```bash
cd PyTestLab/docs
python scripts/validate_styling.py --verbose
```

**3. Normalize existing notebooks:**
```bash
cd PyTestLab/docs
python scripts/normalize_notebooks.py --directory en/tutorials/ --verbose
```

## 📊 Script Dependencies

### External Dependencies
- `nbformat`: For proper notebook handling and validation
- `pathlib`: For cross-platform path operations
- `json`: For notebook JSON manipulation
- `argparse`: For command-line interface

### Internal Dependencies
- PyTestLab documentation structure in `docs/en/`
- CSS files in `docs/en/stylesheets/`
- JavaScript files in `docs/en/js/`
- MkDocs configuration in `docs/mkdocs.yml`

## 🎯 Best Practices

### Notebook Generation
1. Always use descriptive titles and appropriate types
2. Include author information for attribution
3. Test generated notebooks before committing
4. Follow the established naming conventions

### Validation
1. Run validation after any styling changes
2. Address warnings for optimal user experience
3. Test across different browsers and devices
4. Validate accessibility compliance

### Normalization
1. Create backups before running normalization
2. Test notebooks after normalization
3. Validate that all cells have proper structure
4. Ensure metadata is preserved

## 🔧 Troubleshooting

### Common Issues

**"No module named 'nbformat'"**
```bash
pip install nbformat
```

**"Permission denied" errors**
```bash
chmod +x docs/scripts/*.py
```

**"Path not found" errors**
- Ensure you're running scripts from the correct directory
- Check that the docs/en/ structure exists
- Verify file paths in command arguments

### Script-Specific Issues

**generate_notebook.py:**
- Ensure output directory exists or will be created
- Check that notebook type is valid
- Verify all required arguments are provided

**validate_styling.py:**
- Run from PyTestLab/docs directory
- Ensure all CSS and JS files are present
- Check MkDocs configuration is valid

**normalize_notebooks.py:**
- Backup important notebooks before running
- Ensure notebooks are valid JSON
- Check file permissions for writing

## 📈 Performance Tips

1. **Batch Operations**: Use directory-level operations for multiple notebooks
2. **Verbose Mode**: Use `--verbose` for debugging but not in production
3. **Selective Validation**: Use specific validation targets for faster feedback
4. **Backup Strategy**: Always backup before normalization operations

## 🤝 Contributing

When modifying these scripts:

1. **Test Thoroughly**: Validate changes with multiple notebook types
2. **Document Changes**: Update this README and inline documentation
3. **Follow Standards**: Maintain consistent code style and error handling
4. **Add Tests**: Include validation for new features

## 📚 Additional Resources

- [PyTestLab Notebook Styling Guide](../en/user_guide/notebook_styling.md)
- [Jupyter Notebook Format Documentation](https://nbformat.readthedocs.io/)
- [MkDocs Jupyter Plugin](https://github.com/danielfrg/mkdocs-jupyter)
- [PyTestLab Documentation](../en/index.md)

## 📝 License

These scripts are part of PyTestLab and are licensed under the MIT License.
See the project's LICENSE file for full details.