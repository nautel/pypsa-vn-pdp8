# Summary of the run set: figures, tables and key indicators


rule make_summary:
    input:
        rules.solve_all.input,
    output:
        indicators=f"{config['summary']}/key_indicators.csv",
        figures=directory(f"{config['summary']}/figures"),
    log:
        "logs/make_summary.log",
    shell:
        "RES_DIR={RES:q} python -W ignore {SCRIPTS:q}/make_summary.py {config[summary]:q} > {log} 2>&1"
