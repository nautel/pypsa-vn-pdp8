# Inputs of the 30-region expansion model (processed versions are included in the Zenodo archive)


rule cluster_network:
    input:
        DATA / "networks" / "vn2024_base.nc",
    output:
        [EXP / f for f in ["busmap.csv", "clusters.csv", "corridors.csv", "cf_calibration.json"]],
        [EXP / f"cf_{k}.csv" for k in ["solar", "rooftop", "onwind", "offwind"]],
    log:
        "logs/cluster_network.log",
    shell:
        "python {SCRIPTS:q}/prepare.py 30 > {log} 2>&1"


rule plan_sources:
    input:
        EXP / "busmap.csv",
    output:
        DATA / "plans" / "qd1509_sources_by_province.csv",
        DATA / "plans" / "qd1509_sources_by_cluster.csv",
    log:
        "logs/plan_sources.log",
    shell:
        "python {SCRIPTS:q}/parse_qd1509_sources.py > {log} 2>&1"


rule gis_inputs:
    output:
        DATA / "gis" / "worldcover2021_vn_74m.tif",
        DATA / "gis" / "slope_vn_deg_90m.tif",
        DATA / "gis" / "wdpa_vn_terrestrial.gpkg",
    log:
        "logs/gis_inputs.log",
    shell:
        "python -I {SCRIPTS:q}/gis_inputs.py > {log} 2>&1"


rule vre_potentials:
    input:
        rules.gis_inputs.output,
        DATA / "cutouts" / "vietnam-2024-era5.nc",
        EXP / "clusters.csv",
    output:
        [EXP / "gis" / f for f in ["potentials.csv", "cf_solar.csv", "cf_onwind.csv", "calib.json"]],
    log:
        "logs/vre_potentials.log",
    shell:
        "python {SCRIPTS:q}/vre_gis.py > {log} 2>&1"


rule onwind_new_profiles:
    input:
        EXP / "clusters.csv",
    output:
        EXP / "cf_onwind_new.csv",
        EXP / "cf_onwind_new.json",
    log:
        "logs/onwind_new_profiles.log",
    shell:
        "python {SCRIPTS:q}/onwind_new_cf.py > {log} 2>&1"


rule weather_years:
    input:
        EXP / "clusters.csv",
    output:
        directory(EXP / "weather_years"),
    log:
        "logs/weather_years.log",
    shell:
        "(python -I {SCRIPTS:q}/weather_years.py fetch && python -I {SCRIPTS:q}/weather_years.py build) > {log} 2>&1"


rule costs:
    input:
        Path(workflow.basedir) / "repo_data" / "costs" / "costs.csv",
    output:
        [Path(workflow.basedir) / "repo_data" / "costs" / f"costs_{y}.csv" for y in (2035, 2040)],
    log:
        "logs/costs.log",
    shell:
        "python {SCRIPTS:q}/costs_vntc2026.py > {log} 2>&1"


rule build_inputs:
    input:
        rules.cluster_network.output,
        rules.plan_sources.output,
        rules.vre_potentials.output,
        rules.onwind_new_profiles.output,
        rules.weather_years.output,
        rules.costs.output,
