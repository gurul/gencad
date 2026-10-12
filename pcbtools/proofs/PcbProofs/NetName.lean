/-!
# Net-name parsing: `pcbtools/drc.py : net_from_desc`

The Python function, at HEAD 567a1bd1:

```python
def net_from_desc(desc):
    i = desc.find(" [")
    if i < 0:
        return "?"
    j = desc.rfind("] ")
    if j <= i:
        j = len(desc) - 1 if desc.endswith("]") else -1
    if j <= i:
        return "?"
    return desc[i + 2:j]
```

A Python `str` is modelled as `List Char` (a sequence of code points).
`str.find` / `str.rfind` return `-1` on a miss, so they are modelled as `Int`.
-/

namespace NetName

abbrev Str := List Char

/-- Index of the first occurrence of `pat` in `s` (Python `s.find(pat)`, as an
`Option`). -/
def findIdx (pat : Str) : Str → Option Nat
  | [] => if pat.isPrefixOf [] then some 0 else none
  | c :: t => if pat.isPrefixOf (c :: t) then some 0 else (findIdx pat t).map (· + 1)

/-- Index of the last occurrence of `pat` in `s` (Python `s.rfind(pat)`, as an
`Option`). -/
def rfindIdx (pat : Str) : Str → Option Nat
  | [] => if pat.isPrefixOf [] then some 0 else none
  | c :: t =>
    match rfindIdx pat t with
    | some k => some (k + 1)
    | none => if pat.isPrefixOf (c :: t) then some 0 else none

/-- `s.find(pat)`: `-1` on a miss. -/
def pyFind (s pat : Str) : Int :=
  match findIdx pat s with
  | some k => (k : Int)
  | none => -1

/-- `s.rfind(pat)`: `-1` on a miss. -/
def pyRfind (s pat : Str) : Int :=
  match rfindIdx pat s with
  | some k => (k : Int)
  | none => -1

/-- `s.endswith(suf)`. -/
def pyEndsWith (s suf : Str) : Bool := suf.isSuffixOf s

/-- `s[a:b]` for `0 ≤ a` and `0 ≤ b` (the only case `net_from_desc` reaches:
`i ≥ 0` and `j > i`). Python clamps both bounds to `len(s)`, as do
`drop` / `take`; an empty range gives `""`, as `take 0` does. -/
def pySlice (s : Str) (a b : Int) : Str :=
  (s.drop a.toNat).take (b.toNat - a.toNat)

/-- The model of `net_from_desc`, line for line. -/
def netFromDesc (desc : Str) : Str :=
  let i := pyFind desc " [".toList
  if i < 0 then "?".toList else
  let j := pyRfind desc "] ".toList
  let j := if j ≤ i then (if pyEndsWith desc "]".toList then (desc.length : Int) - 1 else -1) else j
  if j ≤ i then "?".toList else pySlice desc (i + 2) j

/-- The rule `net_from_desc` replaced (commit 364770c8, `drc.py:summarize`):
`desc.split("[")[1].split("]")[0] if "[" in desc else "?"`.
`split("[")[1]` is the text between the first and second `[` (or the end);
`split("]")[0]` is that text up to its first `]`. Kept for the regression
check below; nothing proved here uses it. -/
def netFromDescOld (desc : Str) : Str :=
  if '[' ∈ desc then
    ((desc.dropWhile (· ≠ '[')).drop 1 |>.takeWhile (· ≠ '[')).takeWhile (· ≠ ']')
  else "?".toList

/-! ## The exact strings in `pcbtools/tests/test_drc.py` -/

#guard netFromDesc "Pad 1 [/DATA[0]] of R1 on F.Cu".toList == "/DATA[0]".toList
#guard netFromDesc "Pad 2 [GND] of R1 on F.Cu".toList == "GND".toList
#guard netFromDesc "Via [/BUS[3]]".toList == "/BUS[3]".toList
#guard netFromDesc "Board edge".toList == "?".toList
#guard netFromDesc "Pad 1 [/DATA[0]] of R2 on B.Cu".toList == "/DATA[0]".toList

-- The old rule truncates the bracketed net name: the bug the fix closed.
#guard netFromDescOld "Pad 1 [/DATA[0]] of R1 on F.Cu".toList == "/DATA".toList
#guard netFromDescOld "Pad 2 [GND] of R1 on F.Cu".toList == "GND".toList

/-! ## Lemmas about `findIdx` / `rfindIdx` -/

/-- With a two-character pattern `[a, b]`, `a ≠ b`, placed right after `X`,
`find` returns `len X` when the pattern does not occur inside `X`. (`a ≠ b` rules
out an occurrence that straddles the end of `X`.) -/
theorem findIdx_two (a b : Char) (hab : a ≠ b) :
    ∀ (X R : Str), ¬ [a, b] <:+: X → findIdx [a, b] (X ++ a :: b :: R) = some X.length := by
  intro X R
  induction X with
  | nil => intro _; simp [findIdx, List.isPrefixOf]
  | cons x X ih =>
    intro h
    have h' : ¬ [a, b] <:+: X := fun hi => h (List.infix_cons hi)
    have hpre : ([a, b]).isPrefixOf (x :: (X ++ a :: b :: R)) = false := by
      cases hq : ([a, b]).isPrefixOf (x :: (X ++ a :: b :: R)) with
      | false => rfl
      | true =>
        exfalso
        have hp := List.isPrefixOf_iff_prefix.mp hq
        rw [List.prefix_cons_iff] at hp
        rcases hp with hp | ⟨t, ht, htp⟩
        · simp at hp
        · simp only [List.cons.injEq] at ht
          obtain ⟨rfl, rfl⟩ := ht
          cases X with
          | nil =>
            simp only [List.nil_append, List.prefix_cons_iff, List.cons.injEq] at htp
            rcases htp with htp | ⟨t', ⟨hba, _⟩, _⟩
            · simp at htp
            · exact hab hba.symm
          | cons y Y =>
            simp only [List.cons_append, List.prefix_cons_iff, List.cons.injEq] at htp
            rcases htp with htp | ⟨t', ⟨hby, _⟩, _⟩
            · simp at htp
            · subst hby; exact h ⟨[], Y, by simp⟩
    simp only [List.cons_append, findIdx, hpre, ih h', Option.map_some, List.length_cons,
      Bool.false_eq_true, ite_false]

/-- `rfind` is `none` on a string that does not contain the pattern. -/
theorem rfindIdx_none (pat : Str) : ∀ L : Str, ¬ pat <:+: L → rfindIdx pat L = none := by
  intro L
  induction L with
  | nil =>
    intro h
    cases pat with
    | nil => exact absurd List.nil_infix h
    | cons p ps => simp [rfindIdx, List.isPrefixOf]
  | cons c t ih =>
    intro h
    have ht : ¬ pat <:+: t := fun hi => h (List.infix_cons hi)
    have hp : pat.isPrefixOf (c :: t) = false := by
      cases hq : pat.isPrefixOf (c :: t) with
      | false => rfl
      | true => exact absurd (List.IsPrefix.isInfix (List.isPrefixOf_iff_prefix.mp hq)) h
    simp [rfindIdx, ih ht, hp]

/-- Prepending `X` shifts a found `rfind` index by `len X`. -/
theorem rfindIdx_append_some (pat : Str) (Z : Str) (k : Nat) (hz : rfindIdx pat Z = some k) :
    ∀ X : Str, rfindIdx pat (X ++ Z) = some (X.length + k) := by
  intro X
  induction X with
  | nil => simpa using hz
  | cons x X ih =>
    simp only [List.cons_append, rfindIdx, ih, List.length_cons]
    congr 1; omega

/-- If `Z` holds no occurrence, any occurrence in `X ++ Z` starts inside `X`. -/
theorem rfindIdx_append_none (pat : Str) (Z : Str) (hz : rfindIdx pat Z = none) :
    ∀ (X : Str) (k : Nat), rfindIdx pat (X ++ Z) = some k → k < X.length := by
  intro X
  induction X with
  | nil => intro k h; simp [hz] at h
  | cons x X ih =>
    intro k h
    simp only [List.cons_append, rfindIdx] at h
    split at h
    · rename_i k' hk'
      have := ih k' hk'
      simp at h; simp; omega
    · split at h
      · simp at h; simp; omega
      · simp at h

/-- The last occurrence: `[a, b]` at the head and nowhere in the tail `b :: S`. -/
theorem rfindIdx_here (a b : Char) (S : Str) (h : ¬ [a, b] <:+: b :: S) :
    rfindIdx [a, b] (a :: b :: S) = some 0 := by
  rw [rfindIdx.eq_2, rfindIdx_none _ _ h]
  simp [List.isPrefixOf]

/-! ## Preconditions, in user terms -/

/-- `" ["` never straddles the literal `"Pad "` and `P`, except through the
space that ends `"Pad "`; so it is enough that `' ' :: P` has no `" ["`. -/
theorem pad_prefix_clean (P : Str) (hP : ¬ " [".toList <:+: ' ' :: P) :
    ¬ [' ', '['] <:+: "Pad ".toList ++ P := by
  intro h
  have e : "Pad ".toList ++ P = 'P' :: 'a' :: 'd' :: ' ' :: P := by simp
  rw [e] at h
  have hP' : ¬ [' ', '['] <:+: ' ' :: P := by simpa using hP
  rw [List.infix_cons_iff] at h
  rcases h with h | h
  · simp [List.prefix_cons_iff] at h
  rw [List.infix_cons_iff] at h
  rcases h with h | h
  · simp [List.prefix_cons_iff] at h
  rw [List.infix_cons_iff] at h
  rcases h with h | h
  · simp [List.prefix_cons_iff] at h
  exact hP' h

/-- `"] "` cannot straddle the literal `"] of "` and `T`, so the tail after the
closing `"]"` is clean exactly when `T` has no `"] "`. -/
theorem of_suffix_clean (T : Str) (hT : ¬ "] ".toList <:+: T) :
    ¬ [']', ' '] <:+: ' ' :: 'o' :: 'f' :: ' ' :: T := by
  intro h
  simp only [List.infix_cons_iff, List.prefix_cons_iff] at h
  rcases h with h | h | h | h | h <;> simp_all

/-- The suggested simpler condition: no `[` in the pad label. -/
theorem no_bracket_clean (P : Str) (hP : '[' ∉ P) : ¬ " [".toList <:+: ' ' :: P := by
  intro h
  have : '[' ∈ ' ' :: P := h.subset (by simp)
  simp at this
  exact hP this

/-! ## Theorem 1: the pad form `Pad P [N] of T` -/

/-- **Property 1.** For every pad label `P`, net name `N` and suffix `T`:
if `' ' :: P` contains no `" ["` and `T` contains no `"] "`, then
`net_from_desc("Pad " + P + " [" + N + "] of " + T) == N`.
There is **no** precondition on `N`: it may contain `[`, `]`, `" ["` and `"] "`. -/
theorem netFromDesc_pad (P N T : Str)
    (hP : ¬ " [".toList <:+: ' ' :: P) (hT : ¬ "] ".toList <:+: T) :
    netFromDesc ("Pad ".toList ++ P ++ " [".toList ++ N ++ "] of ".toList ++ T) = N := by
  -- name the prefix before " [" and the closing tail
  generalize hX : "Pad ".toList ++ P = X
  have hXc : ¬ [' ', '['] <:+: X := hX ▸ pad_prefix_clean P hP
  have hS := of_suffix_clean T hT
  have hd : X ++ " [".toList ++ N ++ "] of ".toList ++ T
      = X ++ ' ' :: '[' :: (N ++ ']' :: ' ' :: ('o' :: 'f' :: ' ' :: T)) := by simp
  have hd' : X ++ " [".toList ++ N ++ "] of ".toList ++ T
      = (X ++ ' ' :: '[' :: N) ++ (']' :: ' ' :: ('o' :: 'f' :: ' ' :: T)) := by simp
  have hfind : pyFind (X ++ " [".toList ++ N ++ "] of ".toList ++ T) " [".toList = (X.length : Int) := by
    rw [hd]; simp [pyFind, findIdx_two ' ' '[' (by decide) X _ hXc]
  have hr0 := rfindIdx_here ']' ' ' _ hS
  have hrfind : pyRfind (X ++ " [".toList ++ N ++ "] of ".toList ++ T) "] ".toList
      = ((X.length + 2 + N.length : Nat) : Int) := by
    rw [hd']
    have := rfindIdx_append_some _ _ _ hr0 (X ++ ' ' :: '[' :: N)
    simp only [List.length_append, List.length_cons] at this
    simp only [pyRfind, show "] ".toList = [']', ' '] by rfl, this]
    congr 1; omega
  unfold netFromDesc
  simp only [hfind, hrfind]
  have h1 : ¬ ((X.length : Int) < 0) := by omega
  have h2 : ¬ (((X.length + 2 + N.length : Nat) : Int) ≤ (X.length : Int)) := by omega
  simp only [h1, h2, ite_false]
  unfold pySlice
  have e1 : ((X.length : Int) + 2).toNat = X.length + 2 := by omega
  have e2 : (((X.length + 2 + N.length : Nat) : Int)).toNat = X.length + 2 + N.length := by omega
  rw [e1, e2, hd]
  have e3 : X.length + 2 + N.length - (X.length + 2) = N.length := by omega
  rw [e3]
  have e4 : X ++ ' ' :: '[' :: (N ++ ']' :: ' ' :: 'o' :: 'f' :: ' ' :: T)
      = (X ++ [' ', '[']) ++ (N ++ ']' :: ' ' :: 'o' :: 'f' :: ' ' :: T) := by simp
  rw [e4, List.drop_append_of_le_length (by simp), List.drop_of_length_le (by simp)]
  rw [List.nil_append, List.take_append_of_le_length (Nat.le_refl _),
    List.take_of_length_le (Nat.le_refl _)]

/-- The headline instance: a bracketed net survives, whatever the pad and the tail
(subject to the two conditions). -/
theorem netFromDesc_pad_DATA0 (P T : Str) (hP : '[' ∉ P) (hT : ¬ "] ".toList <:+: T) :
    netFromDesc ("Pad ".toList ++ P ++ " [".toList ++ "/DATA[0]".toList ++ "] of ".toList ++ T)
      = "/DATA[0]".toList :=
  netFromDesc_pad P _ T (no_bracket_clean P hP) hT

/-! ## Theorem 1b: the trailing form `H [N]` (e.g. `Via [/BUS[3]]`) -/

/-- **Property 1b.** `net_from_desc(H + " [" + N + "]") == N` when `H` has no
`" ["` and `N` has no `"] "`. Here the precondition **is** on `N`: with no
`"] "` after the name, a `"] "` inside `N` is taken as the closing bracket. -/
theorem netFromDesc_trailing (H N : Str)
    (hH : ¬ " [".toList <:+: H) (hN : ¬ "] ".toList <:+: N) :
    netFromDesc (H ++ " [".toList ++ N ++ "]".toList) = N := by
  have hd : H ++ " [".toList ++ N ++ "]".toList = H ++ ' ' :: '[' :: (N ++ [']']) := by simp
  have hfind : pyFind (H ++ " [".toList ++ N ++ "]".toList) " [".toList = (H.length : Int) := by
    rw [hd]; simp [pyFind, findIdx_two ' ' '[' (by decide) H _ hH]
  -- no "] " at or after the " [" that opens the name
  have hZ : ¬ [']', ' '] <:+: ' ' :: '[' :: (N ++ [']']) := by
    intro h
    simp only [List.infix_cons_iff, List.prefix_cons_iff] at h
    rcases h with h | h | h
    · simp_all
    · simp_all
    · rw [List.infix_concat_iff] at h
      rcases h with h | h
      · obtain ⟨t, ht⟩ := h
        have := congrArg List.getLast? ht
        simp at this
      · exact hN h
  have hrz := rfindIdx_none _ _ hZ
  have hrle : pyRfind (H ++ " [".toList ++ N ++ "]".toList) "] ".toList ≤ (H.length : Int) := by
    rw [hd]; unfold pyRfind
    split
    · rename_i k hk
      have := rfindIdx_append_none _ _ hrz H k hk
      omega
    · omega
  have hend : pyEndsWith (H ++ " [".toList ++ N ++ "]".toList) "]".toList = true := by
    rw [hd]; simp [pyEndsWith, List.isSuffixOf, List.isPrefixOf]
  have hlen : (H ++ " [".toList ++ N ++ "]".toList).length = H.length + 2 + N.length + 1 := by
    simp; omega
  unfold netFromDesc
  simp only [hfind, hrle, hend, ite_true, hlen]
  have h1 : ¬ ((H.length : Int) < 0) := by omega
  have h2 : ¬ (((H.length + 2 + N.length + 1 : Nat) : Int) - 1 ≤ (H.length : Int)) := by omega
  simp only [h1, h2, ite_false]
  unfold pySlice
  have e1 : ((H.length : Int) + 2).toNat = H.length + 2 := by omega
  have e2 : (((H.length + 2 + N.length + 1 : Nat) : Int) - 1).toNat = H.length + 2 + N.length := by
    omega
  rw [e1, e2, hd]
  have e4 : H ++ ' ' :: '[' :: (N ++ [']']) = (H ++ [' ', '[']) ++ (N ++ [']']) := by simp
  rw [e4, List.drop_append_of_le_length (by simp), List.drop_of_length_le (by simp)]
  have e3 : H.length + 2 + N.length - (H.length + 2) = N.length := by omega
  rw [e3, List.nil_append, List.take_append_of_le_length (Nat.le_refl _),
    List.take_of_length_le (Nat.le_refl _)]

/-! ## The preconditions cannot be dropped (counterexamples) -/

-- `' ' :: P` contains `" ["` (here `P = "[x"`, so `"Pad [x"`): find stops early.
#guard netFromDesc ("Pad ".toList ++ "[x".toList ++ " [".toList ++ "N".toList ++ "] of ".toList ++ "R1".toList)
  == "x [N".toList
-- `T` contains `"] "`: rfind runs past the real closing bracket.
#guard netFromDesc ("Pad ".toList ++ "1".toList ++ " [".toList ++ "N".toList ++ "] of ".toList ++ "R] x".toList)
  == "N] of R".toList
-- Trailing form with `"] "` inside `N`: the name is cut at it.
#guard netFromDesc ("Via".toList ++ " [".toList ++ "A] B".toList ++ "]".toList) == "A".toList
-- Pad form with `"] "` and `" ["` inside `N`: still exact (no condition on `N`).
#guard netFromDesc ("Pad ".toList ++ "1".toList ++ " [".toList ++ "A] [B".toList ++ "] of ".toList ++ "R1 on F.Cu".toList)
  == "A] [B".toList

end NetName
