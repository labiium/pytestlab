# Using a prober

PyTestLab represents probers with a profile-driven device API. The profile defines the controller commands, axis units, travel limits, and any readbacks.

## Select a prober in `bench.yaml`

```yaml
bench_name: Prober station

devices:
  prober:
    profile: suss/PA200
    address: GPIB0::1::INSTR
    backend:
      type: lamb
      url: "http://your-lamb-host:8000"
```

Use the address and backend configured for your station. The packaged `suss/PA200` profile expresses X and Y positions in millimetres and converts them to the protocol's micrometre units. Its position response includes X, Y, and Z. Controller wiring, travel limits, and the relationship between controller coordinates and the installed chuck still need to match the actual station. The packaged profile supports absolute and relative XY moves. Its axis bounds are configured position limits, not limits on offsets or automatically detected physical limits.

## Read current position and status

After confirming the bench points at the intended controller, read its position and status:

```bash
export PYTESTLAB_BENCH="$PWD/bench.yaml"
ptl motion position prober --json
ptl motion status prober --json
```

If you want to inspect what the profile declares without connecting, use
`ptl prober capabilities prober --json`.

The profile's status command is an acknowledgement/status field, not proof that a move has physically settled. Do not infer probe contact, chuck vacuum state, or completion from a successful command acknowledgement.

## Use the same bench in Python

Open a session for just the prober to inspect its coordinates. With this profile, the reported position includes X, Y, and Z even though only X and Y are declared as positioning axes.

```python
from pytestlab import Bench

with Bench.open("bench.yaml", aliases={"prober"}, start_experiment=False) as bench:
    print(bench.prober.get_position())
    print(bench.prober.get_status())
```

For a commissioned station, the [prober action reference](../api/prober.md#prober-cli) lists the commands for contact, separation, chuck vacuum, and travel. On the PA200, `move_to_align()` selects the alignment height or preset. Optical alignment requires a separate procedure.

## Relative XY moves

`ptl motion move prober x=OFFSET_MM --relative --units mm` adds the requested
offset to the reported X position and holds Y at its reported position.
Replace `OFFSET_MM` with a value verified for your station. This command
moves hardware. The basis is the controller's same-home position readback;
PyTestLab checks the final coordinates against the profile limits and sends
an absolute move, not a native relative command. An invalid or out-of-bounds
target is rejected before the move command.

Check your reference, clearance, and physical interlocks before moving. The
position read and move are serialized within this PyTestLab process only.
A command acknowledgement does not verify completion, and PA200 does not
support `--wait`.

## Readbacks and completion

Methods such as `get_contact_state()`, `get_vacuum_state()`, and `get_settled_state()` only work when the profile declares a query with an explicit response map. Missing or ambiguous mappings fail instead of guessing the physical state. `--wait` likewise requires a profile-declared completion check.

For a multi-step automated recipe, `preflight_recipe()` can check the
declared actions and mapped contact and settled readbacks without connecting.
PA200 lacks those readbacks. This check is not needed for a single read or
direct action and does not verify the physical state.

For a new controller or station, qualify command framing, coordinate references, travel limits, and readback tokens against its documentation and observed responses before adding them to the profile. For the current LAMB commissioning workflow and its camera checks, see [LAMB station commissioning](lamb-commissioning.md). The generated [prober API reference](../api/prober.md) lists supported actions and CLI details.
