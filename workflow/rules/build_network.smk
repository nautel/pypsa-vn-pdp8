# 2024 nodal model of the 500/220/110 kV grid and its benchmark against observed operation (raw data required:
# OpenStreetMap extract, Global Energy Monitor trackers, ERA5, Decision 1509; see README)


rule build_cutout:
    output:
        DATA / "cutouts" / "vietnam-2024-era5.nc",
    log:
        "logs/build_cutout.log",
    shell:
        "python {SCRIPTS:q}/build_vn_cutout.py 2024 > {log} 2>&1"


rule build_topology:
    input:
        [DATA / "osm" / "out" / "out" / f"VN_{k}.geojson" for k in ["line", "cable", "substation"]],
    output:
        [DATA / "grid" / "topology" / f"{k}.csv" for k in ["buses", "lines", "transformers"]],
    log:
        "logs/build_topology.log",
    shell:
        "python {SCRIPTS:q}/build_vn_topology.py > {log} 2>&1"


rule build_plants:
    output:
        DATA / "plants" / "vn_units_gem.csv",
    log:
        "logs/build_plants.log",
    shell:
        "python {SCRIPTS:q}/build_vn_plants.py > {log} 2>&1"


rule build_network:
    input:
        rules.build_topology.output,
        rules.build_plants.output,
    output:
        DATA / "networks" / "vn2024_base.nc",
        DATA / "networks" / "plants_mapped.csv",
        DATA / "networks" / "load_weights.csv",
    log:
        "logs/build_network.log",
    shell:
        "python {SCRIPTS:q}/build_vn_network.py > {log} 2>&1"


rule parse_plan:
    output:
        [DATA / "plans" / f"qd1509_{k}.csv" for k in ["lines", "substations", "hvdc_uhv"]],
    log:
        "logs/parse_plan.log",
    shell:
        "python {SCRIPTS:q}/parse_qd1509.py > {log} 2>&1"


rule geocode_plan:
    input:
        rules.parse_plan.output,
    output:
        DATA / "plans" / "qd1509_lines_geo.csv",
        DATA / "plans" / "qd1509_substations_geo.csv",
    log:
        "logs/geocode_plan.log",
    shell:
        "python {SCRIPTS:q}/geocode_qd1509.py > {log} 2>&1"


rule nodal_vre_profiles:
    input:
        DATA / "networks" / "vn2024_base.nc",
        EXP / "clusters.csv",
        EXP / "cf_solar.csv",
    output:
        DATA / "networks" / "vre_p_max_pu_2024.csv",
    log:
        "logs/nodal_vre_profiles.log",
    shell:
        "python {SCRIPTS:q}/add_vre_profiles_openmeteo.py > {log} 2>&1"


rule validate_2024:
    input:
        DATA / "networks" / "vn2024_base.nc",
        DATA / "networks" / "vre_p_max_pu_2024.csv",
    output:
        DATA / "figures" / "validation" / "validation_2024_annual.csv",
        DATA / "figures" / "validation" / "validation_2024_monthly.csv",
    log:
        "logs/validate_2024.log",
    threads: 4
    shell:
        "bash {SCRIPTS:q}/run_validation_2024.sh 2 2 > {log} 2>&1"


rule build_network_2024:
    input:
        rules.build_network.output,
        rules.geocode_plan.output,
        rules.validate_2024.output,
