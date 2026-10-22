"""PCS conversion / round-trip efficiency runs in battery_ml.

    python 2026_10_02_ml_efficiency_runs.py            # rehearsal: run, verify, ROLLBACK
    python 2026_10_02_ml_efficiency_runs.py --commit   # run for real

efficiency_run    one model generation run: the PCS units, window, split, feature groups, the parameters of the
                  grey-box loss model, the GAM and the residual booster (LightGBM / XGBoost), and the results the
                  pages draw (grey-box coefficients, GAM curves, SHAP, health, curves, RTE summary, predictions).
                  One run can be the default the Efficiency Estimator uses.
efficiency_score  one row per run, model and data set (test / train / cv): R², MAE, RMSE, MAPE, max error, loss MAE
                  in kW and bias - to compare models across runs. Models: greybox, gam, hybrid (grey-box + residual),
                  rte_ac_composed / rte_sys_composed (cycle RTE from measured DC RTE x the PCS model) and dc_rte (the
                  cycle DC round-trip regression, k-fold cross-validated).
efficiency_cycle  per charge-discharge cycle of a run: window, energies (DC / AC / POI / aux / HVAC), SOC, the
                  measured DC / AC / system round-trip efficiencies and the composed / predicted ones.
"""
import sys

import psycopg2

from bess_common.db_settings import psycopg2_dsn  # noqa: E402  (DATABASE_URL from env / backend/.env)

DSN = psycopg2_dsn()

STEPS = [
    """CREATE TABLE battery_ml.efficiency_run (
        run_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        use_case        text        NOT NULL DEFAULT 'efficiency',
        run_name        text,
        status          text        NOT NULL,
        is_default      boolean     NOT NULL DEFAULT false,
        pcs_ids         bigint[]    NOT NULL,
        date_from       date,
        date_to         date,
        split_method    text        NOT NULL,
        test_fraction   numeric     NOT NULL,
        min_load_frac   numeric     NOT NULL,
        feature_groups  text[]      NOT NULL,
        features        text[],
        booster         text        NOT NULL,
        params          jsonb       NOT NULL DEFAULT '{}',
        n_points        integer,
        n_train         integer,
        n_test          integer,
        n_cycles        integer,
        best_model      text,
        metrics         jsonb,
        results         jsonb,
        predictions     jsonb,
        warnings        jsonb       NOT NULL DEFAULT '[]',
        error_message   text,
        artifact_path   text,
        started_at      timestamptz NOT NULL DEFAULT now(),
        finished_at     timestamptz,
        duration_ms     integer,
        CONSTRAINT efficiency_run_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
        CONSTRAINT efficiency_run_split CHECK (split_method IN ('chronological', 'random')),
        CONSTRAINT efficiency_run_booster CHECK (booster IN ('lightgbm', 'xgboost'))
    )""",
    "CREATE UNIQUE INDEX uq_efficiency_run_default ON battery_ml.efficiency_run (use_case) WHERE is_default",
    """CREATE TABLE battery_ml.efficiency_score (
        run_id       bigint  NOT NULL REFERENCES battery_ml.efficiency_run (run_id) ON DELETE CASCADE,
        model        text    NOT NULL,
        dataset      text    NOT NULL,
        n            integer,
        r2           numeric,
        mae          numeric,
        rmse         numeric,
        mape_pct     numeric,
        max_error    numeric,
        median_ae    numeric,
        loss_mae_kw  numeric,
        bias_pp      numeric,
        PRIMARY KEY (run_id, model, dataset),
        CONSTRAINT efficiency_score_dataset CHECK (dataset IN ('train', 'test', 'cv', 'all'))
    )""",
    """CREATE TABLE battery_ml.efficiency_cycle (
        run_id             bigint      NOT NULL REFERENCES battery_ml.efficiency_run (run_id) ON DELETE CASCADE,
        cycle_no           integer     NOT NULL,
        pcs_id             bigint      NOT NULL,
        battery_system_id  bigint,
        start_ts           timestamptz NOT NULL,
        end_ts             timestamptz NOT NULL,
        data_set           text,
        closed             boolean     NOT NULL,
        complete           boolean     NOT NULL,
        e_dc_in_kwh        numeric,
        e_dc_out_kwh       numeric,
        e_ac_in_kwh        numeric,
        e_ac_out_kwh       numeric,
        e_poi_in_kwh       numeric,
        e_poi_out_kwh      numeric,
        e_aux_kwh          numeric,
        e_hvac_kwh         numeric,
        soc_start_pct      numeric,
        soc_end_pct        numeric,
        depth_pct          numeric,
        rte_dc_pct         numeric,
        rte_ac_pct         numeric,
        rte_sys_pct        numeric,
        rte_dc_pred_pct    numeric,
        rte_ac_comp_pct    numeric,
        rte_sys_comp_pct   numeric,
        eta_chg_meas_pct   numeric,
        eta_dis_meas_pct   numeric,
        eta_chg_pred_pct   numeric,
        eta_dis_pred_pct   numeric,
        detail             jsonb       NOT NULL DEFAULT '{}',
        PRIMARY KEY (run_id, cycle_no)
    )""",
]


def main(commit: bool) -> None:
    conn = psycopg2.connect(**DSN)
    cur = conn.cursor()
    for sql in STEPS:
        cur.execute(sql)
    cur.execute("""SELECT table_name FROM information_schema.tables WHERE table_schema = 'battery_ml'
                   AND table_name LIKE 'efficiency%' ORDER BY 1""")
    print("   tables:", [r[0] for r in cur.fetchall()])
    if commit:
        conn.commit()
        print("COMMITTED")
    else:
        conn.rollback()
        print("rehearsal OK - rolled back (run with --commit)")
    conn.close()


if __name__ == "__main__":
    main("--commit" in sys.argv)
