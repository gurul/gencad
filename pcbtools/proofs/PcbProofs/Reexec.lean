/-!
# Re-exec termination: `pcbtools/kicad_env.py : ensure_pcbnew`

The Python function, at HEAD 567a1bd1 (`kicad_env.py:45-65`):

```python
def ensure_pcbnew():
    try:
        import pcbnew
        os.environ.pop(_REEXEC_MARK, None)
        return __import__("pcbnew")
    except ImportError:
        pass
    if os.environ.get(_REEXEC_MARK) == "1":
        sys.exit(...)
    py = kicad_python()
    if py is None or os.path.realpath(py) == os.path.realpath(sys.executable):
        raise RuntimeError(...)
    os.environ[_REEXEC_MARK] = "1"
    os.execv(py, [py] + sys.argv)
```

`kicad_python()` (`kicad_env.py:31-35`) returns the first non-empty candidate
that exists: `$KICAD_PYTHON`, the macOS bundle path, the Linux path.

## The world

Everything one process cannot change about the next is a fixed `World`:
the filesystem (`exists`, `realpath`), the value of `KICAD_PYTHON` (inherited
unchanged through `execv`), which interpreters can import `pcbnew`, and which
interpreter actually runs when a path is exec'd (`launches`; the identity for a
real binary, something else for a shim or wrapper script). `pcbnew` importability
is a property of the interpreter that runs, keyed by its real path — the
"fixed for a given interpreter" assumption.

A process is its `sys.executable` and the value of `PCBTOOLS_REEXEC` in its
environment (`none` = unset).
-/

namespace Reexec

structure World where
  /-- `os.path.exists` -/
  exists_ : String → Bool
  /-- `os.path.realpath` -/
  realpath : String → String
  /-- `import pcbnew` succeeds under the interpreter whose real path is the argument -/
  importable : String → Bool
  /-- `sys.executable` of the process that `os.execv(p, …)` starts -/
  launches : String → String
  /-- `os.environ.get("KICAD_PYTHON")` -/
  kicadPythonEnv : Option String

structure Proc where
  /-- `sys.executable` -/
  exe : String
  /-- `os.environ.get("PCBTOOLS_REEXEC")` -/
  marker : Option String
deriving DecidableEq, Repr

def macPython : String :=
  "/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3"
def linuxPython : String := "/usr/lib/kicad/bin/python3"

/-- `_CANDIDATE_PYTHONS` (`kicad_env.py:19-23`). -/
def candidates (w : World) : List String :=
  [w.kicadPythonEnv.getD "", macPython, linuxPython]

/-- `kicad_python()` (`kicad_env.py:31-35`). -/
def kicadPython (w : World) : Option String :=
  (candidates w).find? (fun p => p != "" && w.exists_ p)

inductive Action where
  /-- `return pcbnew`; the process continues with `PCBTOOLS_REEXEC` removed -/
  | proceed (after : Proc)
  /-- `sys.exit(...)` (marker already set) -/
  | failExit
  /-- `raise RuntimeError(...)` (no KiCad Python, or it is this interpreter) -/
  | failRaise
  /-- `os.execv(py, …)` with the marker set -/
  | reexec (next : Proc)
deriving DecidableEq, Repr

/-- One call of `ensure_pcbnew` in process `s`. -/
def step (w : World) (s : Proc) : Action :=
  if w.importable (w.realpath s.exe) then
    .proceed { s with marker := none }
  else if s.marker = some "1" then
    .failExit
  else
    match kicadPython w with
    | none => .failRaise
    | some py =>
      if w.realpath py = w.realpath s.exe then .failRaise
      else .reexec { exe := w.launches py, marker := some "1" }

inductive Outcome where
  | proceeded
  | failed
deriving DecidableEq, Repr

/-- Run the chain of processes with `fuel` steps. `none` = fuel ran out (would
be a loop); `some (o, k)` = ended with outcome `o` after `k` re-execs. -/
def run (w : World) : Nat → Proc → Option (Outcome × Nat)
  | 0, _ => none
  | n + 1, s =>
    match step w s with
    | .proceed _ => some (.proceeded, 0)
    | .failExit => some (.failed, 0)
    | .failRaise => some (.failed, 0)
    | .reexec s' => (run w n s').map fun (o, k) => (o, k + 1)

/-! ## Theorems -/

/-- A re-exec always sets the marker. -/
theorem reexec_sets_marker (w : World) (s s' : Proc) (h : step w s = .reexec s') :
    s'.marker = some "1" := by
  unfold step at h
  split at h
  · cases h
  split at h
  · cases h
  split at h
  · cases h
  split at h
  · cases h
  · cases h; rfl

/-- A process that carries the marker never re-execs. -/
theorem marked_never_reexecs (w : World) (s : Proc) (hm : s.marker = some "1") (s' : Proc) :
    step w s ≠ .reexec s' := by
  unfold step
  simp only [hm, ↓reduceIte]
  split <;> simp

/-- The process a re-exec starts never re-execs again. -/
theorem reexec_then_terminal (w : World) (s s' s'' : Proc) (h : step w s = .reexec s') :
    step w s' ≠ .reexec s'' :=
  marked_never_reexecs w s' (reexec_sets_marker w s s' h) s''

/-- **Property 2a (termination, at most one re-exec).** From any start
process, in any world, two steps reach `proceed` or a failure, with at most
one re-exec. -/
theorem terminates_within_two (w : World) (s : Proc) :
    ∃ o k, run w 2 s = some (o, k) ∧ k ≤ 1 := by
  unfold run
  cases h : step w s with
  | proceed _ => exact ⟨_, _, rfl, by decide⟩
  | failExit => exact ⟨_, _, rfl, by decide⟩
  | failRaise => exact ⟨_, _, rfl, by decide⟩
  | reexec s' =>
    simp only
    unfold run
    have hn := fun s'' => reexec_then_terminal w s s' s'' h
    cases h' : step w s' with
    | proceed _ => exact ⟨_, _, rfl, by decide⟩
    | failExit => exact ⟨_, _, rfl, by decide⟩
    | failRaise => exact ⟨_, _, rfl, by decide⟩
    | reexec s'' => exact absurd h' (hn s'')

/-- More fuel never changes the answer: the run with two steps is the run. -/
theorem run_stable (w : World) (s : Proc) (n : Nat) : run w (n + 2) s = run w 2 s := by
  unfold run
  cases h : step w s with
  | proceed _ => rfl
  | failExit => rfl
  | failRaise => rfl
  | reexec s' =>
    simp only
    unfold run
    cases h' : step w s' with
    | proceed _ => rfl
    | failExit => rfl
    | failRaise => rfl
    | reexec s'' => exact absurd h' (reexec_then_terminal w s s' s'' h)

/-- **Property 2b.** If `pcbnew` imports under the current interpreter, the
call proceeds at once, whatever the marker says, and clears the marker. -/
theorem importable_proceeds (w : World) (s : Proc) (h : w.importable (w.realpath s.exe) = true) :
    step w s = .proceed { s with marker := none } := by
  simp [step, h]

theorem importable_runs (w : World) (s : Proc) (n : Nat)
    (h : w.importable (w.realpath s.exe) = true) :
    run w (n + 1) s = some (.proceeded, 0) := by
  simp [run, importable_proceeds w s h]

/-- **Liveness.** From a clean shell, with a resolvable KiCad Python that is not
this interpreter and that can import `pcbnew`, the script re-execs exactly once
and proceeds. -/
theorem reexec_reaches_kicad (w : World) (s : Proc) (py : String)
    (hno : w.importable (w.realpath s.exe) = false)
    (hm : s.marker ≠ some "1")
    (hpy : kicadPython w = some py)
    (hdiff : w.realpath py ≠ w.realpath s.exe)
    (hok : w.importable (w.realpath (w.launches py)) = true) :
    run w 2 s = some (.proceeded, 1) := by
  have h1 : step w s = .reexec { exe := w.launches py, marker := some "1" } := by
    simp [step, hno, hm, hpy, hdiff]
  have h2 := importable_proceeds w { exe := w.launches py, marker := some "1" } hok
  simp only [run, h1, h2, Option.map_some]

/-! ## The marker is load-bearing

Without the `PCBTOOLS_REEXEC` check, the `realpath` comparison alone does not
stop a loop: when `KICAD_PYTHON` names a wrapper (or shim) whose running
interpreter has a different real path and cannot import `pcbnew`, every
process re-execs into the wrapper again. -/

def stepNoMarker (w : World) (s : Proc) : Action :=
  if w.importable (w.realpath s.exe) then .proceed { s with marker := none }
  else
    match kicadPython w with
    | none => .failRaise
    | some py =>
      if w.realpath py = w.realpath s.exe then .failRaise
      else .reexec { exe := w.launches py, marker := some "1" }

def runNoMarker (w : World) : Nat → Proc → Option (Outcome × Nat)
  | 0, _ => none
  | n + 1, s =>
    match stepNoMarker w s with
    | .proceed _ => some (.proceeded, 0)
    | .failExit => some (.failed, 0)
    | .failRaise => some (.failed, 0)
    | .reexec s' => (runNoMarker w n s').map fun (o, k) => (o, k + 1)

/-- `KICAD_PYTHON=/opt/wrap/python3`, a wrapper that runs `/usr/bin/python3`;
no interpreter here can import `pcbnew`. -/
def wrapperWorld : World where
  exists_ := fun p => p == "/opt/wrap/python3"
  realpath := id
  importable := fun _ => false
  launches := fun p => if p == "/opt/wrap/python3" then "/usr/bin/python3" else p
  kicadPythonEnv := some "/opt/wrap/python3"

def start : Proc := { exe := "/usr/bin/python3", marker := none }

-- Without the marker: out of fuel at every depth tried (a loop).
#guard runNoMarker wrapperWorld 50 start == none
-- With the marker (the code as written): one re-exec, then fail.
#guard run wrapperWorld 50 start == some (.failed, 1)

def marked : Proc := { exe := "/usr/bin/python3", marker := some "1" }

theorem noMarker_loops_marked (n : Nat) : runNoMarker wrapperWorld n marked = none := by
  induction n with
  | zero => rfl
  | succ n ih =>
    have h0 : stepNoMarker wrapperWorld marked = .reexec marked := by decide
    simp [runNoMarker, h0, ih]

/-- The same, as a theorem for every fuel. -/
theorem noMarker_loops (n : Nat) : runNoMarker wrapperWorld n start = none := by
  induction n with
  | zero => rfl
  | succ n _ =>
    have h0 : stepNoMarker wrapperWorld start = .reexec marked := by decide
    simp [runNoMarker, h0, noMarker_loops_marked n]

/-! ## A quirk (not a violation)

A shell that already exports `PCBTOOLS_REEXEC=1` makes a script that cannot
import `pcbnew` fail at once, without trying KiCad's Python. -/
#guard step { wrapperWorld with
    exists_ := fun _ => true, kicadPythonEnv := some "/k/python3",
    importable := fun p => p == "/k/python3" }
  { exe := "/usr/bin/python3", marker := some "1" } == .failExit

end Reexec
