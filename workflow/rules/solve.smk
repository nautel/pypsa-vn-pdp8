# Capacity expansion and dispatch runs (scripts/model.py; run set in scripts/run_set.py)


def run_dependencies(wildcards):
    return [RES / f"{d}_summary.json" for d in RUNS[wildcards.run][4]]


def run_environment(wildcards, threads):
    year, scen, tag, env, deps = RUNS[wildcards.run]
    e = dict(run_set.BASE, RUN_TAG=tag, PDP8_TAG=tag, SOLVER=config["solver"]["name"], THREADS=str(threads))
    e.update(env)
    return " ".join(f"{k}={shlex.quote(str(v))}" for k, v in e.items())


rule solve:
    input:
        run_dependencies,
    output:
        network=RES / "{run}.nc",
        summary=RES / "{run}_summary.json",
    log:
        "logs/solve/{run}.log",
    threads: int(config["solver"]["threads"])
    params:
        year=lambda w: RUNS[w.run][0],
        scenario=lambda w: RUNS[w.run][1],
        env=run_environment,
    shell:
        "env {params.env} python -W ignore {SCRIPTS:q}/model.py {params.year} {params.scenario} > {log} 2>&1"


rule solve_all:
    input:
        [RES / f"{r}_summary.json" for r in RUNS],
