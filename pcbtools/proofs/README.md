# pcbtools proofs (Lean 4)

Machine-checked proofs of two properties of `pcbtools`, at gencad commit
`567a1bd1`. Core Lean 4.34.1 only; no Mathlib.

## Check

```sh
cd pcbtools/proofs
~/.elan/bin/lake build
```

The build fails if a proof or a `#guard` fails. It also prints `#print axioms`
for each main theorem. Each one must list only `propext`, `Classical.choice` and
`Quot.sound`, and never `sorryAx`.

## What is proved

### 1. Net-name parsing: `drc.py:net_from_desc`

`PcbProofs/NetName.lean` models Python `str` as `List Char`. It models `find` and
`rfind` as `Int`, with `-1` for "not found", and copies each line of the function.

- **`netFromDesc_pad`**: for all `P N T`, if `' ' :: P` does not contain `" ["`
  and `T` does not contain `"] "`, then
  `netFromDesc ("Pad " ++ P ++ " [" ++ N ++ "] of " ++ T) = N`.
  **There is no condition on `N`.** `N` can contain `[`, `]`, `" ["` and `"] "`.
  The first `" ["` is fixed by the prefix, and the last `"] "` is fixed by
  `"] of "`.
- **`netFromDesc_pad_DATA0`**: the simpler form of the above, with
  `'[' ∉ P` as the condition and `N = "/DATA[0]"`.
- **`netFromDesc_trailing`**: if `H` does not contain `" ["` and `N` does not
  contain `"] "`, then `netFromDesc (H ++ " [" ++ N ++ "]") = N`. This covers
  the `Via [/BUS[3]]` form. **This form has a condition on `N`.** Nothing comes
  after the name, so if `N` contains `"] "`, the function takes that `"] "` as
  the closing bracket.
- `#guard`: every exact string in `tests/test_drc.py` gives the result the test
  expects.
- `#guard` counterexamples: each condition is necessary in the sense that
  dropping it produces a wrong result for at least one input:
  `P = "[x"` gives `"x [N"`, `T = "R] x"` gives `"N] of R"`, and in the
  trailing form `N = "A] B"` gives `"A"`. A positive case shows that a pad-form
  name `N = "A] [B"` comes back exactly. This is a witness for each condition. It
  is not a proof that the conditions are the weakest possible (no iff theorem).
- `netFromDescOld` models the replaced rule
  `desc.split("[")[1].split("]")[0]`. A `#guard` records that it returns
  `"/DATA"` for the `/DATA[0]` test string.

### 2. Re-exec termination: `kicad_env.py:ensure_pcbnew`

`PcbProofs/Reexec.lean` models one call as `step : World → Proc → Action`, where
the actions are `proceed`, `failExit`, `failRaise` and `reexec`. A `Proc` holds
`sys.executable` and the value of `PCBTOOLS_REEXEC`. The `World` holds the
following, and none of them change across `execv`:

- the filesystem (`exists`, `realpath`)
- `KICAD_PYTHON`
- which interpreters can import `pcbnew`, keyed by real path
- `launches p`: the interpreter that actually runs when `p` is exec'd. This
  lets a wrapper or shim run a different interpreter.

`run w n s` runs the chain of processes with fuel `n`.

- **`terminates_within_two`**: for every world and every start process,
  `run w 2 s = some (o, k)` with `k ≤ 1`.
- **`run_stable`**: `run w (n+2) s = run w 2 s`. More fuel gives the same
  result, so the chain cannot loop.
- **`reexec_then_terminal`**: the process that a re-exec starts never re-execs.
- **`importable_proceeds`** / **`importable_runs`**: if `pcbnew` imports under
  the current interpreter, the call proceeds at once and clears the marker,
  whatever the marker's value was.
- **`reexec_reaches_kicad`**: start from a clean shell. Assume that a KiCad
  Python resolves, that it is not this interpreter, and that it can import
  `pcbnew`. Then the run does exactly one re-exec and then proceeds.
- **`noMarker_loops`**: the marker is necessary. If you remove the
  `PCBTOOLS_REEXEC` check, a world where `KICAD_PYTHON` names a wrapper that runs
  `/usr/bin/python3` loops for every amount of fuel. The `realpath` check alone
  does not stop it.

## Correspondence

| Lean | Python |
|---|---|
| `NetName.netFromDesc` | `pcbtools/drc.py:net_from_desc:39-52` |
| `NetName.pyFind` (`findIdx`) | `desc.find(" [")`, `drc.py:44` |
| `NetName.pyRfind` (`rfindIdx`) | `desc.rfind("] ")`, `drc.py:47` |
| `NetName.pyEndsWith`, `desc.length - 1` | `drc.py:49` |
| `NetName.pySlice` | `desc[i + 2:j]`, `drc.py:52` |
| `NetName.netFromDescOld` | old rule in `summarize`, commit `364770c8` |
| `Reexec.step` | `pcbtools/kicad_env.py:ensure_pcbnew:45-65` |
| `step`, branch 1 (`proceed`, marker cleared) | `kicad_env.py:47-50` |
| `step`, branch 2 (`failExit`) | `kicad_env.py:53-59` |
| `step`, branch 3 (`failRaise`) | `kicad_env.py:60-63` |
| `step`, branch 4 (`reexec`, marker `"1"`) | `kicad_env.py:64-65` |
| `Reexec.kicadPython`, `candidates` | `kicad_env.py:kicad_python:31-35`, `_CANDIDATE_PYTHONS:19-23` |
| `Proc.marker` | `os.environ["PCBTOOLS_REEXEC"]`, `kicad_env.py:17` |

## Modelling gaps

- **Strings.** A Lean `Char` is a Unicode scalar value. A Python `str` can also
  hold lone surrogates, for example from `json` with `"\ud800"`. These do not
  occur in KiCad descriptions.
- **Slicing.** `pySlice` models only non-negative bounds. `net_from_desc` only
  reaches `desc[i+2:j]` when `0 ≤ i < j`.
- **The model is not derived from the Python.** The correspondence between the
  model and the Python is checked by reading the code and by tests, not by a
  proof. A differential run compared the model with the real Python function on
  7007 generated strings and found no differences.
- **The pad-form conditions in real KiCad output.** `P` is a pad number and `T`
  is `"<ref> on <layer>"`. KiCad pad numbers are free text, and layer names can
  be renamed by the user, so a `[` or a `"] "` can occur there. If one does, the
  function returns a wrong name. It does not loop or crash.
- **The trailing-form condition in real KiCad output.** This form fails only if
  a net name contains `"] "`. We did not check whether KiCad lets a label
  contain a space after `]`.
- **Constant world.** The model assumes that `KICAD_PYTHON`, the filesystem and
  `pcbnew` importability stay the same between the process and the process that
  it re-execs. It also assumes that the script does not change the environment
  before it calls `ensure_pcbnew`.
- **Failures that are not modelled.** These fail sooner, so they cannot make the
  chain loop:
  - `import pcbnew` raises an error other than `ImportError`.
  - `execv` raises `OSError`.
  - A caller catches the `RuntimeError`.
- **Side effects.** A re-exec runs the script again from the start, so any work
  done before `ensure_pcbnew` runs twice. See the comment at
  `jlc_export.py:64`. This is not modelled.
- **Quirk (proved by `#guard`, not a bug in the property).** A shell that
  already exports `PCBTOOLS_REEXEC=1` makes a script that cannot import `pcbnew`
  stop at once with `failExit`. It does not try KiCad's Python first.
