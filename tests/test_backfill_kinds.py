"""#440: `ccx doctor --backfill-kinds` rebuilds `kind_counts` of the routing state from old run records (adds only).
Fake hub, no real CLIs."""
import json

from test_adapters import AdapterEnv

R1, R2 = "claude:sonnet:medium", "codex:gpt-6.1-sol:high"


def att(rung, kind=None):
    a, m, e = rung.split(":")
    return {"agent": a, "model": m, "effort": e, "kind": kind}


class BackfillEnv(AdapterEnv):
    def run_rec(self, rid, attempts, route=None, mode=None, learned="lead", with_mode=True):
        d = self.hub / "ccx" / "runs" / rid
        d.mkdir(parents=True, exist_ok=True)
        rec = {"run_id": rid, "attempts": attempts, "route": route, "learned": learned}
        if with_mode:
            rec["mode"] = mode
        (d / "run.json").write_text(json.dumps(rec), encoding="utf-8")

    def set_state(self, counts, **extra):
        d = self.hub / "ccx"
        d.mkdir(parents=True, exist_ok=True)
        (d / "routing-state.json").write_text(json.dumps({"offsets": {}, "counts": counts, "outcomes": [], **extra}),
                                              encoding="utf-8")

    def state(self):
        return json.loads((self.hub / "ccx" / "routing-state.json").read_text(encoding="utf-8"))

    def backfill(self):
        return self.ccx("doctor", "--backfill-kinds")


class TestBackfill(BackfillEnv):
    def test_rebuilds_kind_counts_from_route_kind_and_mode(self):
        self.set_state({R1: 3, R2: 1})
        self.run_rec("r1", [att(R1)], route={"b": 4, "kind": "read"})
        self.run_rec("r2", [att(R1, "quota"), att(R2)], route={"b": 5, "kind": "code"})   # quota attempt not learned
        self.run_rec("r3", [att(R1)], route={"b": 5}, mode="read")                      # no route.kind: mode -> read
        self.run_rec("r4", [att(R1)], route={"b": 5}, mode="write")                     # mode write -> code
        r = self.backfill()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = self.state()
        self.assertEqual(st["kind_counts"], {"read": {R1: 2}, "code": {R2: 1, R1: 1}})
        self.assertEqual(st["counts"], {R1: 3, R2: 1})                                  # the skill's counts untouched

    def test_missing_fields_stay_unknown(self):
        self.set_state({R1: 4})
        self.run_rec("a", [att(R1)], route={"b": 4})                                     # no kind, mode null
        self.run_rec("b", [att(R1)], route={"b": 4}, with_mode=False)                    # no mode field at all
        self.run_rec("c", [att(R1)], route={"kind": "read"})                             # no b: never learned from
        self.run_rec("d", [att(R1)], route={"b": 4, "kind": "read"}, learned=None)       # not learned
        self.run_rec("e", [{"agent": "claude"}], route={"b": 4, "kind": "read"})        # attempt without a rung
        self.backfill()
        st = self.state()
        self.assertEqual(st.get("kind_counts", {}), {})
        from ccx.learn import kind_history
        self.assertEqual(kind_history(st, ["claude"], "read"), {"kind": 0, "other": 0, "unknown": 4})

    def test_never_exceeds_what_the_skill_counted(self):
        # a corrected verdict is learned twice into counts but only one record exists; and records of runs whose
        # counts were reset must not invent history: kind_counts per rung stays <= counts
        self.set_state({R1: 1})
        self.run_rec("x", [att(R1)], route={"b": 4, "kind": "read"})
        self.run_rec("y", [att(R1)], route={"b": 4, "kind": "code"})
        self.backfill()
        st = self.state()
        self.assertEqual(sum(v.get(R1, 0) for v in st["kind_counts"].values()), 1)

    def test_only_adds_next_to_existing_kind_counts(self):
        self.set_state({R1: 3}, kind_counts={"read": {R1: 1}})
        self.run_rec("x", [att(R1)], route={"b": 4, "kind": "code"})
        self.run_rec("y", [att(R1)], route={"b": 4, "kind": "read"})
        self.backfill()
        st = self.state()
        self.assertEqual(st["kind_counts"]["read"][R1], 1 + 1)
        self.assertEqual(st["kind_counts"]["code"][R1], 1)

    def test_repeat_is_idempotent_and_leaves_run_records_alone(self):
        self.set_state({R1: 2})
        self.run_rec("x", [att(R1)], route={"b": 4, "kind": "read"})
        before = (self.hub / "ccx" / "runs" / "x" / "run.json").read_bytes()
        self.backfill()
        first = self.state()
        out = self.backfill()
        self.assertEqual(self.state(), first)
        self.assertIn("already", out.stdout.lower())
        self.assertEqual((self.hub / "ccx" / "runs" / "x" / "run.json").read_bytes(), before)

    def test_no_state_or_no_runs_is_harmless(self):
        r = self.backfill()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_default_pick_unchanged_without_the_option(self):
        self.set_state({R1: 3})
        self.run_rec("x", [att(R1)], route={"b": 4, "kind": "read"})
        self.ccx("doctor")                                                               # plain doctor does not backfill
        self.assertNotIn("kind_counts", self.state())
        a = self.j("run", "--from", "claude", "--b", "4", "--mode", "read", "--new", "--context", "off", "--no-ab",
                   "--review", "off", "--dry-run", "x")
        self.backfill()
        b = self.j("run", "--from", "claude", "--b", "4", "--mode", "read", "--new", "--context", "off", "--no-ab",
                   "--review", "off", "--dry-run", "x")
        self.assertEqual(a["first_rung"], b["first_rung"])
