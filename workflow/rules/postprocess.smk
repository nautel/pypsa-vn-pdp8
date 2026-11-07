# Analyses, figures, tables and number macros of the paper


rule paper_assets:
    input:
        rules.solve_all.input,
    output:
        numbers=f"{config['paper_assets']}/numbers.tex",
        figures=directory(f"{config['paper_assets']}/figures"),
    log:
        "logs/paper_assets.log",
    shell:
        "RES_DIR={RES:q} python -W ignore {SCRIPTS:q}/make_paper_assets.py {config[paper_assets]:q} > {log} 2>&1"
