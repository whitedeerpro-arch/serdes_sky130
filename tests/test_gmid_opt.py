"""Unit and integration tests for serdes_flow.gmid and serdes_flow.opt (zero ngspice)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from scipy.optimize import minimize

from serdes_flow import gmid, opt
from serdes_flow.corners import STRESS


# ===================================================================== gmid.py
class TestGmIdToolkit:
    def test_synthetic_ekv_physics_and_corner_ordering(self):
        tbl = gmid.synthetic_ekv_table(
            device_models=("nfet_01v8", "nfet_01v8_lvt", "pfet_01v8", "pfet_01v8_lvt"),
            corners=("ss", "tt", "ff"),
            temps_c=(27.0,),
            vds_list=(0.45, 0.9, 1.35),
        )
        # Peak gm/ID in weak inversion should be realistic for SKY130 (~22..32 S/A at 27 C).
        c_tt = tbl.get("nfet_01v8", "tt", 27.0, 0.9, 0.15)
        assert 22.0 <= float(np.max(c_tt.gm_id)) <= 32.0

        # LVT has lower Vth than SVT.
        c_lvt = tbl.get("nfet_01v8_lvt", "tt", 27.0, 0.9, 0.15)
        assert float(c_lvt.vth_v[0]) < float(c_tt.vth_v[0]) - 0.08

        # pfet_01v8_lvt starts at L = 0.35 um (SKY130 PDK bin floor).
        pfet_lvt_ls = sorted({k[4] for k in tbl.keys() if k[0] == "sky130_fd_pr__pfet_01v8_lvt"})
        assert pfet_lvt_ls[0] == pytest.approx(0.35)

        # Longer L increases intrinsic gain gm/gds and reduces fT at fixed gm/ID.
        op_short = tbl.lookup(12.0, 0.15, device_model="nfet_01v8", corner="tt", temp_c=27.0, vds_v=0.9)
        op_long = tbl.lookup(12.0, 1.0, device_model="nfet_01v8", corner="tt", temp_c=27.0, vds_v=0.9)
        assert op_long["gm_gds"] > 3.0 * op_short["gm_gds"]
        assert op_short["ft_hz"] > 5.0 * op_long["ft_hz"]

        # Corner ordering at fixed gm/ID: FF carries higher Id/W than TT than SS.
        op_ss = tbl.lookup(12.0, 0.15, device_model="nfet_01v8", corner="ss", temp_c=27.0, vds_v=0.9)
        op_ff = tbl.lookup(12.0, 0.15, device_model="nfet_01v8", corner="ff", temp_c=27.0, vds_v=0.9)
        assert op_ff["id_w"] > op_tt_id(op_short) > op_ss["id_w"]

    def test_table_roundtrip_json_npz_and_dir(self, tmp_path: Path):
        tbl = gmid.synthetic_ekv_table(
            device_models=("nfet_01v8", "pfet_01v8"),
            corners=("tt",),
            temps_c=(27.0,),
            vds_list=(0.9,),
            l_list=(0.15, 0.5),
        )
        for target in (tmp_path / "card.json", tmp_path / "card.npz", tmp_path / "card_dir"):
            saved = tbl.save(target)
            loaded = gmid.GmIdTable.load(saved)
            assert loaded.keys() == tbl.keys()
            assert loaded.meta["source"] == "synthetic_ekv"
            for k in tbl.keys():
                c_orig = tbl.curves[k]
                c_load = loaded.curves[k]
                for fname in gmid.CURVE_FIELDS:
                    np.testing.assert_allclose(getattr(c_load, fname), getattr(c_orig, fname), rtol=1e-12, atol=0.0)

    def test_size_for_gm_and_size_for_id_accuracy_lt_1pct(self):
        # Generate fine ground-truth table and compare coarse table interpolation against it.
        vgs_coarse = np.linspace(0.05, 1.80, 60)
        tbl_coarse = gmid.synthetic_ekv_table(
            device_models=("nfet_01v8",),
            corners=("tt",),
            temps_c=(27.0,),
            vds_list=(0.45, 0.9, 1.35),
            l_list=(0.15, 0.25, 0.5, 1.0),
            vgs_grid=vgs_coarse,
        )
        # Exact ground truth at intermediate (vds=0.675, l=0.35) and on-grid (vds=0.9, l=0.25).
        tbl_fine = gmid.synthetic_ekv_table(
            device_models=("nfet_01v8",),
            corners=("tt",),
            temps_c=(27.0,),
            vds_list=(0.9,),
            l_list=(0.25,),
            vgs_grid=np.linspace(0.05, 1.80, 1751),
        )

        gm_target = 6.0e-3  # 6 mS
        for gmid_target in (8.0, 12.0, 16.0, 20.0):
            res_c = tbl_coarse.size_for_gm(gm_target, gmid_target, 0.25)
            res_f = tbl_fine.size_for_gm(gm_target, gmid_target, 0.25)
            # Tuple unpacking order matches spec: (w_um, id_a, cgg_f, cdd_f, ro_ohm, vdsat_v, vgs_v)
            w_um, id_a, cgg_f, cdd_f, ro_ohm, vdsat_v, vgs_v = res_c
            assert id_a == pytest.approx(gm_target / gmid_target, rel=1e-12)
            assert abs(w_um - res_f.w_um) / res_f.w_um < 0.01
            assert abs(cgg_f - res_f.cgg_f) / res_f.cgg_f < 0.01
            assert abs(cdd_f - res_f.cdd_f) / res_f.cdd_f < 0.01
            assert abs(ro_ohm - res_f.ro_ohm) / res_f.ro_ohm < 0.01
            assert abs(vdsat_v - res_f.vdsat_v) / res_f.vdsat_v < 0.01
            assert abs(vgs_v - res_f.vgs_v) / res_f.vgs_v < 0.01

            # Roundtrip consistency with size_for_id:
            # (w_um, gm_s, cgg_f, cdd_f, ro_ohm, ft_hz, vdsat_v)
            w2, gm2, cgg2, cdd2, ro2, ft2, vdsat2 = tbl_coarse.size_for_id(id_a, gmid_target, 0.25)
            assert w2 == pytest.approx(w_um, rel=1e-12)
            assert gm2 == pytest.approx(gm_target, rel=1e-12)
            assert cgg2 == pytest.approx(cgg_f, rel=1e-12)
            assert cdd2 == pytest.approx(cdd_f, rel=1e-12)
            assert ro2 == pytest.approx(ro_ohm, rel=1e-12)
            assert ft2 == pytest.approx(gm2 / (2.0 * math.pi * cgg2), rel=1e-12)
            assert vdsat2 == pytest.approx(vdsat_v, rel=1e-12)

    def test_snap_sky130_width(self):
        # Below minimum finger width -> clamped to 0.42 um, 1 finger.
        g_small = gmid.snap_sky130_width(0.20)
        assert g_small == (0.42, 1, 0.42)

        # Single finger exact grid snap.
        g_mid = gmid.snap_sky130_width(3.456)
        assert g_mid.nf == 1
        assert g_mid.w_finger == pytest.approx(3.46)
        assert g_mid.w_total == pytest.approx(3.46)

        # Exceeds max finger width (10.0 um) -> splits cleanly into multiple DRC-valid fingers.
        g_wide = gmid.snap_sky130_width(25.0)
        assert g_wide.nf >= 3
        assert 0.42 <= g_wide.w_finger <= 10.0
        assert g_wide.w_total == pytest.approx(g_wide.nf * g_wide.w_finger)
        assert abs(g_wide.w_total - 25.0) <= 0.01

        # Explicit nf respected and finger quantized on 0.01 um grid.
        g_nf = gmid.snap_sky130_width(12.34, nf=4)
        assert g_nf.nf == 4
        assert g_nf.w_finger == pytest.approx(3.08)
        assert g_nf.w_total == pytest.approx(12.32)

        with pytest.raises(ValueError):
            gmid.snap_sky130_width(-1.0)
        with pytest.raises(ValueError):
            gmid.snap_sky130_width(2.0, nf=0)

    def test_build_spice_char_deck_syntax_nmos_and_pmos(self):
        deck_n = gmid.build_spice_char_deck(
            "nfet_01v8",
            "tt",
            temp_c=(-40, 27, 85),
            l_list=(0.15, 0.5),
            vds_list=(0.45, 0.9),
            model_library="/fake/sky130.lib.spice",
        )
        assert '.lib "/fake/sky130.lib.spice" tt' in deck_n
        assert "sky130_fd_pr__nfet_01v8" in deck_n
        assert "l=0.1500" in deck_n and "l=0.5000" in deck_n
        assert "option temp=-40" in deck_n and "option temp=85" in deck_n
        assert "alter Vd dc=0.45" in deck_n and "alter Vd dc=0.9" in deck_n
        assert "set filetype=binary" in deck_n
        assert "@m.xdut0.msky130_fd_pr__nfet_01v8[gm]" in deck_n
        assert "@m.xdut1.msky130_fd_pr__nfet_01v8[cdd]" in deck_n
        assert "Bgp gp 0" not in deck_n
        assert deck_n.strip().endswith(".end")
        assert "@CORNER@" not in deck_n

        deck_p = gmid.build_spice_char_deck(
            "pfet_01v8_lvt",
            "ss",
            temp_c=85.0,
            l_list=(0.35, 1.0),
            vds_list=(0.6,),
            model_library="/fake/sky130.lib.spice",
        )
        assert '.lib "/fake/sky130.lib.spice" ss' in deck_p
        assert "Bgp gp 0 V=-v(g)" in deck_p
        assert "Bdp dp 0 V=-v(d)" in deck_p
        assert "sky130_fd_pr__pfet_01v8_lvt" in deck_p


def op_tt_id(op_dict: dict[str, float]) -> float:
    return op_dict["id_w"]


# ===================================================================== opt.py
class TestParamSpaceAndLHS:
    def test_param_space_transforms_and_snapping(self):
        space = opt.ParamSpace([
            opt.ParamSpec("w_um", 1.0, 40.0, log=True, step=0.05),
            opt.ParamSpec("r_ohm", 100.0, 1000.0, log=False, step=10.0),
            opt.ParamSpec("nf", 1.0, 8.0, log=False, step=1.0),
        ])
        pt = {"w_um": 12.34, "r_ohm": 456.0, "nf": 3.4}
        snapped = space.snap(pt)
        assert snapped["w_um"] == pytest.approx(12.35)
        assert snapped["r_ohm"] == pytest.approx(460.0)
        assert snapped["nf"] == pytest.approx(3.0)
        assert space.contains(snapped)

        u = space.to_unit(snapped)
        assert np.all((u >= 0.0) & (u <= 1.0))
        back = space.from_unit(u, snap=True)
        assert back == snapped
        assert len(space.signature()) == 64

    def test_maximin_lhs_stratification_and_reproducibility(self):
        space = opt.ParamSpace([
            opt.ParamSpec("x1", 0.0, 1.0),
            opt.ParamSpec("x2", 1.0, 100.0, log=True),
            opt.ParamSpec("x3", -5.0, 5.0),
        ])
        n = 16
        u = opt.lhs_unit(space.dim, n, seed=42, candidates=24)
        assert u.shape == (n, 3)
        # Exact 1D Latin Hypercube stratification: one sample in each [k/n, (k+1)/n] bin.
        for j in range(3):
            bins = np.floor(u[:, j] * n).astype(int)
            assert sorted(bins.tolist()) == list(range(n))

        s1 = opt.lhs_sample(space, n, seed=7)
        s2 = opt.lhs_sample(space, n, seed=7)
        assert s1 == s2


class TestGaussianProcess:
    def test_gp_r2_gt_098_on_smooth_nonlinear_function(self):
        def fn(X: np.ndarray) -> np.ndarray:
            x1, x2 = X[:, 0], X[:, 1]
            return np.sin(2.5 * x1) + 0.6 * np.cos(3.0 * x2) + 0.8 * (x1 - 0.5) * (x2 - 0.5)

        X_train = opt.lhs_unit(2, 32, seed=11)
        y_train = fn(X_train)

        gp = opt.GaussianProcess(ard=True, seed=0).fit(X_train, y_train)

        grid = np.linspace(0.05, 0.95, 12)
        g1, g2 = np.meshgrid(grid, grid)
        X_test = np.column_stack([g1.ravel(), g2.ravel()])
        y_true = fn(X_test)
        y_pred, y_std = gp.predict(X_test, return_std=True)

        ss_res = float(np.sum((y_true - y_pred) ** 2))
        ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
        r2 = 1.0 - ss_res / ss_tot
        assert r2 > 0.985

        # Posterior std at training points must be much smaller than at far test points.
        _, train_std = gp.predict(X_train, return_std=True)
        assert float(np.mean(train_std)) < 0.25 * float(np.mean(y_std))

    def test_gp_multi_output_and_duplicate_jitter(self):
        X = opt.lhs_unit(2, 20, seed=5)
        X_dup = np.vstack([X, X[:2]])  # Intentional exact duplicates to test Cholesky jitter.
        Y = np.column_stack([
            np.sin(2.0 * X_dup[:, 0]) + X_dup[:, 1],
            (X_dup[:, 0] - 0.3) ** 2 + (X_dup[:, 1] - 0.7) ** 2,
        ])
        gp = opt.GaussianProcess(ard=False, seed=3).fit(X_dup, Y)
        mean, std = gp.predict(X[:5], return_std=True)
        assert mean.shape == (5, 2)
        assert std.shape == (5, 2)
        np.testing.assert_allclose(mean, Y[:5], atol=0.05)


class TestParetoAndCornerMargins:
    def test_pareto_front_exact_with_feasibility(self):
        records = [
            {"id": 0, "metrics": {"power": 1.0, "area": 4.0, "gain": 12.0}},
            {"id": 1, "metrics": {"power": 2.0, "area": 2.0, "gain": 11.0}},
            {"id": 2, "metrics": {"power": 3.0, "area": 1.0, "gain": 10.5}},
            {"id": 3, "metrics": {"power": 2.5, "area": 2.5, "gain": 15.0}},  # dominated by #1
            {"id": 4, "metrics": {"power": 0.5, "area": 0.5, "gain": 8.0}},   # infeasible (gain < 10)
            {"id": 5, "status": "failed", "metrics": {"power": 0.1, "area": 0.1, "gain": 20.0}},
        ]
        front = opt.pareto_front(records, minimize_keys=("power", "area"), constraints={"gain": (10.0, None)})
        assert [r["id"] for r in front] == [0, 1, 2]

    def test_worst_corner_margin_minimax(self):
        corner_metrics = {
            "tt_v1800_t27": {"gain_db": 9.5, "bw_ghz": 3.8, "swing_mv": 410.0},
            "ss_v1650_t85": {"gain_db": 6.2, "bw_ghz": 2.7, "swing_mv": 360.0},
            "ff_v1950_t-40": {"gain_db": 11.0, "bw_ghz": 4.5, "swing_mv": 520.0},
        }
        specs = {
            "gain_db": (6.0, None),
            "bw_ghz": (2.8, None),
            "swing_mv": (320.0, 550.0),
        }
        rep = opt.worst_corner_margin(corner_metrics, specs, normalize=False)
        assert not rep.feasible
        assert rep.worst_corner == "ss_v1650_t85"
        assert rep.worst_metric == "bw_ghz"
        assert rep.worst_margin == pytest.approx(-0.1)

        # Passing case with normalization.
        corner_metrics["ss_v1650_t85"]["bw_ghz"] = 3.08
        rep_ok = opt.worst_corner_margin(corner_metrics, specs, normalize=True)
        assert rep_ok.feasible
        assert rep_ok.worst_corner == "ss_v1650_t85"
        assert rep_ok.worst_metric == "gain_db"
        assert rep_ok.worst_margin == pytest.approx((6.2 - 6.0) / 6.0)


# ===================================================================== Realistic Multi-Corner Analog Benchmark
def _make_diffpair_benchmark():
    """Multi-corner SKY130 CML differential stage sizing benchmark (pure analytic physics).

    Design variables:
        id_ma:  tail current (mA), log-scaled in [0.4, 4.0]
        w_um:   input pair width (um), log-scaled in [4.0, 60.0]
        r_ohm:  load resistance (Ohm), linear in [150.0, 900.0]

    Evaluated across the 6 repo STRESS corners (TT, SS cold/hot, FS cold/hot, FF cold):
        - Minimize nominal power P = 1.8 V * id_ma (mW)
        - Subject to worst-corner specs:
            * min_gain_db    >= 6.0 dB     (20*log10(gm * R_eff))
            * min_bw_ghz     >= 2.8 GHz    (1 / (2*pi*R_eff*(C_load + C_dd(W))))
            * min_headroom_v >= 0.18 V     (VDD - 0.5*Id*R_eff - Vdsat - V_tail)
    """
    corner_factors = {
        # tag: (vdd, mu_scale, r_scale, vtail_min)
        "tt_v1800_t27": (1.80, 1.00, 1.00, 0.20),
        "ss_v1650_t-40": (1.65, 0.95, 1.15, 0.24),
        "ss_v1650_t85": (1.65, 0.78, 1.18, 0.22),
        "fs_v1650_t-40": (1.65, 1.08, 1.12, 0.23),
        "fs_v1650_t85": (1.65, 0.88, 1.14, 0.21),
        "ff_v1950_t-40": (1.95, 1.24, 0.86, 0.18),
    }
    specs = {
        "gain_db": (6.0, None),
        "bw_ghz": (2.8, None),
        "headroom_v": (0.18, None),
    }
    space = opt.ParamSpace([
        opt.ParamSpec("id_ma", 0.4, 4.0, log=True),
        opt.ParamSpec("w_um", 4.0, 60.0, log=True),
        opt.ParamSpec("r_ohm", 150.0, 900.0, log=False),
    ])

    def evaluate(params: dict[str, float]) -> dict[str, float]:
        id_a = params["id_ma"] * 1e-3
        i_branch = 0.5 * id_a
        w_um = params["w_um"]
        r_nom = params["r_ohm"]
        c_load = 65e-15
        c_dd = 1.45e-15 * w_um

        per_corner: dict[str, dict[str, float]] = {}
        for cond in STRESS:
            vdd, mu_sc, r_sc, vtail = corner_factors[cond.tag]
            r_eff = r_nom * r_sc
            # Smooth EKV-like gm and Vdsat from current density (I_branch / W).
            # SKY130 L=0.15 um effective mu*Cox/L ~ 1.6 mA / V^2 per um width.
            k_eff = 1.6e-3 * mu_sc
            id_w = i_branch / w_um
            vov = math.sqrt((2.0 * id_w) / k_eff + 0.04 ** 2)
            gm = (2.0 * i_branch) / (vov + 0.08)
            vdsat = 0.08 + 0.85 * vov
            gain_lin = gm * r_eff
            gain_db = 20.0 * math.log10(max(gain_lin, 1e-6))
            bw_ghz = 1.0 / (2.0 * math.pi * r_eff * (c_load + c_dd)) * 1e-9
            headroom_v = vdd - i_branch * r_eff - vdsat - vtail
            per_corner[cond.tag] = {
                "gain_db": gain_db,
                "bw_ghz": bw_ghz,
                "headroom_v": headroom_v,
            }

        rep = opt.worst_corner_margin(per_corner, specs, normalize=False)
        return {
            "power_mw": 1.8 * params["id_ma"],
            "min_gain_db": min(m["gain_db"] for m in per_corner.values()),
            "min_bw_ghz": min(m["bw_ghz"] for m in per_corner.values()),
            "min_headroom_v": min(m["headroom_v"] for m in per_corner.values()),
            "worst_margin": rep.worst_margin,
        }

    constraints = {
        "min_gain_db": (6.0, None),
        "min_bw_ghz": (2.8, None),
        "min_headroom_v": (0.18, None),
    }
    return space, constraints, evaluate


def _exact_benchmark_optimum(space: opt.ParamSpace, constraints, evaluate) -> float:
    """Reference global optimum computed independently via dense multi-start SLSQP."""
    specs = opt.normalize_constraints(constraints)
    best_p = float("inf")
    inits = opt.lhs_unit(space.dim, 16, seed=99)
    for u0 in inits:
        def obj(u):
            return evaluate(space.from_unit(u, snap=False))["power_mw"]

        cons = [
            {
                "type": "ineq",
                "fun": lambda u, s=s: s.margin(evaluate(space.from_unit(u, snap=False))[s.key]),
            }
            for s in specs
        ]
        res = minimize(obj, u0, method="SLSQP", bounds=[(0.0, 1.0)] * space.dim, constraints=cons)
        m = evaluate(space.from_unit(np.clip(res.x, 0.0, 1.0), snap=False))
        if all(s.is_satisfied(m[s.key], tol=1e-5) for s in specs) and m["power_mw"] < best_p:
            best_p = m["power_mw"]
    return best_p


class TestOptCampaignAndPolish:
    def test_constrained_bo_converges_lt_1pct_on_multicorner_diffpair(self, tmp_path: Path):
        space, constraints, evaluate = _make_diffpair_benchmark()
        true_opt_mw = _exact_benchmark_optimum(space, constraints, evaluate)
        assert math.isfinite(true_opt_mw) and 0.7 < true_opt_mw < 7.2

        camp = opt.OptCampaign(
            tmp_path / "diffpair_bo",
            space,
            objective_key="power_mw",
            constraints=constraints,
            minimize_obj=True,
        )
        # Parallel 4-worker batch BO + local Powell polish.
        res = camp.run(
            eval_batch_fn=lambda batch: [evaluate(pt) for pt in batch],
            n_trials=28,
            batch_size=4,
            init_points=8,
            seed=12,
            polish=True,
            polish_method="Powell",
            polish_evals=40,
        )

        assert res.best_trial is not None
        assert res.best_trial.feasible
        found_mw = float(res.best_trial.metrics["power_mw"])
        rel_err = abs(found_mw - true_opt_mw) / true_opt_mw
        assert rel_err < 0.01, f"found={found_mw:.4f} mW vs true={true_opt_mw:.4f} mW (err={rel_err:.2%})"

    def test_crash_resume_idempotency_and_config_hash_guard(self, tmp_path: Path):
        space, constraints, evaluate = _make_diffpair_benchmark()
        camp_dir = tmp_path / "resumable_camp"

        calls_phase1 = 0

        def eval_phase1(pt: dict[str, float]) -> dict[str, float]:
            nonlocal calls_phase1
            calls_phase1 += 1
            return evaluate(pt)

        camp1 = opt.OptCampaign(camp_dir, space, "power_mw", constraints)
        camp1.run(eval_phase1, n_trials=8, batch_size=4, init_points=8, seed=5)
        assert calls_phase1 == 8
        assert len(camp1.trials) == 8

        # Simulate host reboot mid-write: append a truncated partial JSON line to trials.jsonl.
        with (camp_dir / "trials.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('{"trial_id": 8, "input_sha256": "truncated')

        # Re-opening with a modified ParamSpace must be rejected by config SHA-256 check.
        bad_space = opt.ParamSpace([
            opt.ParamSpec("id_ma", 0.5, 4.0, log=True),
            opt.ParamSpec("w_um", 4.0, 60.0, log=True),
            opt.ParamSpec("r_ohm", 150.0, 900.0, log=False),
        ])
        with pytest.raises(ValueError, match="config mismatch"):
            opt.OptCampaign(camp_dir, bad_space, "power_mw", constraints)

        # Resume with matching config: recovers all 8 trials cleanly and evaluates only 8 new ones.
        calls_phase2 = 0

        def eval_phase2(pt: dict[str, float]) -> dict[str, float]:
            nonlocal calls_phase2
            calls_phase2 += 1
            return evaluate(pt)

        camp2 = opt.OptCampaign(camp_dir, space, "power_mw", constraints)
        assert len(camp2.trials) == 8
        first_eight_hashes = [t.input_sha256 for t in camp2.trials]

        camp2.run(eval_phase2, n_trials=16, batch_size=4, init_points=8, seed=5)
        assert calls_phase2 == 8
        assert len(camp2.trials) == 16
        assert [t.input_sha256 for t in camp2.trials[:8]] == first_eight_hashes
        assert len({t.input_sha256 for t in camp2.trials}) == 16

        # Recording an already-present parameter dict is idempotent (no duplicate appended).
        dup = camp2.record(camp2.trials[0].params, camp2.trials[0].metrics)
        assert dup.trial_id == 0
        assert len(camp2.trials) == 16

    def test_polish_local_nelder_mead_and_powell(self):
        space = opt.ParamSpace([
            opt.ParamSpec("x", 0.0, 4.0, step=0.05),
            opt.ParamSpec("y", 0.0, 4.0, step=0.05),
        ])

        def eval_fn(pt: dict[str, float]) -> dict[str, float]:
            x, y = pt["x"], pt["y"]
            # Minimize (x - 1.5)^2 + (y - 2.0)^2 subject to x + y >= 4.0.
            # Exact constrained optimum on grid: x = 1.75, y = 2.25 -> f = 0.125.
            return {"loss": (x - 1.5) ** 2 + (y - 2.0) ** 2, "sum_xy": x + y}

        x0 = {"x": 3.0, "y": 3.0}
        res_p = opt.polish_local(
            eval_fn, x0, space, objective_key="loss", constraints={"sum_xy": (4.0, None)},
            method="Powell", max_evals=50,
        )
        assert res_p.feasible
        assert res_p.best_objective < 0.15

        res_nm = opt.polish_local(
            eval_fn, x0, space, objective_key="loss", constraints={"sum_xy": (4.0, None)},
            method="Nelder-Mead", max_evals=60,
        )
        assert res_nm.feasible
        assert res_nm.best_objective < 0.15

    def test_high_level_gmid_sizing_helpers(self):
        tbl = gmid.synthetic_ekv_table(
            device_models=("nfet_01v8", "nfet_01v8_lvt", "pfet_01v8", "pfet_01v8_lvt"),
            corners=("ss", "tt", "ff"),
            temps_c=(-40.0, 27.0, 85.0),
            vds_list=(0.4, 0.9, 1.4),
        )
        op = tbl.eval_at_vgs(0.9, 0.15, device_model="nfet_lvt", corner="tt", temp_c=27.0, vds_v=0.9)
        assert op["id_w"] > 0.0 and op["gm_w"] > 0.0 and op["ft_hz"] > 1e9

        inv_fast = gmid.size_cmos_inverter(
            tbl, n_dev="nfet_lvt", p_dev="pfet", l_n=0.15, l_p=0.15,
            conditions=(("tt", 1.80, 27.0), ("ss", 1.65, 85.0), ("ff", 1.95, -40.0)),
        )
        inv_slow = gmid.size_cmos_inverter(
            tbl, n_dev="nfet_lvt", p_dev="pfet_lvt", l_n=0.15, l_p=0.35,
            conditions=(("tt", 1.80, 27.0), ("ss", 1.65, 85.0), ("ff", 1.95, -40.0)),
        )
        assert 1.5 <= inv_fast["opt_wp_over_wn"] <= 6.5
        assert inv_fast["worst_ft_eff_ghz"] > inv_slow["worst_ft_eff_ghz"]

        dp = gmid.size_diff_pair(
            tbl, device_model="nfet_lvt", l_um=0.15, gm_target_s=10e-3, gmid_target=11.0,
            conditions=(("tt", 1.80, 27.0), ("ss", 1.65, 85.0), ("ff", 1.95, -40.0)),
        )
        assert dp["w_total_um"] > 5.0 and dp["nf"] >= 2 and dp["min_bw_ghz"] > 0.5

        cm = gmid.size_current_mirror(
            tbl, device_model="nfet", l_um=0.5, id_target_a=2e-3, gmid_target=10.0,
            vds_min_v=0.40, conditions=(("tt", 27.0), ("ss", 85.0), ("ff", -40.0)),
        )
        assert cm["w_total_um"] > 10.0 and cm["min_ro_kohm"] > 0.5
