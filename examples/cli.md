# Command-line examples

Start with the [examples index](QUICKSTART.md), which distinguishes offline
examples from templates for actual instruments. Run commands from the source
checkout unless noted.

```bash
ptl bench ls examples/bench.yaml
ptl bench validate examples/bench.yaml --strict
ptl bench sim examples/bench.yaml
ptl replay run examples/replay_mode/capture_scope.py --session examples/replay_mode/scope_session.yaml
```

The replay fixture contains synthetic scope replies and a binary waveform. Its
strict command sequence rejects queries that do not match the recording. Use
`ptl replay record --help` for capture options. Recording executes your script
using the specified bench, so review it and confirm whether it uses simulation
or a commissioned live station before running it.
