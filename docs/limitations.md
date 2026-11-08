# Limitations

PyPSA-VN-PDP8 is a research model. These simplifications matter most when using its results:

- **Single reference years.** 2035 and 2040 are optimised separately. The pathway runs (`_vn_path`) capture path
  dependence between 2035 and 2040, but not lead times or the path before 2035.
- **Transport model.** Inter-regional flows follow a transport model without a nodal power-flow check, so the
  transmission results are indicative. Corridor capacities are derated to 70% of the summed thermal ratings.
- **One weather year for design.** Both systems are dimensioned with the weather of 2024. The ten-year adequacy test
  checks the resulting portfolios, but keeps the demand profile of 2024.
- **Temporal sampling.** Every fourth day plus the peak day, in three-hour steps (`DAY_STEP=4`). The sensitivity
  `_vn_ds2` (every second day) tests this choice.
- **Hydropower and fuel contracts** enter as monthly and annual energy bounds, not as cascades or contract terms.
- **Plan representation.** The plan's targets are national. Their regional split follows the project lists of
  Decision 1509, and the plan's transmission projects are mapped to the 30 regions.
- **Costs** are projections of the Vietnam Technology Catalogue 2026 and the fuel price frameworks of 2025. The
  sensitivities and the Monte Carlo analysis show how the results depend on them.
