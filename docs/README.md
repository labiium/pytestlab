# PyTestLab Documentation

This directory contains the source files and build system for PyTestLab's documentation.

## Quick Start

### Building Documentation

The easiest way to build the documentation is using the provided build script:

```bash
# Build with clean output (recommended)
./build.sh

# Build with verbose output for debugging
./build.sh --verbose
```

### Manual Build

If you prefer to build manually:

```bash
# Set environment variable to suppress Jupyter warnings
export JUPYTER_PLATFORM_DIRS=1

# Build the documentation
mkdocs build
```

### Development Server

For live editing and preview during development:

```bash
# Start development server with auto-reload
mkdocs serve

# Or with the environment variable
JUPYTER_PLATFORM_DIRS=1 mkdocs serve
```

The development server will be available at `http://localhost:8000`.

## Directory Structure

```
docs/
├── README.md              # This file
├── build.sh              # Build script with warning suppression
├── mkdocs.yml            # MkDocs configuration
├── en/                   # English documentation source
│   ├── index.md          # Homepage
│   ├── api/              # API reference
│   ├── tutorials/        # Tutorial notebooks
│   ├── user_guide/       # User guides
│   └── profiles/         # Instrument profile documentation
├── themes/               # Custom theme files
└── site/                 # Generated documentation (git-ignored)
```

## Configuration

The documentation is configured through `mkdocs.yml`. Key features:

- **Multi-language support** (currently English only, French placeholder)
- **API documentation** generated from docstrings using mkdocstrings
- **Jupyter notebook support** for interactive tutorials
- **Custom theme** (labiium_photon)
- **Search functionality** with advanced separator handling

## Content Guidelines

### API Documentation

API documentation is auto-generated from Python docstrings. To ensure proper documentation:

1. Use proper type annotations in function signatures
2. Follow Google-style docstring format
3. Include examples in docstrings where helpful

### Tutorials

Tutorials are written as Jupyter notebooks in `en/tutorials/`. Best practices:

1. Include clear explanations and context
2. Use realistic examples
3. Test notebooks before committing
4. Keep cell outputs for better user experience

### User Guides

User guides in `en/user_guide/` should:

1. Focus on practical usage scenarios
2. Include code examples
3. Link to relevant API documentation
4. Use clear headings and structure

## Common Issues

### Jupyter Deprecation Warning

If you see Jupyter deprecation warnings during build, use the build script or set:
```bash
export JUPYTER_PLATFORM_DIRS=1
```

### Missing Type Annotations

griffe warnings about missing type annotations indicate functions without proper typing. Add type hints to the source code to resolve these.

### Broken Links

Check for broken internal links by reviewing the build output. Common issues:
- Incorrect anchor references
- Missing API documentation entries
- Typos in file paths

### Build Failures

For build failures:
1. Run `./build.sh --verbose` for detailed output
2. Check that all referenced modules can be imported
3. Verify mkdocstrings can find all API references

## Dependencies

The documentation build requires:

- **mkdocs** - Static site generator
- **mkdocs-material** (or custom theme)
- **mkdocstrings** - API documentation from docstrings
- **mkdocs-jupyter** - Jupyter notebook support
- **Python packages** - All PyTestLab dependencies for API introspection

Install with:
```bash
pip install mkdocs mkdocstrings mkdocs-jupyter
```

## Deployment

The built documentation in `site/` can be deployed to any static hosting service:

- GitHub Pages
- Netlify
- Vercel
- Traditional web servers

For GitHub Pages deployment:
```bash
mkdocs gh-deploy
```

## Contributing

When contributing to documentation:

1. Test your changes locally with `mkdocs serve`
2. Run a full build with `./build.sh` to check for errors
3. Follow the existing style and structure
4. Update navigation in `mkdocs.yml` if adding new pages
5. Ensure all links work correctly

## Troubleshooting

### Slow Builds

Documentation builds can be slow due to:
- Large notebooks with outputs
- Many API references to process
- Complex dependency imports

Consider using `mkdocs serve` for development to enable incremental builds.

### Memory Issues

For large codebases, mkdocstrings may consume significant memory. If you encounter memory issues:
- Build on a machine with more RAM
- Consider excluding some modules from API docs temporarily
- Use `--verbose` flag to identify problematic modules

### Theme Issues

If using the custom theme:
- Ensure theme files are in the correct location
- Check that all theme dependencies are installed
- Verify theme configuration in `mkdocs.yml`

For more help, see the [MkDocs documentation](https://www.mkdocs.org/) or [mkdocstrings documentation](https://mkdocstrings.github.io/).